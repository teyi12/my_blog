from django.urls import path
from . import views, customer_views

app_name = "shop"

urlpatterns = [
    # Produits
    path("", views.ProduitListView.as_view(), name="liste"),
    path("produit/<slug:slug>/", views.ProduitDetailView.as_view(), name="detail"),
    path("categorie/<slug:slug>/", views.produits_par_categorie, name="par_categorie"),

    # Espace client
    path("mes-commandes/", customer_views.mes_commandes, name="mes_commandes"),
    path("mes-commandes/<int:pk>/", customer_views.ma_commande_detail, name="ma_commande_detail"),

    # Gestion des catégories (staff)
    path("categories/", views.categorie_gestion_liste, name="categorie_gestion_liste"),
    path("categories/creer/", views.categorie_creer, name="categorie_creer"),
    path("categories/<slug:slug>/modifier/", views.categorie_modifier, name="categorie_modifier"),
    path("categories/<slug:slug>/supprimer/", views.categorie_supprimer, name="categorie_supprimer"),

    # Gestion des commandes (staff)
    path("commandes/", views.commande_gestion_liste, name="commande_gestion_liste"),
    path("commandes/<int:pk>/", views.commande_gestion_detail, name="commande_gestion_detail"),
    path(
        "commandes/<int:pk>/traitement/",
        views.commande_traitement_modifier,
        name="commande_traitement_modifier",
    ),

    # Panier
    path("panier/", views.panier_view, name="panier"),
    path("panier/update/", views.update_panier, name="update_panier"),
    path("panier/ajouter/<slug:slug>/", views.ajouter_panier, name="ajouter_panier"),

    # Checkout et confirmation
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("confirmation/<int:pk>/", views.ConfirmationView.as_view(), name="confirmation"),
    path("adresse-enregistree/", views.adresse_enregistree, name="adresse_enregistree"),
]
