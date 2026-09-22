from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import get_language
from django.utils.translation import gettext_lazy as _


http_url_validator = URLValidator(schemes=("http", "https"))


class Partenaire(models.Model):
    """Annonceurs ou sponsors"""
    nom = models.CharField(max_length=150)
    site_web = models.URLField(blank=True, null=True)
    logo = models.ImageField(upload_to="sponsors/", blank=True, null=True)

    def __str__(self):
        return self.nom


class PubliciteQuerySet(models.QuerySet):
    def diffusables(self, moment=None):
        """Return campaigns that can be shown publicly at ``moment``."""
        moment = moment or timezone.now()
        return (
            self.filter(actif=True)
            .filter(Q(date_debut__isnull=True) | Q(date_debut__lte=moment))
            .filter(Q(date_fin__isnull=True) | Q(date_fin__gte=moment))
            .order_by("ordre", "pk")
        )


class Publicite(models.Model):
    """Encarts publicitaires liés à un article ou globalement au blog"""
    titre = models.CharField(max_length=150)
    description = models.TextField(max_length=500, blank=True)
    texte_cta = models.CharField(max_length=80, blank=True)
    texte_alternatif = models.CharField(max_length=255, blank=True)
    partenaire = models.ForeignKey(Partenaire, on_delete=models.CASCADE)
    image = models.ImageField(upload_to="publicites/")
    lien = models.URLField(max_length=500, validators=[http_url_validator])
    date_debut = models.DateTimeField(blank=True, null=True)
    date_fin = models.DateTimeField(blank=True, null=True)
    actif = models.BooleanField(default=True)
    ordre = models.PositiveIntegerField(default=0, db_index=True)

    objects = PubliciteQuerySet.as_manager()

    class Meta:
        ordering = ("ordre", "pk")
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(date_debut__isnull=True)
                    | Q(date_fin__isnull=True)
                    | Q(date_debut__lte=models.F("date_fin"))
                ),
                name="publicite_period_is_chronological",
            )
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.date_debut and self.date_fin and self.date_debut > self.date_fin:
            errors["date_fin"] = _(
                "La date de fin doit être postérieure ou égale à la date de début."
            )

        if self.lien:
            value = self.lien.strip()
            parsed = urlsplit(value)
            if (
                value.startswith("//")
                or parsed.scheme.lower() not in {"http", "https"}
                or not parsed.netloc
            ):
                errors["lien"] = _(
                    "L’URL de destination doit utiliser HTTP ou HTTPS."
                )
            else:
                try:
                    http_url_validator(value)
                except ValidationError as exc:
                    errors["lien"] = exc.messages
                else:
                    self.lien = value

        if errors:
            raise ValidationError(errors)

    @property
    def image_alt(self):
        language = (get_language() or "fr").split("-", 1)[0]
        candidate_languages = tuple(dict.fromkeys((language, "fr")))
        for field_name in ("texte_alternatif", "titre"):
            for language_code in candidate_languages:
                value = getattr(self, f"{field_name}_{language_code}", "") or ""
                if value.strip():
                    return value.strip()
        return (self.partenaire.nom or "").strip()

    def __str__(self):
        return f"{self.titre} ({self.partenaire.nom})"


class Abonnement(models.Model):
    """Abonnement Premium pour accéder à du contenu exclusif"""
    nom = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    prix = models.DecimalField(max_digits=10, decimal_places=2)
    duree_jours = models.PositiveIntegerField(help_text=_("Durée en jours"))
    description = models.TextField()
    stripe_price_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        validators=[
            RegexValidator(
                regex=r"^price_[A-Za-z0-9_]+$",
                message=_("L’identifiant Stripe doit commencer par price_."),
            )
        ],
        help_text=_("Identifiant Stripe Price, laissé vide hors facturation."),
    )

    def save(self, *args, **kwargs):
        if self._state.adding and not self.slug:
            self.slug = slugify(self.nom_fr)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nom} - {self.prix}€"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["stripe_price_id"],
                condition=(
                    models.Q(stripe_price_id__isnull=False)
                    & ~models.Q(stripe_price_id="")
                ),
                name="unique_configured_subscription_stripe_price",
            )
        ]


class AbonnementUtilisateur(models.Model):
    """Lien entre utilisateur et son abonnement"""
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    abonnement = models.ForeignKey(Abonnement, on_delete=models.CASCADE)
    date_debut = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField()
    actif = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.utilisateur} -> {self.abonnement}"


class Don(models.Model):
    """Dons des utilisateurs"""
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Don de {self.utilisateur} ({self.montant} €)"


class LienAffiliation(models.Model):
    article = models.ForeignKey(
        "articles.Article",
        on_delete=models.CASCADE,
        related_name="liens_affiliation"
    )
    url = models.URLField()
    plateforme = models.CharField(max_length=100)
    revenu_genere = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return f"Lien {self.plateforme} pour {self.article}"


class Revenu(models.Model):
    """Centralisation des revenus"""
    TYPE_CHOICES = [
        ("PUB", _("Publicité")),
        ("SUB", _("Abonnement")),
        ("DON", _("Don")),
        ("AFF", _("Affiliation")),
    ]
    type = models.CharField(max_length=3, choices=TYPE_CHOICES)
    montant = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} - {self.montant}€"
    

class DemandePartenariat(models.Model):
    nom = models.CharField(max_length=150)
    email = models.EmailField()
    entreprise = models.CharField(max_length=200, blank=True, null=True)
    message = models.TextField()
    date = models.DateTimeField(auto_now_add=True)
    traite = models.BooleanField(default=False)

    def __str__(self):
        return f"Partenariat - {self.nom} ({'Traité' if self.traite else 'En attente'})"


class DemandeAffiliation(models.Model):
    nom = models.CharField(max_length=150)
    email = models.EmailField()
    plateforme = models.CharField(max_length=100)
    produit = models.CharField(max_length=200)
    message = models.TextField()
    date = models.DateTimeField(auto_now_add=True)
    traite = models.BooleanField(default=False)

    def __str__(self):
        return f"Affiliation - {self.nom} ({self.plateforme})"
