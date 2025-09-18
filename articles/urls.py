from django.urls import path
from . import views

app_name = "articles"

urlpatterns = [
    path("", views.articles_view, name="articles"),
    path("creer/", views.creer_view, name="article_creer"),
    path("<slug:slug>/", views.article_view, name="article_detail"),
    path('<slug:slug>/media-json/', views.article_media_json, name='article_media_json'),
    path("<slug:slug>/modifier/", views.modifier_view, name="article_modifier"),
    path("<slug:slug>/supprimer/", views.supprimer_view, name="article_supprimer"),
]
