import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("monetization", "0004_populate_french_monetization_translations"),
        ("payments", "0005_payment_initialization_claim_and_reconcile_pending"),
    ]

    operations = [
        migrations.CreateModel(
            name="DonationPaymentAttempt",
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
                (
                    "devise",
                    models.CharField(
                        choices=[("EUR", "EUR")],
                        default="EUR",
                        max_length=3,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PROCESSING", "En cours"),
                            ("SUCCESS", "Réussi"),
                            ("FAILED", "Échoué"),
                            ("CANCELED", "Annulé"),
                        ],
                        default="PROCESSING",
                        max_length=20,
                    ),
                ),
                (
                    "stripe_session_id",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        null=True,
                        unique=True,
                    ),
                ),
                (
                    "idempotency_key",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        unique=True,
                    ),
                ),
                ("checkout_url", models.URLField(blank=True, max_length=500)),
                ("raw_response", models.JSONField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "don",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="payment_attempt",
                        to="monetization.don",
                    ),
                ),
                (
                    "utilisateur",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="donation_payment_attempts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("devise", "EUR")),
                        name="donation_attempt_eur_only",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("montant__gte", 1)),
                        name="donation_attempt_min_1_eur",
                    ),
                ],
            },
        ),
    ]
