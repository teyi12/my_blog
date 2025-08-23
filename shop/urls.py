from django.urls import path
from . import views

app_name = "shop"

urlpatterns = [
    path("", views.ProduitListView.as_view(), name="liste"),
    path("produit/<slug:slug>/", views.ProduitDetailView.as_view(), name="detail"),
    path("panier/", views.panier_view, name="panier"),
    path("panier/ajouter/<slug:slug>/", views.ajouter_panier, name="ajouter_panier"),
     path("categorie/<slug:slug>/", views.produits_par_categorie, name="par_categorie"),
]
