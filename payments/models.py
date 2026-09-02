from django.db import models
from django.conf import settings
from django.db.models import Q
from shop.models import Commande
import uuid


class Payment(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "En attente"),
        ("PROCESSING", "En cours"),
        ("SUCCESS", "Réussi"),
        ("FAILED", "Échoué"),
        ("CANCELED", "Annulé"),
    ]

    CHANNEL_CHOICES = [
        ("STRIPE", "Stripe"),
        ("MOBILE_MONEY", "Mobile Money"),
        ("CINETPAY", "CinetPay"),
        ("CARD", "Carte bancaire"),
        ("OTHER", "Autre"),
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

from django.db import models
from django.contrib.auth.models import User


from django.db import models
from django.conf import settings


class Adresse(models.Model):
    TYPE_ADRESSE_CHOICES = [
        ("LIVRAISON", "Adresse de livraison"),
        ("FACTURATION", "Adresse de facturation"),
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

