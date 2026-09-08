from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from articles.models import Article
from shop.models import Categorie, Produit
from videos.models import Video

from .seo import SEO_LANGUAGES, available_translation_languages


class StaticViewSitemap(Sitemap):
    protocol = "https"
    i18n = True
    alternates = True
    x_default = True

    public_views = (
        "home",
        "about",
        "contact",
        "articles:articles",
        "shop:liste",
        "videos:list",
        "monetization:abonnements",
        "monetization:partenariat",
        "monetization:affiliation",
        "monetization:publicites",
    )

    def items(self):
        return self.public_views

    def location(self, item):
        return reverse(item)

    def get_languages_for_item(self, item):
        return SEO_LANGUAGES


class TranslatedModelSitemap(Sitemap):
    protocol = "https"
    i18n = True
    alternates = True
    x_default = True
    required_translation_fields = ()

    def get_languages_for_item(self, item):
        return available_translation_languages(
            item,
            self.required_translation_fields,
        )


class ArticleSitemap(TranslatedModelSitemap):
    required_translation_fields = ("titre", "contenu")

    def items(self):
        return Article.objects.filter(is_premium=False).order_by("pk")

    def location(self, item):
        return reverse("articles:article_detail", kwargs={"slug": item.slug})


class ProductSitemap(TranslatedModelSitemap):
    required_translation_fields = ("nom", "description")

    def items(self):
        return Produit.objects.order_by("pk")

    def location(self, item):
        return reverse("shop:detail", kwargs={"slug": item.slug})


class ProductCategorySitemap(TranslatedModelSitemap):
    required_translation_fields = ("nom",)

    def items(self):
        return Categorie.objects.order_by("pk")

    def location(self, item):
        return reverse("shop:par_categorie", kwargs={"slug": item.slug})


class VideoSitemap(TranslatedModelSitemap):
    required_translation_fields = ("titre", "description")

    def items(self):
        return Video.objects.filter(est_publie=True, is_premium=False).order_by("pk")

    def location(self, item):
        return reverse("videos:detail", kwargs={"slug": item.slug})


sitemaps = {
    "static": StaticViewSitemap,
    "articles": ArticleSitemap,
    "products": ProductSitemap,
    "product-categories": ProductCategorySitemap,
    "videos": VideoSitemap,
}
