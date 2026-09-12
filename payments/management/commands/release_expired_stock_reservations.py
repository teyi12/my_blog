from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from payments.models import Payment
from payments.views import _resolve_expired_payment
from shop.inventory import (
    StockUnavailable,
    commit_order_stock,
    release_order_stock,
)
from shop.models import Commande
from shop.services import SQLiteLockRetryExhausted


DEFAULT_LIMIT = 100


class Command(BaseCommand):
    help = (
        "Vérifie et libère les réservations de stock expirées. "
        "Lecture seule sans --apply."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Vérifier les paiements et appliquer les libérations sûres.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"Nombre maximal de réservations examinées (défaut : {DEFAULT_LIMIT}).",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        apply_changes = options["apply"]
        if limit <= 0:
            raise CommandError("--limit doit être strictement positif.")

        order_ids = list(
            Commande.objects.filter(
                inventory_status="RESERVED",
                stock_reservation_expires_at__lte=timezone.now(),
            )
            .order_by("stock_reservation_expires_at", "pk")
            .values_list("pk", flat=True)[:limit]
        )
        counters = {
            "examined": 0,
            "released": 0,
            "committed": 0,
            "active": 0,
            "errors": 0,
        }

        for order_id in order_ids:
            counters["examined"] += 1
            if not apply_changes:
                counters["active"] += 1
                continue

            try:
                order = Commande.objects.get(pk=order_id)
                if order.payment_status in {"SUCCESS", "REFUNDED"}:
                    commit_order_stock(order.id)
                    counters["committed"] += 1
                    continue

                payment = (
                    Payment.objects.filter(
                        commande=order,
                        status="PROCESSING",
                    )
                    .order_by("pk")
                    .first()
                )
                if payment is not None:
                    outcome = _resolve_expired_payment(payment.id)
                    if outcome == "SUCCESS":
                        counters["committed"] += 1
                    elif outcome == "TERMINAL":
                        counters["released"] += 1
                    else:
                        counters["active"] += 1
                    continue

                release_order_stock(order.id)
                counters["released"] += 1
            except (
                Commande.DoesNotExist,
                Payment.DoesNotExist,
                SQLiteLockRetryExhausted,
                StockUnavailable,
            ):
                counters["errors"] += 1

        mode = "APPLICATION" if apply_changes else "LECTURE SEULE"
        self.stdout.write(f"Mode : {mode}")
        self.stdout.write(
            "Résumé : "
            f"examinées={counters['examined']}, "
            f"libérées={counters['released']}, "
            f"confirmées={counters['committed']}, "
            f"encore actives={counters['active']}, "
            f"erreurs={counters['errors']}"
        )
