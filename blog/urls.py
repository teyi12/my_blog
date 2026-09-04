from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.views.generic import TemplateView
from django.contrib import admin
from django.urls import path, include
from monetization.admin import custom_admin_site


from . import views
from . import i18n_views

urlpatterns = [
    # Infrastructure et intégrations externes : ne jamais préfixer ces URLs.
    path("admin/", admin.site.urls),
    path("i18n/setlang/", i18n_views.set_language, name="set_language"),
    # Le namespace reste hors i18n pour préserver les retours et callbacks actuels.
    path("payments/", include("payments.urls", namespace="payments")),
]

urlpatterns += i18n_patterns(
    path("", views.home_view, name="home"),
    path("contact/", views.contact_view, name="contact"),
    path("about/", views.about, name="about"),
    path("remerciement/", views.remerciement_view, name="remerciement"),
    path("articles/", include("articles.urls"), name="articles"),
    path("accounts/", include("accounts.urls")),
    path("shop/", include("shop.urls")),
    path("social/", include("social.urls")),
    path("monetization/", include("monetization.urls")),
    prefix_default_language=False,
)


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

