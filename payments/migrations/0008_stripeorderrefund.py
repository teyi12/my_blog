import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0007_stripewebhookevent_stripesubscription_and_more"),
        ("shop", "0020_alter_commande_payment_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="StripeOrderRefund",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("montant", models.DecimalField(decimal_places=2, max_digits=10)),
                ("devise", models.CharField(max_length=10)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PROCESSING", "Traitement en cours"),
                            ("PENDING", "En attente de confirmation"),
                            ("SUCCESS", "Remboursé"),
                            ("RETRYABLE", "Nouvel essai requis"),
                            ("FAILED", "Échoué"),
                            ("CANCELED", "Annulé"),
                        ],
                        default="PROCESSING",
                        max_length=20,
                    ),
                ),
                (
                    "stripe_payment_intent_id",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=255,
                        null=True,
                        unique=True,
                    ),
                ),
                (
                    "stripe_refund_id",
                    models.CharField(
                        blank=True,
                        editable=False,
                        max_length=255,
                        null=True,
                        unique=True,
                    ),
                ),
                (
                    "idempotency_key",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "confirmed_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "commande",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stripe_refund",
                        to="shop.commande",
                    ),
                ),
                (
                    "payment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="stripe_refund",
                        to="payments.payment",
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_stripe_order_refunds",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("montant__gt", 0)),
                        name="stripe_order_refund_positive_amount",
                    ),
                ],
            },
        ),
    ]
