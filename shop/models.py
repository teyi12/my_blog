from decimal import Decimal
from pathlib import PurePosixPath
import uuid

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import get_valid_filename, slugify
from django.utils.translation import gettext_lazy as _


ORDER_CURRENCY_CHOICES = [
    ("EUR", _("Euro")),
    ("USD", _("Dollar")),
    ("XOF", _("Franc CFA")),
]
DEFAULT_ORDER_CURRENCY = "EUR"

FULFILLMENT_STATUS_CHOICES = [
    ("WAITING_PAYMENT", _("En attente de paiement")),
    ("TO_PREPARE", _("À préparer")),
    ("PREPARING", _("En préparation")),
    ("SHIPPED", _("Expédiée")),
    ("DELIVERED", _("Livrée")),
    ("CANCELED", _("Traitement annulé")),
]

ORDER_LANGUAGE_CHOICES = [
    ("fr", _("Français")),
    ("de", _("Allemand")),
    ("en", _("Anglais")),
]

FULFILLMENT_TRANSITIONS = {
    "WAITING_PAYMENT": {"TO_PREPARE"},
    "TO_PREPARE": {"PREPARING", "CANCELED"},
    "PREPARING": {"SHIPPED", "CANCELED"},
    "SHIPPED": {"DELIVERED"},
    "DELIVERED": set(),
    "CANCELED": set(),
}

INVENTORY_STATUS_CHOICES = [
    ("NONE", _("Sans réservation")),
    ("RESERVED", _("Stock réservé")),
    ("COMMITTED", _("Stock consommé")),
    ("RELEASED", _("Stock libéré")),
]


def safe_order_download_filename(storage_name):
    """Return a path-free attachment name derived from a storage key."""
    normalized_name = str(storage_name or "").replace("\\", "/")
    if not normalized_name:
        return ""

    basename = PurePosixPath(normalized_name).name
    if not basename:
        return "fichier-commande"
    try:
        return get_valid_filename(basename)
    except SuspiciousFileOperation:
        return "fichier-commande"


def product_file_storage():
    """Return the configured product-file storage without requiring a product."""
    return Produit._meta.get_field("fichier").storage


def order_product_snapshot_name(product, language_code):
    """Choose a deterministic product name for an order language."""
    language_fields = {
        "fr": "nom_fr",
        "de": "nom_de",
        "en": "nom_en",
    }
    requested_language = (
        language_code if language_code in language_fields else "fr"
    )
    fallback_languages = (requested_language, "fr", "de", "en")
    for candidate_language in dict.fromkeys(fallback_languages):
        value = getattr(product, language_fields[candidate_language], "") or ""
        if value.strip():
            return value
    return "Produit indisponible"


class Categorie(models.Model):
    nom = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nom)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom


class Produit(models.Model):
    nom = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, blank=True)
    description = models.TextField(blank=True)
    prix = models.DecimalField(max_digits=10, decimal_places=2)
    image = models.ImageField(upload_to="produits/", blank=True, null=True)
    fichier = models.FileField(upload_to="produits/fichiers/", blank=True, null=True)
    stock = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Stock disponible"),
        help_text=_(
            "Laissez vide pour ne pas gérer le stock. Les produits numériques "
            "ne consomment pas de stock."
        ),
    )

    categorie = models.ForeignKey(
        Categorie, on_delete=models.SET_NULL, null=True, blank=True
    )
    en_vedette = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nom)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom

    @property
    def est_numerique(self):
        return bool(self.fichier)

    @property
    def stock_est_gere(self):
        return self.stock is not None and not self.est_numerique

    @property
    def est_disponible(self):
        return not self.stock_est_gere or self.stock > 0

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock__isnull=True) | models.Q(stock__gte=0),
                name="product_stock_nonnegative",
            ),
        ]


class Commande(models.Model):
    client = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="commandes",
    )
    adresse = models.ForeignKey(
        "payments.Adresse",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commandes"
    )
    source_cart = models.ForeignKey(
        "Cart",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="commandes",
    )
    checkout_token = models.UUIDField(unique=True, null=True, blank=True, editable=False)
    cart_finalized_at = models.DateTimeField(null=True, blank=True, editable=False)
    date_commande = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", _("En attente")),
            ("PROCESSING", _("Paiement en cours")),
            ("SUCCESS", _("Payée")),
            ("REFUNDED", _("Remboursée")),
            ("FAILED", _("Échouée")),
            ("CANCELED", _("Annulée")),
        ],
        default="PENDING",
    )
    payment_channel = models.CharField(
        max_length=20,
        choices=[
            ("CARD", _("Carte bancaire")),
            ("MOBILE_MONEY", _("Mobile Money")),
            ("STRIPE", _("Stripe")),
            ("CINETPAY", _("CinetPay")),
        ],
        blank=True,
        null=True,
    )
    currency = models.CharField(
        max_length=10,
        choices=ORDER_CURRENCY_CHOICES,
        default=DEFAULT_ORDER_CURRENCY,
    )
    language_code = models.CharField(
        max_length=10,
        choices=ORDER_LANGUAGE_CHOICES,
        default="fr",
    )
    fulfillment_status = models.CharField(
        max_length=20,
        choices=FULFILLMENT_STATUS_CHOICES,
        default="WAITING_PAYMENT",
    )
    carrier = models.CharField(max_length=100, blank=True)
    tracking_number = models.CharField(max_length=150, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True, editable=False)
    delivered_at = models.DateTimeField(null=True, blank=True, editable=False)
    inventory_status = models.CharField(
        max_length=20,
        choices=INVENTORY_STATUS_CHOICES,
        default="NONE",
        editable=False,
    )
    stock_reservation_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    def __str__(self):
        return f"Commande #{self.id} - {self.client}"

    def recalculate_total(self):
        total = sum(lc.quantite * lc.prix_unitaire for lc in self.lignes.all())
        self.total = total
        self.save(update_fields=["total"])
        return self.total

    def allowed_fulfillment_transitions(self):
        return FULFILLMENT_TRANSITIONS.get(self.fulfillment_status, set())


class LigneCommande(models.Model):
    commande = models.ForeignKey(
        Commande, related_name="lignes", on_delete=models.CASCADE
    )
    produit = models.ForeignKey(
        Produit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    source_cart_item = models.ForeignKey(
        "CartItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lignes_commande",
    )
    quantite = models.PositiveIntegerField(default=1)
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    nom_produit_snapshot = models.CharField(
        max_length=255,
        blank=True,
        editable=False,
    )
    fichier_nom_stockage_snapshot = models.CharField(
        max_length=500,
        blank=True,
        editable=False,
    )
    fichier_nom_telechargement_snapshot = models.CharField(
        max_length=255,
        blank=True,
        editable=False,
    )
    stock_reserved_quantity = models.PositiveIntegerField(
        default=0,
        editable=False,
    )

    SNAPSHOT_FIELDS = (
        "nom_produit_snapshot",
        "fichier_nom_stockage_snapshot",
        "fichier_nom_telechargement_snapshot",
    )

    def _restore_existing_snapshots(self):
        if self._state.adding or not self.pk:
            return

        stored_snapshots = (
            type(self).objects.filter(pk=self.pk).values(*self.SNAPSHOT_FIELDS).first()
        )
        if not stored_snapshots:
            return
        for field_name, stored_value in stored_snapshots.items():
            setattr(self, field_name, stored_value)

    def _populate_initial_snapshots(self):
        if not self._state.adding:
            return set()
        if not self.produit_id:
            return set()
        try:
            produit = self.produit
        except Produit.DoesNotExist:
            return set()

        changed_fields = set()
        if not self.nom_produit_snapshot:
            self.nom_produit_snapshot = order_product_snapshot_name(
                produit,
                self.commande.language_code,
            )
            changed_fields.add("nom_produit_snapshot")

        current_storage_name = produit.fichier.name if produit.fichier else ""
        if not self.fichier_nom_stockage_snapshot and current_storage_name:
            self.fichier_nom_stockage_snapshot = current_storage_name
            changed_fields.add("fichier_nom_stockage_snapshot")
        if (
            not self.fichier_nom_telechargement_snapshot
            and self.fichier_nom_stockage_snapshot
        ):
            self.fichier_nom_telechargement_snapshot = safe_order_download_filename(
                self.fichier_nom_stockage_snapshot
            )
            changed_fields.add("fichier_nom_telechargement_snapshot")
        return changed_fields

    def save(self, *args, **kwargs):
        self._restore_existing_snapshots()
        changed_snapshot_fields = self._populate_initial_snapshots()
        if not self.prix_unitaire and self.produit:
            self.prix_unitaire = self.produit.prix
        if kwargs.get("update_fields") is not None and changed_snapshot_fields:
            kwargs["update_fields"] = (
                set(kwargs["update_fields"]) | changed_snapshot_fields
            )
        super().save(*args, **kwargs)

    @property
    def nom_produit_affiche(self):
        if self.nom_produit_snapshot:
            return self.nom_produit_snapshot
        if self.produit_id:
            try:
                return self.produit.nom
            except Produit.DoesNotExist:
                pass
        return _("Produit indisponible")

    @property
    def a_fichier_numerique(self):
        return bool(self.fichier_nom_stockage_snapshot)

    def sous_total(self):
        return Decimal(self.quantite) * self.prix_unitaire

    def __str__(self):
        return f"{self.quantite} x {self.nom_produit_affiche}"


class OrderReceipt(models.Model):
    """Immutable payment-receipt snapshot.

    The save-level guard does not cover QuerySet.update() or bulk_update(),
    which bypass model save methods in Django.
    """

    commande = models.OneToOneField(
        Commande,
        on_delete=models.CASCADE,
        related_name="receipt",
    )
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    issued_at = models.DateTimeField(editable=False)
    language_code = models.CharField(max_length=10, editable=False)
    currency = models.CharField(max_length=10, editable=False)
    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        editable=False,
    )
    payment_channel = models.CharField(max_length=20, blank=True, editable=False)
    issuer_name = models.CharField(max_length=255, editable=False)
    issuer_contact = models.CharField(max_length=255, blank=True, editable=False)
    customer_name = models.CharField(max_length=301, blank=True, editable=False)
    customer_email = models.EmailField(editable=False)
    address_snapshot = models.JSONField(default=dict, editable=False)
    items_snapshot = models.JSONField(default=list, editable=False)

    IMMUTABLE_FIELDS = (
        "commande_id",
        "public_id",
        "issued_at",
        "language_code",
        "currency",
        "total",
        "payment_channel",
        "issuer_name",
        "issuer_contact",
        "customer_name",
        "customer_email",
        "address_snapshot",
        "items_snapshot",
    )

    def save(self, *args, **kwargs):
        if not self._state.adding and self.pk:
            stored_values = (
                type(self)
                .objects.filter(pk=self.pk)
                .values(*self.IMMUTABLE_FIELDS)
                .first()
            )
            if stored_values:
                for field_name, stored_value in stored_values.items():
                    setattr(self, field_name, stored_value)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Reçu commande #{self.commande_id}"


class Cart(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="carts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    actif = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(actif=True, user__isnull=False),
                name="one_active_cart_per_user",
            )
        ]

    def __str__(self):
        return f"Panier #{self.id} ({self.user})"

    def total(self):
        return sum(item.sous_total() for item in self.items.all())

    def total_articles(self):
        return sum(item.quantite for item in self.items.all())

    def recalculate(self):
        for item in self.items.all():
            if not item.prix_unitaire:
                item.prix_unitaire = item.produit.prix
                item.save()
        return self.total()


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    quantite = models.PositiveIntegerField(default=1)
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "produit"],
                name="unique_product_per_cart",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.prix_unitaire:
            self.prix_unitaire = self.produit.prix
        super().save(*args, **kwargs)

    def sous_total(self):
        return Decimal(self.quantite) * self.prix_unitaire

    def __str__(self):
        return f"{self.quantite} x {self.produit.nom} (Panier {self.cart.id})"
