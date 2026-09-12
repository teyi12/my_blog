from datetime import timedelta

import stripe
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from payments.models import Payment
from payments.views import (
    PaymentChannelConflict,
    _confirm_payment_once,
    _lock_order_then_payment,
    _minor_amount,
    _stripe_value,
)
from shop.services import SQLiteLockRetryExhausted, execute_with_sqlite_lock_retry


DEFAULT_OLDER_THAN_MINUTES = 60
DEFAULT_LIMIT = 100


class ReconciliationMismatch(Exception):
    """Stripe and the locked local payment do not describe the same payment."""


def _stripe_session_matches(commande, payment, session):
    metadata = _stripe_value(session, "metadata") or {}
    try:
        expected_amount = _minor_amount(payment.montant, payment.devise)
    except (TypeError, ValueError, ArithmeticError):
        return False

    return (
        payment.channel == "STRIPE"
        and payment.status == "PROCESSING"
        and payment.transaction_id.startswith("cs_")
        and commande.id == payment.commande_id
        and commande.client_id is not None
        and commande.payment_channel == "STRIPE"
        and commande.payment_status == "PROCESSING"
        and commande.transaction_id == payment.transaction_id
        and _stripe_value(session, "id") == payment.transaction_id
        and str(_stripe_value(metadata, "commande_id") or "")
        == str(commande.id)
        and str(_stripe_value(metadata, "payment_id") or "") == str(payment.id)
        and str(_stripe_value(metadata, "user_id") or "")
        == str(commande.client_id)
        and _stripe_value(session, "amount_total") == expected_amount
        and str(_stripe_value(session, "currency") or "").upper()
        == payment.devise.upper()
        and payment.montant == commande.total
        and payment.devise.upper() == commande.currency.upper()
    )


def _safe_confirmation_record():
    # Deliberately excludes the Checkout Session ID and the provider payload.
    return {
        "source": "stripe_payment_reconciliation",
        "payment_status": "paid",
    }


def _confirm_matching_payment(payment_id, session):
    """Validate under lock, then use the existing transactional finalizer."""

    def confirm_once():
        with transaction.atomic():
            commande, payment = _lock_order_then_payment(payment_id)
            if not _stripe_session_matches(commande, payment, session):
                raise ReconciliationMismatch
            if (
                _stripe_value(session, "payment_status") != "paid"
                or _stripe_value(session, "status") != "complete"
            ):
                raise ReconciliationMismatch
            return _confirm_payment_once(payment.id, _safe_confirmation_record())

    return execute_with_sqlite_lock_retry(confirm_once)


class Command(BaseCommand):
    help = (
        "Réconcilie prudemment les paiements Stripe PROCESSING dont la Checkout "
        "Session est payée. Lecture seule sans --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Confirmer réellement les paiements strictement compatibles.",
        )
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=DEFAULT_OLDER_THAN_MINUTES,
            help=(
                "Examiner les paiements non mis à jour depuis au moins ce délai "
                f"(défaut : {DEFAULT_OLDER_THAN_MINUTES})."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"Nombre maximal de paiements examinés (défaut : {DEFAULT_LIMIT}).",
        )

    def handle(self, *args, **options):
        older_than_minutes = options["older_than_minutes"]
        limit = options["limit"]
        apply_changes = options["apply"]
        if older_than_minutes <= 0:
            raise CommandError("--older-than-minutes doit être strictement positif.")
        if limit <= 0:
            raise CommandError("--limit doit être strictement positif.")

        cutoff = timezone.now() - timedelta(minutes=older_than_minutes)
        candidate_ids = list(
            Payment.objects.filter(
                channel="STRIPE",
                status="PROCESSING",
                updated_at__lte=cutoff,
                transaction_id__startswith="cs_",
            )
            .order_by("updated_at", "pk")
            .values_list("pk", flat=True)[:limit]
        )

        counters = {
            "examines": 0,
            "recuperes": 0,
            "ignores": 0,
            "incompatibles": 0,
            "erreurs": 0,
        }
        dry_run_recoverable = 0

        for payment_id in candidate_ids:
            counters["examines"] += 1
            try:
                payment = Payment.objects.select_related("commande").get(
                    pk=payment_id,
                    channel="STRIPE",
                    status="PROCESSING",
                    updated_at__lte=cutoff,
                    transaction_id__startswith="cs_",
                )
            except Payment.DoesNotExist:
                counters["incompatibles"] += 1
                continue

            try:
                session = stripe.checkout.Session.retrieve(payment.transaction_id)
            except stripe.StripeError as exc:
                counters["erreurs"] += 1
                self.stderr.write(
                    self.style.WARNING(
                        "Erreur Stripe attendue ignorée pour un paiement local "
                        f"(type={type(exc).__name__})."
                    )
                )
                continue

            if not _stripe_session_matches(payment.commande, payment, session):
                counters["incompatibles"] += 1
                continue
            if (
                _stripe_value(session, "payment_status") != "paid"
                or _stripe_value(session, "status") != "complete"
            ):
                counters["ignores"] += 1
                continue

            if not apply_changes:
                counters["ignores"] += 1
                dry_run_recoverable += 1
                continue

            try:
                _confirm_matching_payment(payment.id, session)
            except (
                Payment.DoesNotExist,
                PaymentChannelConflict,
                ReconciliationMismatch,
            ):
                counters["incompatibles"] += 1
            except SQLiteLockRetryExhausted:
                counters["erreurs"] += 1
            else:
                counters["recuperes"] += 1

        mode = "APPLICATION" if apply_changes else "LECTURE SEULE"
        self.stdout.write(f"Mode : {mode}")
        if dry_run_recoverable:
            self.stdout.write(
                f"Paiements payés récupérables : {dry_run_recoverable}"
            )
        self.stdout.write(
            "Résumé : "
            f"examinés={counters['examines']}, "
            f"payés récupérés={counters['recuperes']}, "
            f"ignorés={counters['ignores']}, "
            f"incompatibles={counters['incompatibles']}, "
            f"erreurs={counters['erreurs']}"
        )
