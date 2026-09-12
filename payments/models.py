from django.db import models
from django.conf import settings
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from shop.models import Commande
import uuid


class Payment(models.Model):
    STATUS_CHOICES = [
        ("PENDING", _("En attente")),
        ("PROCESSING", _("En cours")),
        ("SUCCESS", _("Réussi")),
        ("FAILED", _("Échoué")),
        ("CANCELED", _("Annulé")),
    ]

    CHANNEL_CHOICES = [
        ("STRIPE", "Stripe"),
        ("MOBILE_MONEY", "Mobile Money"),
        ("CINETPAY", "CinetPay"),
        ("CARD", _("Carte bancaire")),
        ("OTHER", _("Autre")),
    ]

    commande = models.ForeignKey(
        Commande,
        on_delete=models.CASCADE,
        related_name="payments"
    )
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    devise = models.CharField(max_length=10, default="EUR")

    # Infos transaction
    transaction_id = models.CharField(max_length=100, unique=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    checkout_url = models.URLField(max_length=500, blank=True)
    initialization_token = models.UUIDField(null=True, blank=True, editable=False)
    initialization_started_at = models.DateTimeField(null=True, blank=True, editable=False)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="STRIPE")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    # Infos supplémentaires
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    raw_response = models.JSONField(blank=True, null=True)  # log brut du prestataire

    def __str__(self):
        return f"Paiement {self.channel} - {self.transaction_id} - {self.status}"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["commande"],
                condition=Q(status="PROCESSING"),
                name="one_processing_payment_per_order",
            )
        ]


class StripeOrderRefund(models.Model):
    STATUS_CHOICES = [
        ("PROCESSING", _("Traitement en cours")),
        ("PENDING", _("En attente de confirmation")),
        ("SUCCESS", _("Remboursé")),
        ("RETRYABLE", _("Nouvel essai requis")),
        ("FAILED", _("Échoué")),
        ("CANCELED", _("Annulé")),
    ]

    commande = models.OneToOneField(
        Commande,
        on_delete=models.PROTECT,
        related_name="stripe_refund",
    )
    payment = models.OneToOneField(
        Payment,
        on_delete=models.PROTECT,
        related_name="stripe_refund",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_stripe_order_refunds",
    )
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    devise = models.CharField(max_length=10)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PROCESSING",
    )
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        editable=False,
    )
    stripe_refund_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        editable=False,
    )
    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(montant__gt=0),
                name="stripe_order_refund_positive_amount",
            ),
        ]

    def __str__(self):
        return f"Remboursement commande #{self.commande_id} - {self.status}"


class DonationPaymentAttempt(models.Model):
    STATUS_CHOICES = [
        ("PROCESSING", _("En cours")),
        ("SUCCESS", _("Réussi")),
        ("FAILED", _("Échoué")),
        ("CANCELED", _("Annulé")),
    ]

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="donation_payment_attempts",
    )
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    devise = models.CharField(max_length=3, choices=[("EUR", "EUR")], default="EUR")
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PROCESSING",
    )
    stripe_session_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )
    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    checkout_url = models.URLField(max_length=500, blank=True)
    don = models.OneToOneField(
        "monetization.Don",
        on_delete=models.PROTECT,
        related_name="payment_attempt",
        null=True,
        blank=True,
    )
    raw_response = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(devise="EUR"),
                name="donation_attempt_eur_only",
            ),
            models.CheckConstraint(
                condition=Q(montant__gte=1),
                name="donation_attempt_min_1_eur",
            ),
        ]

    def __str__(self):
        return f"Don Stripe {self.pk} - {self.montant} {self.devise} - {self.status}"


class StripeSubscription(models.Model):
    OPEN_STATUSES = ("PROCESSING", "CHECKOUT_COMPLETE", "ACTIVE", "PAST_DUE")
    STATUS_CHOICES = [
        ("PROCESSING", _("En cours")),
        ("CHECKOUT_COMPLETE", _("Checkout terminé")),
        ("ACTIVE", _("Actif")),
        ("PAST_DUE", _("Paiement en retard")),
        ("CANCELED", _("Annulé")),
        ("FAILED", _("Échoué")),
    ]

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stripe_subscriptions",
    )
    abonnement = models.ForeignKey(
        "monetization.Abonnement",
        on_delete=models.PROTECT,
        related_name="stripe_subscriptions",
    )
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    devise = models.CharField(max_length=3, choices=[("EUR", "EUR")], default="EUR")
    stripe_price_id = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="PROCESSING",
    )
    stripe_checkout_session_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )
    stripe_customer_id = models.CharField(max_length=255, null=True, blank=True)
    stripe_subscription_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
    )
    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    checkout_url = models.URLField(max_length=500, blank=True)
    abonnement_utilisateur = models.OneToOneField(
        "monetization.AbonnementUtilisateur",
        on_delete=models.PROTECT,
        related_name="stripe_subscription",
        null=True,
        blank=True,
    )
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    raw_response = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(montant__gt=0),
                name="stripe_subscription_positive_amount",
            ),
            models.CheckConstraint(
                condition=Q(devise="EUR"),
                name="stripe_subscription_eur_only",
            ),
            models.UniqueConstraint(
                fields=["utilisateur"],
                condition=Q(
                    status__in=(
                        "PROCESSING",
                        "CHECKOUT_COMPLETE",
                        "ACTIVE",
                        "PAST_DUE",
                    )
                ),
                name="one_open_stripe_subscription_per_user",
            ),
        ]

    def __str__(self):
        return f"Abonnement Stripe {self.pk} - {self.status}"


class StripeSubscriptionInvoice(models.Model):
    subscription = models.ForeignKey(
        StripeSubscription,
        on_delete=models.PROTECT,
        related_name="invoices",
    )
    stripe_invoice_id = models.CharField(max_length=255, unique=True)
    montant_paye = models.DecimalField(max_digits=10, decimal_places=2)
    devise = models.CharField(max_length=3, choices=[("EUR", "EUR")], default="EUR")
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    revenu = models.OneToOneField(
        "monetization.Revenu",
        on_delete=models.PROTECT,
        related_name="stripe_subscription_invoice",
        null=True,
        blank=True,
    )
    raw_response = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(montant_paye__gt=0),
                name="stripe_subscription_invoice_positive_amount",
            ),
            models.CheckConstraint(
                condition=Q(devise="EUR"),
                name="stripe_subscription_invoice_eur_only",
            ),
            models.CheckConstraint(
                condition=Q(period_end__gt=models.F("period_start")),
                name="stripe_subscription_invoice_valid_period",
            ),
        ]

    def __str__(self):
        return f"Facture Stripe {self.stripe_invoice_id}"


class StripeWebhookEvent(models.Model):
    stripe_event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=100)
    processed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type} - {self.stripe_event_id}"

from django.db import models
from django.contrib.auth.models import User


from django.db import models
from django.conf import settings


class Adresse(models.Model):
    TYPE_ADRESSE_CHOICES = [
        ("LIVRAISON", _("Adresse de livraison")),
        ("FACTURATION", _("Adresse de facturation")),
    ]

    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="adresses"
    )
    type_adresse = models.CharField(
        max_length=20,
        choices=TYPE_ADRESSE_CHOICES,
        default="LIVRAISON"
    )
    rue = models.CharField(max_length=255)
    ville = models.CharField(max_length=100)
    code_postal = models.CharField(max_length=20)
    pays = models.CharField(max_length=100)
    telephone = models.CharField(max_length=20, blank=True, null=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.get_type_adresse_display()}] {self.rue}, {self.ville}, {self.pays}"
