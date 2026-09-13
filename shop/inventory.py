from collections import defaultdict
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import (
    Cart,
    CartItem,
    Commande,
    LigneCommande,
    Produit,
    StockMovement,
)


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


class InvalidStockAdjustment(Exception):
    pass


class InventoryNotManaged(Exception):
    pass


class OrderNotRestockable(Exception):
    pass


class OrderAlreadyRestocked(Exception):
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


def _assert_staff(actor):
    if actor is None or not actor.is_authenticated or not actor.is_staff:
        raise PermissionDenied


def _movement_key(action, order, line):
    return f"inventory:{action}:order:{order.pk}:cycle:{order.inventory_cycle}:line:{line.pk}"


def _create_movement(
    *,
    product,
    movement_type,
    quantity,
    stock_before,
    stock_after,
    reason,
    idempotency_key,
    order=None,
    line=None,
    actor=None,
):
    existing = StockMovement.objects.filter(
        idempotency_key=idempotency_key
    ).first()
    if existing is not None:
        expected = (
            product.pk,
            movement_type,
            quantity,
            order.pk if order else None,
            line.pk if line else None,
            actor.pk if actor else None,
        )
        actual = (
            existing.product_id_snapshot,
            existing.movement_type,
            existing.quantity,
            existing.commande_id,
            existing.ligne_id,
            existing.actor_id,
        )
        if actual != expected:
            raise InventoryStateConflict
        return existing, False

    movement = StockMovement.objects.create(
        produit=product,
        product_id_snapshot=product.pk,
        product_name_snapshot=product.nom,
        movement_type=movement_type,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        reason=reason,
        commande=order,
        ligne=line,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    return movement, True


def _change_locked_product_stock(
    product,
    quantity,
    *,
    movement_type,
    reason,
    idempotency_key,
    order=None,
    line=None,
    actor=None,
    allow_digital=False,
):
    if product.stock is None or (product.est_numerique and not allow_digital):
        raise InventoryNotManaged
    stock_before = product.stock
    stock_after = stock_before + quantity
    if stock_after < 0:
        raise StockUnavailable(product.pk, abs(quantity), stock_before)

    movement, created = _create_movement(
        product=product,
        movement_type=movement_type,
        quantity=quantity,
        stock_before=stock_before,
        stock_after=stock_after,
        reason=reason,
        idempotency_key=idempotency_key,
        order=order,
        line=line,
        actor=actor,
    )
    if not created:
        return movement

    product.stock = stock_after
    product.save(update_fields=["stock"])
    return movement


def _record_locked_product_decision(
    product,
    *,
    movement_type,
    reason,
    idempotency_key,
    order,
    line,
):
    if product.stock is None:
        raise InventoryNotManaged
    movement, _created = _create_movement(
        product=product,
        movement_type=movement_type,
        quantity=0,
        stock_before=product.stock,
        stock_after=product.stock,
        reason=reason,
        idempotency_key=idempotency_key,
        order=order,
        line=line,
    )
    return movement


def adjust_product_stock(product_id, quantity, reason, actor, idempotency_key):
    _assert_staff(actor)
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity == 0:
        raise InvalidStockAdjustment
    reason = str(reason or "").strip()
    if not reason:
        raise InvalidStockAdjustment
    idempotency_key = str(idempotency_key or "").strip()
    if not idempotency_key:
        raise InvalidStockAdjustment

    with transaction.atomic():
        product = Produit.objects.select_for_update().get(pk=product_id)
        existing = StockMovement.objects.filter(
            idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            if (
                existing.produit_id != product.pk
                or existing.movement_type != "MANUAL"
                or existing.quantity != quantity
                or existing.reason != reason
                or existing.actor_id != actor.pk
            ):
                raise InventoryStateConflict
            return existing
        return _change_locked_product_stock(
            product,
            quantity,
            movement_type="MANUAL",
            reason=reason,
            idempotency_key=idempotency_key,
            actor=actor,
        )


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

    tracked_lines = []
    for line in lines:
        product = products.get(line.produit_id)
        if (
            product is None
            or line.a_fichier_numerique
            or product.stock is None
        ):
            continue
        tracked_lines.append(line)

    quantities_by_product = defaultdict(int)
    for line in tracked_lines:
        quantities_by_product[line.produit_id] += line.quantite
    for product_id, requested in quantities_by_product.items():
        _ensure_available(products[product_id], requested)

    order.inventory_cycle += 1
    for line in tracked_lines:
        product = products[line.produit_id]
        _change_locked_product_stock(
            product,
            -line.quantite,
            movement_type="RESERVATION",
            reason=_("Réservation pour la commande #%(order)s")
            % {"order": order.pk},
            idempotency_key=_movement_key("reserve", order, line),
            order=order,
            line=line,
        )

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
        update_fields=[
            "inventory_status",
            "inventory_cycle",
            "stock_reservation_expires_at",
        ]
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
        lines, products = _locked_order_lines_and_products(order)
        for line in lines:
            if line.stock_reserved_quantity <= 0:
                continue
            product = products.get(line.produit_id)
            if product is None:
                raise InventoryStateConflict
            _record_locked_product_decision(
                product,
                movement_type="SALE",
                reason=_("Vente confirmée pour la commande #%(order)s")
                % {"order": order.pk},
                idempotency_key=_movement_key("sale", order, line),
                order=order,
                line=line,
            )
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
        reserved_lines = []
        for line in lines:
            if line.stock_reserved_quantity <= 0:
                continue
            product = products.get(line.produit_id)
            if product is None:
                raise InventoryStateConflict
            _change_locked_product_stock(
                product,
                line.stock_reserved_quantity,
                movement_type="RELEASE",
                reason=_("Libération pour la commande #%(order)s")
                % {"order": order.pk},
                idempotency_key=_movement_key("release", order, line),
                order=order,
                line=line,
                allow_digital=True,
            )
            line.stock_reserved_quantity = 0
            reserved_lines.append(line)

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


def restock_refunded_order(order_id, actor):
    _assert_staff(actor)
    with transaction.atomic():
        order = Commande.objects.select_for_update().get(pk=order_id)
        if order.inventory_status == "RESTOCKED":
            raise OrderAlreadyRestocked
        if order.payment_status != "REFUNDED" or order.inventory_status != "COMMITTED":
            raise OrderNotRestockable

        lines, products = _locked_order_lines_and_products(order)
        reserved_lines = [line for line in lines if line.stock_reserved_quantity > 0]
        if not reserved_lines:
            raise OrderNotRestockable

        for line in reserved_lines:
            product = products.get(line.produit_id)
            reservation_exists = StockMovement.objects.filter(
                idempotency_key=_movement_key("reserve", order, line),
                movement_type="RESERVATION",
                quantity=-line.stock_reserved_quantity,
            ).exists()
            if (
                product is None
                or line.a_fichier_numerique
                or product.est_numerique
                or product.stock is None
                or not reservation_exists
            ):
                raise OrderNotRestockable

        for line in reserved_lines:
            product = products[line.produit_id]
            _change_locked_product_stock(
                product,
                line.stock_reserved_quantity,
                movement_type="RESTOCK",
                reason=_("Remise en stock après remboursement de la commande #%(order)s")
                % {"order": order.pk},
                idempotency_key=_movement_key("restock", order, line),
                order=order,
                line=line,
                actor=actor,
            )

        order.inventory_status = "RESTOCKED"
        order.save(update_fields=["inventory_status"])
        return order
