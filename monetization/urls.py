from django.urls import path
from . import views

app_name = "monetization"

urlpatterns = [
    path("dashboard/", views.dashboard_view, name="dashboard"),
    path("partenariat/", views.partenariat_view, name="partenariat"),
    path("affiliation/", views.affiliation_view, name="affiliation"),
    path("abonnements/", views.abonnements_view, name="abonnements"),
    path("abonnements/<slug:slug>/souscrire/", views.souscrire_abonnement, name="souscrire_abonnement"),
    path("don/", views.don_view, name="don"),
    path('paiement/', views.paiement_view, name='choice')  # payments:choice
]