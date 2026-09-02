from django.urls import path
from . import views

app_name = "shop"

urlpatterns = [
    # Produits
    path("", views.ProduitListView.as_view(), name="liste"),
    path("produit/<slug:slug>/", views.ProduitDetailView.as_view(), name="detail"),
    path("categorie/<slug:slug>/", views.produits_par_categorie, name="par_categorie"),

    # Panier
    path("panier/", views.panier_view, name="panier"),
    path("panier/update/", views.update_panier, name="update_panier"),   # ⚡ cohérence d’URL
    path("panier/ajouter/<slug:slug>/", views.ajouter_panier, name="ajouter_panier"),

    # Checkout et confirmation
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("confirmation/<int:pk>/", views.ConfirmationView.as_view(), name="confirmation"),
    path("adresse-enregistree/", views.adresse_enregistree, name="adresse_enregistree"),
]
