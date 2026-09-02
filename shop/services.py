import time

from django.db import OperationalError, connection
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import CartItem, Commande


class SQLiteLockRetryExhausted(Exception):
    """Un verrou SQLite persiste après toutes les tentatives autorisées."""


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
        commande.cart_finalized_at = timezone.now()
        commande.save(update_fields=["payment_status", "cart_finalized_at"])
        return commande


def finalize_paid_order(order_id):
    """Finalise une commande avec un retry court en cas de verrou SQLite."""
    return execute_with_sqlite_lock_retry(
        lambda: _finalize_paid_order_once(order_id)
    )
