from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .forms import AccountAuthenticationForm

app_name = "accounts"
urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("profile/", views.profile_view, name="profile"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html",
            authentication_form=AccountAuthenticationForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="home"), name="logout"),  # ← logout ici
]
