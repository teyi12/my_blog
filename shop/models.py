from decimal import Decimal
from pathlib import PurePosixPath
import uuid

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import translation
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
    "WAITING_PAYMENT": set(),
    "TO_PREPARE": {"PREPARING"},
    "PREPARING": {"SHIPPED"},
    "SHIPPED": {"DELIVERED"},
    "DELIVERED": set(),
    "CANCELED": set(),
}

INVENTORY_STATUS_CHOICES = [
    ("NONE", _("Sans réservation")),
    ("RESERVED", _("Stock réservé")),
    ("COMMITTED", _("Stock consommé")),
    ("RELEASED", _("Stock libéré")),
    ("RESTOCKED", _("Stock remis en inventaire")),
]

STOCK_MOVEMENT_TYPE_CHOICES = [
    ("INITIAL", _("Stock initial")),
    ("MANUAL", _("Ajustement manuel")),
    ("RESERVATION", _("Réservation")),
    ("RELEASE", _("Libération")),
    ("SALE", _("Vente confirmée")),
    ("RESTOCK", _("Remise en stock")),
]

ORDER_CANCELLATION_SOURCE_CHOICES = [
    ("CUSTOMER", _("Client")),
    ("STAFF", _("Équipe")),
]

STRIPE_EXPIRATION_STATUS_CHOICES = [
    ("NOT_REQUIRED", _("Non requise")),
    ("PENDING", _("À effectuer")),
    ("PROCESSING", _("En cours")),
    ("SUCCEEDED", _("Session expirée")),
    ("FAILED", _("Échec contrôlé")),
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


class ProduitQuerySet(models.QuerySet):
    def with_secondary_images(self):
        """Prefetch the ordered gallery for code that explicitly needs it."""
        return self.prefetch_related(
            models.Prefetch(
                "images_secondaires",
                queryset=ProduitImage.objects.order_by("ordre", "pk"),
                to_attr="_prefetched_secondary_images",
            )
        )


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
    low_stock_threshold = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        verbose_name=_("Seuil de stock faible"),
        help_text=_("Laissez vide pour désactiver l’alerte de stock faible."),
    )

    categorie = models.ForeignKey(
        Categorie, on_delete=models.SET_NULL, null=True, blank=True
    )
    en_vedette = models.BooleanField(default=False)

    objects = ProduitQuerySet.as_manager()

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nom)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom

    def _localized_content(self, field_name, language_code=None):
        """Return an explicit product translation with French as fallback."""
        active_language = language_code or translation.get_language() or "fr"
        normalized_language = active_language.lower().split("-", 1)[0]
        if normalized_language not in {"fr", "de", "en"}:
            normalized_language = "fr"

        translated_value = getattr(
            self,
            f"{field_name}_{normalized_language}",
            None,
        )
        if str(translated_value or "").strip():
            return translated_value

        french_value = getattr(self, f"{field_name}_fr", None)
        if str(french_value or "").strip():
            return french_value

        # Compatibility for rows created before the explicit translation columns
        # were populated. Reading __dict__ avoids falling through to an unrelated
        # active-language descriptor when an explicit language was requested.
        return self.__dict__.get(field_name, "") or ""

    def localized_name_for(self, language_code=None):
        return self._localized_content("nom", language_code)

    def localized_description_for(self, language_code=None):
        return self._localized_content("description", language_code)

    @property
    def localized_name(self):
        return self.localized_name_for()

    @property
    def localized_description(self):
        return self.localized_description_for()

    def get_public_secondary_images(self):
        """Return gallery rows in stable order, using an explicit prefetch if present."""
        prefetched = getattr(self, "_prefetched_secondary_images", None)
        if prefetched is not None:
            return prefetched
        return self.images_secondaires.order_by("ordre", "pk")

    def get_display_image(self):
        """Resolve the historical main image, then the first gallery image."""
        if self.image:
            return self.image
        secondary_images = self.get_public_secondary_images()
        if isinstance(secondary_images, list):
            first_secondary = secondary_images[0] if secondary_images else None
        else:
            first_secondary = secondary_images.first()
        return first_secondary.image if first_secondary else None

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
            models.CheckConstraint(
                condition=(
                    models.Q(low_stock_threshold__isnull=True)
                    | models.Q(low_stock_threshold__gte=0)
                ),
                name="product_low_stock_threshold_nonnegative",
            ),
        ]


class ProduitImage(models.Model):
    """Ordered secondary product image.

    Deleting this row, or deleting its product through CASCADE, removes only the
    database record. The storage object is deliberately retained because a
    Cloudinary asset may be shared or managed outside Django.
    """

    produit = models.ForeignKey(
        Produit,
        on_delete=models.CASCADE,
        related_name="images_secondaires",
        db_index=False,
    )
    image = models.ImageField(upload_to="produits/galerie/")
    ordre = models.PositiveIntegerField(
        _("Ordre d’affichage"),
        default=0,
    )
    texte_alternatif = models.CharField(
        _("Texte alternatif de l’image"),
        max_length=255,
        blank=True,
        default="",
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("ordre", "pk")
        indexes = [
            models.Index(
                fields=("produit", "ordre"),
                name="shop_prodimg_order_idx",
            )
        ]

    def localized_alt_text_for(self, language_code=None):
        active_language = language_code or translation.get_language() or "fr"
        normalized_language = active_language.lower().split("-", 1)[0]
        if normalized_language not in {"fr", "de", "en"}:
            normalized_language = "fr"

        translated_value = getattr(
            self,
            f"texte_alternatif_{normalized_language}",
            "",
        )
        if str(translated_value or "").strip():
            return str(translated_value).strip()

        french_value = getattr(self, "texte_alternatif_fr", "")
        if str(french_value or "").strip():
            return str(french_value).strip()

        return str(self.produit.localized_name_for(normalized_language) or "").strip()

    @property
    def localized_alt_text(self):
        return self.localized_alt_text_for()

    def __str__(self):
        return f"{self.produit} · {self.ordre}"


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
    inventory_cycle = models.PositiveIntegerField(default=0, editable=False)
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
        if self.fulfillment_status == "PREPARING" and self.is_digital_only:
            return {"DELIVERED"}
        return FULFILLMENT_TRANSITIONS.get(self.fulfillment_status, set())

    @property
    def is_digital_only(self):
        if not self.pk or not self.lignes.exists():
            return False
        return not self.lignes.filter(fichier_nom_stockage_snapshot="").exists()


class OrderCancellation(models.Model):
    commande = models.OneToOneField(
        Commande,
        on_delete=models.PROTECT,
        related_name="cancellation",
        verbose_name=_("Commande"),
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_order_cancellations",
        verbose_name=_("Annulée par"),
    )
    source = models.CharField(
        max_length=20,
        choices=ORDER_CANCELLATION_SOURCE_CHOICES,
        verbose_name=_("Origine"),
    )
    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name=_("Clé d’idempotence"),
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    stripe_expiration_status = models.CharField(
        max_length=20,
        choices=STRIPE_EXPIRATION_STATUS_CHOICES,
        default="NOT_REQUIRED",
        editable=False,
        verbose_name=_("Expiration Stripe"),
    )
    stripe_expiration_attempted_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )
    notification_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )
    late_payment_detected_at = models.DateTimeField(
        null=True,
        blank=True,
        editable=False,
    )

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("Annulation de commande")
        verbose_name_plural = _("Annulations de commande")

    def __str__(self):
        return f"Annulation commande #{self.commande_id}"


class ImmutableFulfillmentEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(_("Le journal logistique est immuable."))

    def delete(self):
        raise ValidationError(_("Le journal logistique est immuable."))

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError(_("Le journal logistique est immuable."))


class OrderFulfillmentEvent(models.Model):
    commande = models.ForeignKey(
        Commande,
        on_delete=models.PROTECT,
        related_name="fulfillment_events",
        verbose_name=_("Commande"),
    )
    old_status = models.CharField(
        max_length=20,
        choices=FULFILLMENT_STATUS_CHOICES,
        editable=False,
        verbose_name=_("Ancien statut"),
    )
    new_status = models.CharField(
        max_length=20,
        choices=FULFILLMENT_STATUS_CHOICES,
        editable=False,
        verbose_name=_("Nouveau statut"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fulfillment_events",
        editable=False,
        verbose_name=_("Acteur staff"),
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    note = models.TextField(
        max_length=1000,
        blank=True,
        editable=False,
        verbose_name=_("Note opérationnelle"),
    )
    carrier = models.CharField(
        max_length=100,
        blank=True,
        editable=False,
        verbose_name=_("Transporteur"),
    )
    tracking_number = models.CharField(
        max_length=150,
        blank=True,
        editable=False,
        verbose_name=_("Numéro de suivi"),
    )
    tracking_url = models.URLField(
        max_length=500,
        blank=True,
        editable=False,
        verbose_name=_("URL de suivi"),
    )
    idempotency_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name=_("Clé d’idempotence"),
    )

    objects = ImmutableFulfillmentEventQuerySet.as_manager()

    class Meta:
        ordering = ("created_at", "pk")
        verbose_name = _("Événement logistique")
        verbose_name_plural = _("Événements logistiques")
        indexes = [
            models.Index(
                fields=("commande", "created_at"),
                name="shop_fulfi_command_1d5f54_idx",
            )
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk:
            raise ValidationError(_("Le journal logistique est immuable."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Le journal logistique est immuable."))

    def __str__(self):
        return (
            f"Commande #{self.commande_id} · "
            f"{self.old_status} → {self.new_status}"
        )


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


class ImmutableStockMovementQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(_("Le journal d’inventaire est immuable."))

    def delete(self):
        raise ValidationError(_("Le journal d’inventaire est immuable."))

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError(_("Le journal d’inventaire est immuable."))


class StockMovement(models.Model):
    produit = models.ForeignKey(
        Produit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name=_("Produit"),
    )
    product_id_snapshot = models.PositiveBigIntegerField(
        editable=False,
        verbose_name=_("Identifiant produit"),
    )
    product_name_snapshot = models.CharField(
        max_length=255,
        editable=False,
        verbose_name=_("Nom du produit"),
    )
    movement_type = models.CharField(
        max_length=20,
        choices=STOCK_MOVEMENT_TYPE_CHOICES,
        verbose_name=_("Type de mouvement"),
    )
    quantity = models.IntegerField(verbose_name=_("Variation"))
    stock_before = models.PositiveIntegerField(verbose_name=_("Stock avant"))
    stock_after = models.PositiveIntegerField(verbose_name=_("Stock après"))
    reason = models.TextField(verbose_name=_("Motif"))
    commande = models.ForeignKey(
        Commande,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name=_("Commande"),
    )
    ligne = models.ForeignKey(
        LigneCommande,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name=_("Ligne de commande"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
        verbose_name=_("Acteur staff"),
    )
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        editable=False,
        verbose_name=_("Clé d’idempotence"),
    )

    objects = ImmutableStockMovementQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")
        verbose_name = _("Mouvement de stock")
        verbose_name_plural = _("Mouvements de stock")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock_after=models.F("stock_before") + models.F("quantity")),
                name="stock_movement_balanced",
            ),
            models.CheckConstraint(
                condition=~models.Q(reason=""),
                name="stock_movement_reason_not_empty",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk:
            raise ValidationError(_("Le journal d’inventaire est immuable."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_("Le journal d’inventaire est immuable."))

    def __str__(self):
        return (
            f"{self.get_movement_type_display()} · "
            f"{self.product_name_snapshot} · {self.quantity:+d}"
        )


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
        return (
            f"{self.quantite} x {self.produit.localized_name} "
            f"(Panier {self.cart.id})"
        )
