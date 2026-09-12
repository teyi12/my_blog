from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Cart, CartItem, Commande, LigneCommande, Produit


DEFAULT_STOCK_RESERVATION_TIMEOUT_SECONDS = 3600
MIN_STOCK_RESERVATION_TIMEOUT_SECONDS = 1800
MAX_STOCK_RESERVATION_TIMEOUT_SECONDS = 86400


class StockUnavailable(Exception):
    def __init__(self, product_id, requested, available):
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__("stock unavailable")


class InventoryStateConflict(Exception):
    pass


def stock_reservation_timeout_seconds():
    configured = int(
        getattr(
            settings,
            "STOCK_RESERVATION_TIMEOUT_SECONDS",
            DEFAULT_STOCK_RESERVATION_TIMEOUT_SECONDS,
        )
    )
    return min(
        max(configured, MIN_STOCK_RESERVATION_TIMEOUT_SECONDS),
        MAX_STOCK_RESERVATION_TIMEOUT_SECONDS,
    )


def _lock_products(product_ids):
    return {
        product.pk: product
        for product in Produit.objects.select_for_update()
        .filter(pk__in=sorted(set(product_ids)))
        .order_by("pk")
    }


def _ensure_available(product, requested, *, digital=False):
    if digital or product.stock is None:
        return
    if product.stock < requested:
        raise StockUnavailable(product.pk, requested, product.stock)


def add_product_to_cart(cart_id, product_id):
    with transaction.atomic():
        cart = Cart.objects.select_for_update().get(pk=cart_id, actif=True)
        item = (
            CartItem.objects.select_for_update()
            .filter(cart=cart, produit_id=product_id)
            .first()
        )
        product = Produit.objects.select_for_update().get(pk=product_id)
        requested = (item.quantite if item else 0) + 1
        _ensure_available(product, requested, digital=product.est_numerique)
        if item is None:
            return CartItem.objects.create(
                cart=cart,
                produit=product,
                quantite=1,
            )
        item.quantite = requested
        item.save(update_fields=["quantite"])
        return item


def set_cart_item_quantity(cart_id, item_id, quantity):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("invalid cart quantity")

    with transaction.atomic():
        cart = Cart.objects.select_for_update().get(pk=cart_id, actif=True)
        item = CartItem.objects.select_for_update().get(pk=item_id, cart=cart)
        product = Produit.objects.select_for_update().get(pk=item.produit_id)
        _ensure_available(product, quantity, digital=product.est_numerique)
        item.quantite = quantity
        item.save(update_fields=["quantite"])
        return item


def remove_cart_item(cart_id, item_id):
    with transaction.atomic():
        cart = Cart.objects.select_for_update().get(pk=cart_id, actif=True)
        item = CartItem.objects.select_for_update().get(pk=item_id, cart=cart)
        item.delete()


def lock_and_validate_cart_items(cart):
    """Lock and return a cart's valid items inside the caller's transaction."""
    items = list(
        CartItem.objects.select_for_update()
        .filter(cart=cart)
        .order_by("produit_id", "pk")
    )
    products = _lock_products(item.produit_id for item in items)
    for item in items:
        product = products.get(item.produit_id)
        if product is None:
            raise StockUnavailable(item.produit_id, item.quantite, 0)
        item.produit = product
        _ensure_available(
            product,
            item.quantite,
            digital=product.est_numerique,
        )
    return items


def cart_stock_issues(cart):
    issues = {}
    for item in cart.items.select_related("produit"):
        product = item.produit
        if (
            product.stock_est_gere
            and product.stock < item.quantite
        ):
            issues[item.pk] = product.stock
    return issues


def _locked_order_lines_and_products(order):
    lines = list(
        LigneCommande.objects.select_for_update()
        .filter(commande=order)
        .order_by("produit_id", "pk")
    )
    products = _lock_products(
        line.produit_id for line in lines if line.produit_id is not None
    )
    return lines, products


def _reserve_locked_order(order):
    if order.inventory_status in {"RESERVED", "COMMITTED"}:
        return order

    lines, products = _locked_order_lines_and_products(order)
    if any(line.stock_reserved_quantity for line in lines):
        raise InventoryStateConflict

    quantities_by_product = defaultdict(int)
    tracked_lines = []
    for line in lines:
        product = products.get(line.produit_id)
        if (
            product is None
            or line.a_fichier_numerique
            or product.stock is None
        ):
            continue
        quantities_by_product[product.pk] += line.quantite
        tracked_lines.append(line)

    for product_id in sorted(quantities_by_product):
        requested = quantities_by_product[product_id]
        product = products[product_id]
        _ensure_available(product, requested)
        updated = Produit.objects.filter(
            pk=product_id,
            stock__gte=requested,
        ).update(stock=F("stock") - requested)
        if updated != 1:
            product.refresh_from_db(fields=["stock"])
            raise StockUnavailable(product_id, requested, product.stock or 0)

    for line in tracked_lines:
        line.stock_reserved_quantity = line.quantite
    if tracked_lines:
        LigneCommande.objects.bulk_update(
            tracked_lines,
            ["stock_reserved_quantity"],
        )

    order.inventory_status = "RESERVED"
    order.stock_reservation_expires_at = timezone.now() + timedelta(
        seconds=stock_reservation_timeout_seconds()
    )
    order.save(
        update_fields=["inventory_status", "stock_reservation_expires_at"]
    )
    return order


def reserve_order_stock(order_id):
    with transaction.atomic():
        order = Commande.objects.select_for_update().get(pk=order_id)
        return _reserve_locked_order(order)


def commit_order_stock(order_id):
    with transaction.atomic():
        order = Commande.objects.select_for_update().get(pk=order_id)
        if order.inventory_status == "COMMITTED":
            return order
        if order.inventory_status != "RESERVED":
            _reserve_locked_order(order)
        order.inventory_status = "COMMITTED"
        order.stock_reservation_expires_at = None
        order.save(
            update_fields=["inventory_status", "stock_reservation_expires_at"]
        )
        return order


def release_order_stock(order_id):
    with transaction.atomic():
        order = Commande.objects.select_for_update().get(pk=order_id)
        if order.inventory_status != "RESERVED":
            return order
        if order.payment_status in {"SUCCESS", "REFUNDED"}:
            order.inventory_status = "COMMITTED"
            order.stock_reservation_expires_at = None
            order.save(
                update_fields=[
                    "inventory_status",
                    "stock_reservation_expires_at",
                ]
            )
            return order

        lines, products = _locked_order_lines_and_products(order)
        quantities_by_product = defaultdict(int)
        reserved_lines = []
        for line in lines:
            if line.stock_reserved_quantity <= 0:
                continue
            if line.produit_id in products:
                quantities_by_product[line.produit_id] += (
                    line.stock_reserved_quantity
                )
            line.stock_reserved_quantity = 0
            reserved_lines.append(line)

        for product_id in sorted(quantities_by_product):
            Produit.objects.filter(pk=product_id).update(
                stock=F("stock") + quantities_by_product[product_id]
            )
        if reserved_lines:
            LigneCommande.objects.bulk_update(
                reserved_lines,
                ["stock_reserved_quantity"],
            )

        order.inventory_status = "RELEASED"
        order.stock_reservation_expires_at = None
        order.save(
            update_fields=["inventory_status", "stock_reservation_expires_at"]
        )
        return order
