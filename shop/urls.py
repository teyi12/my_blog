from django.urls import path
from . import views

app_name = 'shop'

urlpatterns = [
    path('produits/', views.produits_liste, name='liste'),
    path('produit/<slug:slug>/', views.detail_produit, name='detail'),
    path('creer/', views.creer_produit, name='creer'),
    path('ajouter/<slug:slug>/', views.ajouter_au_panier, name='ajouter'),
    path('panier/', views.afficher_panier, name='panier'),
    path('commander/', views.passer_commande, name='commander'),
    path('categorie/<slug:slug>/', views.produits_par_categorie, name='produits_par_categorie'),
]

