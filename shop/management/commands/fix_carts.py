from django.core.management.base import BaseCommand
from django.db import transaction

from shop.models import CartItem


class Command(BaseCommand):
    help = "Corrige les paniers en recalculant les prix unitaires manquants."

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
                    f"DRY-RUN : {updated} ligne(s) CartItem seraient modifiées."
                )
            )
            return

        with transaction.atomic():
            updated = self._process(write=True)

        self.stdout.write(
            self.style.SUCCESS(f"{updated} ligne(s) CartItem modifiées.")
        )

    def _process(self, *, write):
        updated = 0
        for item in CartItem.objects.select_related("produit", "cart").all():
            # None signifie "prix manquant" ; Decimal("0") reste un prix valide.
            if item.prix_unitaire is not None:
                continue

            updated += 1
            self.stdout.write(
                f"CartItem {item.id} : prix manquant -> {item.produit.prix}"
            )
            if write:
                item.prix_unitaire = item.produit.prix
                item.save(update_fields=["prix_unitaire"])

        return updated
