import time

from django.db import IntegrityError, OperationalError, connection
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Cart, CartItem, Commande


class SQLiteLockRetryExhausted(Exception):
    """Un verrou SQLite persiste après toutes les tentatives autorisées."""


def get_or_create_active_cart(user):
    """Return the sole active cart for an authenticated user."""
    if not user.is_authenticated:
        raise ValueError("Un panier utilisateur nécessite un utilisateur authentifié.")

    try:
        with transaction.atomic():
            cart = Cart.objects.filter(user=user, actif=True).first()
            if cart is not None:
                return cart
            return Cart.objects.create(user=user, actif=True)
    except IntegrityError:
        # Une transaction concurrente a pu créer le panier entre SELECT et INSERT.
        return Cart.objects.get(user=user, actif=True)


def _is_sqlite_lock_error(exc):
    if connection.vendor != "sqlite":
        return False
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


def execute_with_sqlite_lock_retry(operation, attempts=3, base_delay=0.05):
    """Relance une opération uniquement pour les erreurs de verrou SQLite connues."""
    for attempt in range(attempts):
        try:
            return operation()
        except OperationalError as exc:
            if not _is_sqlite_lock_error(exc):
                raise
            if attempt == attempts - 1:
                raise SQLiteLockRetryExhausted from exc
            time.sleep(base_delay * (attempt + 1))


def _finalize_paid_order_once(order_id):
    with transaction.atomic():
        commande = (
            Commande.objects.select_for_update()
            .prefetch_related("lignes")
            .get(pk=order_id)
        )

        if commande.cart_finalized_at is not None:
            if commande.payment_status == "SUCCESS" and commande.fulfillment_status == "WAITING_PAYMENT":
                commande.fulfillment_status = "TO_PREPARE"
                commande.save(update_fields=["fulfillment_status"])
            return commande

        if commande.source_cart_id:
            for ligne in commande.lignes.all():
                if not ligne.source_cart_item_id:
                    continue

                item = (
                    CartItem.objects.select_for_update()
                    .filter(
                        pk=ligne.source_cart_item_id,
                        cart_id=commande.source_cart_id,
                        produit_id=ligne.produit_id,
                    )
                    .first()
                )
                if not item:
                    continue

                updated = CartItem.objects.filter(
                    pk=item.pk,
                    quantite__gt=ligne.quantite,
                ).update(quantite=F("quantite") - ligne.quantite)
                if not updated:
                    CartItem.objects.filter(
                        pk=item.pk,
                        quantite__lte=ligne.quantite,
                    ).delete()

        commande.payment_status = "SUCCESS"
        if commande.fulfillment_status == "WAITING_PAYMENT":
            commande.fulfillment_status = "TO_PREPARE"
        commande.cart_finalized_at = timezone.now()
        commande.save(
            update_fields=["payment_status", "fulfillment_status", "cart_finalized_at"]
        )
        return commande


def finalize_paid_order(order_id):
    """Finalise une commande avec un retry court en cas de verrou SQLite."""
    return execute_with_sqlite_lock_retry(
        lambda: _finalize_paid_order_once(order_id)
    )
