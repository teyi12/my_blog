from django.core.management.base import BaseCommand
from django.db import transaction

from shop.models import Commande


class Command(BaseCommand):
    help = "Corrige les anciennes commandes : définit la currency par défaut et nettoie payment_status."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les corrections sans modifier la base de données.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if dry_run:
            updated = self._process(write=False)
            self.stdout.write(
                self.style.WARNING(
                    f"DRY-RUN : {updated} ligne(s) Commande seraient modifiées."
                )
            )
            return

        with transaction.atomic():
            updated = self._process(write=True)

        self.stdout.write(
            self.style.SUCCESS(f"{updated} ligne(s) Commande modifiées.")
        )

    def _process(self, *, write):
        valid_statuses = {
            value for value, _label in Commande._meta.get_field("payment_status").choices
        }
        updated = 0
        for commande in Commande.objects.all():
            update_fields = []

            # Une commande payée est un historique financier : cette commande
            # de maintenance ne la modifie jamais automatiquement.
            if commande.payment_status == "SUCCESS":
                continue

            if not commande.currency:
                commande.currency = "EUR"
                update_fields.append("currency")

            if not commande.payment_status:
                commande.payment_status = "PENDING"
                update_fields.append("payment_status")
            elif commande.payment_status not in valid_statuses:
                old_status = commande.payment_status
                commande.payment_status = "PENDING"
                update_fields.append("payment_status")
                self.stdout.write(
                    self.style.WARNING(
                        f"Commande {commande.id} : statut invalide "
                        f"'{old_status}' -> 'PENDING'."
                    )
                )

            if not update_fields:
                continue

            updated += 1
            self.stdout.write(
                f"Commande {commande.id} : correction de {', '.join(update_fields)}."
            )
            if write:
                commande.save(update_fields=update_fields)

        return updated
