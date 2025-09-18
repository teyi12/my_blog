from django.db import models 
from django.contrib.auth import get_user_model
from django.utils.text import slugify


class Article(models.Model):
    titre = models.CharField(max_length=150)
    contenu = models.TextField()
    slug = models.SlugField(max_length=100, unique=True)
    date_publication = models.DateTimeField(auto_now_add=True)
    image = models.ImageField(upload_to="articles/", default="default.jpg")
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

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.titre)
        super().save(*args, **kwargs)

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
