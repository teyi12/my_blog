from django.contrib.auth import get_user_model
from django.db import models, transaction
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _


class CategorieArticle(models.Model):
    nom = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("Catégorie d’article")
        verbose_name_plural = _("Catégories d’articles")

    def save(self, *args, **kwargs):
        if self._state.adding and not self.slug:
            self.slug = slugify(self.nom_fr)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom


class Article(models.Model):
    titre = models.CharField(max_length=150)
    contenu = models.TextField()
    slug = models.SlugField(max_length=100, unique=True)
    date_publication = models.DateTimeField(auto_now_add=True)
    image = models.ImageField(upload_to="articles/", default="default.jpg")
    image_alt = models.CharField(
        _("Texte alternatif de l’image"),
        max_length=255,
        blank=True,
        default="",
    )
    auteur = models.ForeignKey(
        get_user_model(),
        on_delete=models.CASCADE,
        related_name="articles",
        null=True,
        blank=True,
    )
    sponsor = models.CharField(max_length=255, blank=True, null=True)
    est_sponsorise = models.BooleanField(default=False)
    is_premium = models.BooleanField(default=False)
    categorie = models.ForeignKey(
        CategorieArticle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="articles",
        verbose_name=_("Catégorie"),
    )
    en_vedette = models.BooleanField(_("À la une"), default=False)
    ordre_affichage = models.PositiveIntegerField(
        _("Ordre d’affichage"),
        null=True,
        blank=True,
    )

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self._state.adding and not self.slug:
            self.slug = slugify(self.titre_fr)
        super().save(*args, **kwargs)
        if self.en_vedette:
            type(self).objects.filter(en_vedette=True).exclude(pk=self.pk).update(
                en_vedette=False
            )

    @property
    def resolved_image_alt(self):
        return self.image_alt or self.titre

    def __str__(self):
        return self.titre


class ArticleMedia(models.Model):
    MEDIA_CHOICES = [
        ("image", "Image"),
        ("video", "Vidéo"),
    ]
    article = models.ForeignKey("Article", on_delete=models.CASCADE, related_name="medias")
    type = models.CharField(max_length=10, choices=MEDIA_CHOICES)
    fichier = models.FileField(upload_to="medias/")
    date_ajout = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.type} - {self.article.titre}"
