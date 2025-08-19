from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView


from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", views.home_view, name="home"),

    path("contact/", views.contact_view, name="contact"),
    path("remerciement/", views.remerciement_view, name="remerciement"),
    path("articles/", include("articles.urls"), name="articles"),
    path("accounts/", include("accounts.urls")),
    path("shop/", include("shop.urls")),
    path("social/", include("social.urls")),
    path("payments/", include("payments.urls", namespace="payments")),
]


if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)



