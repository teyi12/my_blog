from django.conf import settings
from django.db import models, transaction
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from articles.models import CategorieArticle

from .youtube import extract_youtube_id, validate_youtube_url


class Video(models.Model):
    titre = models.CharField(_("Titre"), max_length=160)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    description = models.TextField(_("Description"))
    youtube_url = models.URLField(
        _("URL YouTube"),
        validators=[validate_youtube_url],
    )
    miniature = models.ImageField(
        _("Miniature"),
        upload_to="videos/thumbnails/",
        blank=True,
    )
    miniature_alt = models.CharField(
        _("Texte alternatif de la miniature"),
        max_length=255,
        blank=True,
        default="",
    )
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="videos",
        verbose_name=_("Auteur"),
    )
    categorie = models.ForeignKey(
        CategorieArticle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="videos",
        verbose_name=_("Catégorie"),
    )
    date_publication = models.DateTimeField(_("Date de publication"), auto_now_add=True)
    est_publie = models.BooleanField(_("Publiée"), default=False)
    is_premium = models.BooleanField(_("Contenu premium"), default=False)
    en_vedette = models.BooleanField(_("À la une"), default=False)
    ordre_affichage = models.PositiveIntegerField(
        _("Ordre d’affichage"),
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = _("Vidéo")
        verbose_name_plural = _("Vidéos")

    def save(self, *args, **kwargs):
        validate_youtube_url(self.youtube_url)
        if self._state.adding and not self.slug:
            self.slug = slugify(self.titre_fr)
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.en_vedette:
                type(self).objects.filter(en_vedette=True).exclude(pk=self.pk).update(
                    en_vedette=False
                )

    @property
    def youtube_id(self):
        return extract_youtube_id(self.youtube_url)

    @property
    def embed_url(self):
        return f"https://www.youtube-nocookie.com/embed/{self.youtube_id}"

    @property
    def resolved_miniature_alt(self):
        return self.miniature_alt or self.titre

    def __str__(self):
        return self.titre

# Create your models here.
