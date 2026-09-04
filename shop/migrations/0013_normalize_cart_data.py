from django.db import migrations
from django.db.models import Count, Sum


def normalize_cart_data(apps, schema_editor):
    Cart = apps.get_model("shop", "Cart")
    CartItem = apps.get_model("shop", "CartItem")
    LigneCommande = apps.get_model("shop", "LigneCommande")
    database = schema_editor.connection.alias

    duplicate_groups = list(
        CartItem.objects.using(database)
        .values("cart_id", "produit_id")
        .annotate(line_count=Count("id"), quantity_sum=Sum("quantite"))
        .filter(line_count__gt=1)
        .order_by("cart_id", "produit_id")
    )

    max_quantity = schema_editor.connection.ops.integer_field_range(
        CartItem._meta.get_field("quantite").get_internal_type()
    )[1]
    for group in duplicate_groups:
        prices = set(
            CartItem.objects.using(database)
            .filter(
                cart_id=group["cart_id"],
                produit_id=group["produit_id"],
                prix_unitaire__isnull=False,
            )
            .values_list("prix_unitaire", flat=True)
        )
        if len(prices) > 1:
            raise RuntimeError(
                "Migration interrompue : prix unitaires divergents pour "
                f"cart_id={group['cart_id']}, produit_id={group['produit_id']}."
            )
        if group["quantity_sum"] > max_quantity:
            raise RuntimeError(
                "Migration interrompue : quantité fusionnée hors capacité pour "
                f"cart_id={group['cart_id']}, produit_id={group['produit_id']}."
            )

    duplicate_users = (
        Cart.objects.using(database)
        .exclude(user_id=None)
        .values("user_id")
        .annotate(cart_count=Count("id"))
        .filter(cart_count__gt=1)
        .order_by("user_id")
    )
    for group in duplicate_users.iterator():
        cart_ids = list(
            Cart.objects.using(database)
            .filter(user_id=group["user_id"])
            .order_by("id")
            .values_list("id", flat=True)
        )
        Cart.objects.using(database).filter(id=cart_ids[0]).update(actif=True)
        Cart.objects.using(database).filter(id__in=cart_ids[1:]).update(actif=False)

    for group in duplicate_groups:
        item_ids = list(
            CartItem.objects.using(database)
            .filter(
                cart_id=group["cart_id"],
                produit_id=group["produit_id"],
            )
            .order_by("id")
            .values_list("id", flat=True)
        )
        canonical_id = item_ids[0]
        redundant_ids = item_ids[1:]
        LigneCommande.objects.using(database).filter(
            source_cart_item_id__in=redundant_ids
        ).update(source_cart_item_id=canonical_id)
        CartItem.objects.using(database).filter(id=canonical_id).update(
            quantite=group["quantity_sum"]
        )
        CartItem.objects.using(database).filter(id__in=redundant_ids).delete()


def preserve_normalized_data(apps, schema_editor):
    # Les anciennes répartitions ne peuvent pas être reconstruites sans ambiguïté.
    pass


class Migration(migrations.Migration):
    atomic = True

    dependencies = [
        ("shop", "0012_cart_actif"),
    ]

    operations = [
        migrations.RunPython(normalize_cart_data, preserve_normalized_data),
    ]
