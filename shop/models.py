from django.db import models
from django.conf import settings
from django.utils.text import slugify
from decimal import Decimal


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
    date_commande = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "En attente"),
            ("SUCCESS", "Payée"),
            ("FAILED", "Échouée"),
        ],
        default="PENDING",
    )
    payment_channel = models.CharField(
        max_length=20,
        choices=[
            ("CARD", "Carte bancaire"),
            ("MOBILE_MONEY", "Mobile Money"),
            ("STRIPE", "Stripe"),
        ],
        blank=True,
        null=True,
    )
    currency = models.CharField(
        max_length=10,
        choices=[
            ("EUR", "Euro"),
            ("USD", "Dollar"),
            ("XOF", "Franc CFA"),
        ],
        default="EUR"
    )

    def __str__(self):
        return f"Commande #{self.id} - {self.client}"

    def recalculate_total(self):
        total = sum(lc.quantite * lc.prix_unitaire for lc in self.lignes.all())
        self.total = total
        self.save(update_fields=["total"])
        return self.total


class LigneCommande(models.Model):
    commande = models.ForeignKey(
        Commande, related_name="lignes", on_delete=models.CASCADE
    )
    produit = models.ForeignKey(Produit, on_delete=models.CASCADE)
    quantite = models.PositiveIntegerField(default=1)
    prix_unitaire = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        if not self.prix_unitaire and self.produit:
            self.prix_unitaire = self.produit.prix
        super().save(*args, **kwargs)

    def sous_total(self):
        return Decimal(self.quantite) * self.prix_unitaire

    def __str__(self):
        return f"{self.quantite} x {self.produit.nom}"


class Cart(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="carts"
    )
    created_at = models.DateTimeField(auto_now_add=True)

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

    def save(self, *args, **kwargs):
        if not self.prix_unitaire:
            self.prix_unitaire = self.produit.prix
        super().save(*args, **kwargs)

    def sous_total(self):
        return Decimal(self.quantite) * self.prix_unitaire

    def __str__(self):
        return f"{self.quantite} x {self.produit.nom} (Panier {self.cart.id})"
