from django.db import models
from django.conf import settings
from django.core.validators import RegexValidator
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class Partenaire(models.Model):
    """Annonceurs ou sponsors"""
    nom = models.CharField(max_length=150)
    site_web = models.URLField(blank=True, null=True)
    logo = models.ImageField(upload_to="sponsors/", blank=True, null=True)

    def __str__(self):
        return self.nom


class Publicite(models.Model):
    """Encarts publicitaires liés à un article ou globalement au blog"""
    titre = models.CharField(max_length=150)
    partenaire = models.ForeignKey(Partenaire, on_delete=models.CASCADE)
    image = models.ImageField(upload_to="publicites/")
    lien = models.URLField()
    date_debut = models.DateField()
    date_fin = models.DateField()
    actif = models.BooleanField(default=True)

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
