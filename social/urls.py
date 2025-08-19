from django.urls import path
from . import views
urlpatterns = [
    path("follow/<int:user_id>/", views.follow, name="follow"),
    path("unfollow/<int:user_id>/", views.unfollow, name="unfollow"),
]
