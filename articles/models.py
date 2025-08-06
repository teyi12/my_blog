from django.db import models
from django.contrib.auth import get_user_model


class Article(models.Model):
    # Https://docs.djangoproject.com/fr/3.1/ref/models/fields/#field-types
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

    def __str__(self):
        return self.titre
