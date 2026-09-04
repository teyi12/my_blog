from contextlib import contextmanager

from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Count, Q, Sum

from shop.models import Cart, CartItem, Commande, LigneCommande


@contextmanager
def read_only_transaction():
    """Use a database-enforced read-only transaction when PostgreSQL supports it."""
    if connection.vendor == "postgresql":
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION READ ONLY")
            yield
        return

    yield


class Command(BaseCommand):
    help = "Audite l’intégrité des paniers sans modifier la base de données."

    def handle(self, *args, **options):
        with read_only_transaction():
            report = self._build_report()
            self._write_report(report)

    def _build_report(self):
        user_cart_counts = list(
            Cart.objects.exclude(user_id=None)
            .values("user_id")
            .annotate(cart_count=Count("id"))
            .filter(cart_count__gt=1)
        )
        multiple_user_ids = [row["user_id"] for row in user_cart_counts]

        duplicate_groups = list(
            CartItem.objects.values("cart_id", "produit_id")
            .annotate(
                line_count=Count("id"),
                quantity_sum=Sum("quantite"),
                distinct_price_count=Count("prix_unitaire", distinct=True),
                null_price_count=Count(
                    "id",
                    filter=Q(prix_unitaire__isnull=True),
                ),
            )
            .filter(line_count__gt=1)
            .order_by("cart_id", "produit_id")
        )

        max_quantity = connection.ops.integer_field_range(
            CartItem._meta.get_field("quantite").get_internal_type()
        )[1]
        divergent_price_groups = 0
        historically_multiple_referenced_groups = 0
        overflow_groups = []

        for group in duplicate_groups:
            price_variants = group["distinct_price_count"] + bool(
                group["null_price_count"]
            )
            group["has_divergent_prices"] = price_variants > 1
            if group["has_divergent_prices"]:
                divergent_price_groups += 1

            referenced_item_count = (
                CartItem.objects.filter(
                    cart_id=group["cart_id"],
                    produit_id=group["produit_id"],
                    lignes_commande__isnull=False,
                )
                .distinct()
                .count()
            )
            group["referenced_item_count"] = referenced_item_count
            if referenced_item_count > 1:
                historically_multiple_referenced_groups += 1

            if group["quantity_sum"] > max_quantity:
                overflow_groups.append(
                    (group["cart_id"], group["produit_id"], group["quantity_sum"])
                )

        return {
            "total_carts": Cart.objects.count(),
            "authenticated_carts": Cart.objects.exclude(user_id=None).count(),
            "anonymous_carts": Cart.objects.filter(user_id=None).count(),
            "users_with_multiple_carts": len(user_cart_counts),
            "max_carts_per_user": max(
                (row["cart_count"] for row in user_cart_counts),
                default=int(
                    Cart.objects.exclude(user_id=None).values("user_id").exists()
                ),
            ),
            "referenced_carts": Cart.objects.filter(commandes__isnull=False)
            .distinct()
            .count(),
            "multiple_carts_referenced_by_pending_orders": Cart.objects.filter(
                user_id__in=multiple_user_ids,
                commandes__payment_status="PENDING",
            )
            .distinct()
            .count(),
            "total_cart_items": CartItem.objects.count(),
            "duplicate_groups": duplicate_groups,
            "divergent_price_groups": divergent_price_groups,
            "referenced_cart_items": CartItem.objects.filter(
                lignes_commande__isnull=False
            )
            .distinct()
            .count(),
            "cart_item_historical_references": LigneCommande.objects.exclude(
                source_cart_item_id=None
            ).count(),
            "historically_multiple_referenced_groups": (
                historically_multiple_referenced_groups
            ),
            "unfinalized_orders_with_source_cart": Commande.objects.filter(
                source_cart_id__isnull=False,
                cart_finalized_at__isnull=True,
            ).count(),
            "max_quantity": max_quantity,
            "overflow_groups": overflow_groups,
        }

    def _write_report(self, report):
        self.stdout.write("=== Audit d’intégrité des paniers (lecture seule) ===")
        self.stdout.write(f"Nombre total de paniers : {report['total_carts']}")
        self.stdout.write(
            f"Paniers authentifiés : {report['authenticated_carts']}"
        )
        self.stdout.write(f"Paniers anonymes : {report['anonymous_carts']}")
        self.stdout.write(
            "Utilisateurs possédant plusieurs paniers : "
            f"{report['users_with_multiple_carts']}"
        )
        self.stdout.write(
            f"Nombre maximal de paniers pour un utilisateur : "
            f"{report['max_carts_per_user']}"
        )
        self.stdout.write(
            f"Paniers référencés par une commande : {report['referenced_carts']}"
        )
        self.stdout.write(
            "Paniers de groupes multi-paniers référencés par des commandes "
            "en attente : "
            f"{report['multiple_carts_referenced_by_pending_orders']}"
        )
        self.stdout.write(
            f"Nombre total de lignes de panier : {report['total_cart_items']}"
        )
        self.stdout.write(
            f"Couples (cart, produit) dupliqués : {len(report['duplicate_groups'])}"
        )

        for group in report["duplicate_groups"]:
            self.stdout.write(
                "  - cart_id={cart_id}, produit_id={produit_id}, lignes={line_count}, "
                "quantité_fusionnée={quantity_sum}, prix_divergents={prices}, "
                "lignes_référencées={referenced_item_count}".format(
                    prices="oui" if group["has_divergent_prices"] else "non",
                    **group,
                )
            )

        self.stdout.write(
            "Groupes dupliqués ayant plusieurs prix unitaires distincts : "
            f"{report['divergent_price_groups']}"
        )
        self.stdout.write(
            "Lignes de panier référencées par LigneCommande : "
            f"{report['referenced_cart_items']}"
        )
        self.stdout.write(
            "Références historiques LigneCommande vers ces lignes : "
            f"{report['cart_item_historical_references']}"
        )
        self.stdout.write(
            "Doublons dont plusieurs lignes sont référencées historiquement : "
            f"{report['historically_multiple_referenced_groups']}"
        )
        self.stdout.write(
            "Commandes non finalisées utilisant un panier source : "
            f"{report['unfinalized_orders_with_source_cart']}"
        )

        if report["overflow_groups"]:
            self.stdout.write(
                self.style.WARNING(
                    "AVERTISSEMENT : une quantité fusionnée dépasse la capacité "
                    f"du champ ({report['max_quantity']})."
                )
            )
            for cart_id, produit_id, quantity in report["overflow_groups"]:
                self.stdout.write(
                    f"  - cart_id={cart_id}, produit_id={produit_id}, "
                    f"quantité_fusionnée={quantity}"
                )
        else:
            self.stdout.write(
                "Risque de dépassement de capacité des quantités fusionnées : aucun"
            )
