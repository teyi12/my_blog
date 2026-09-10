import logging

from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from .forms import CustomUserCreationForm, CustomUserUpdateForm


logger = logging.getLogger(__name__)

PHOTO_STORAGE_ERROR = _(
    "La photo n’a pas pu être enregistrée pour le moment. "
    "Veuillez réessayer ultérieurement."
)


def _save_form_with_uploaded_photo(form, *, operation, old_photo_name="", user_id=None):
    """Save a valid form and turn photo-storage failures into field errors."""
    try:
        with transaction.atomic():
            return form.save()
    except Exception as error:
        # A text-only save or an intentional clear doesn't call photo storage;
        # preserve its existing failure semantics instead of hiding unrelated
        # database/programming errors.
        if not form.files.get("photo"):
            raise

        logger.error(
            "Profile photo storage failure operation=%s exception_type=%s user_id=%s",
            operation,
            type(error).__name__,
            user_id if user_id is not None else "unavailable",
        )
        form.instance.photo = old_photo_name
        form.add_error("photo", PHOTO_STORAGE_ERROR)
        return None


def register_view(request):
    if request.method == "POST":
        form = CustomUserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            user = _save_form_with_uploaded_photo(form, operation="registration")
            if user is not None:
                login(request, user)  # Connexion automatique après inscription
                return redirect("home")  # redirige vers la vue nommée 'home'
    else:
        form = CustomUserCreationForm()
    return render(request, "accounts/register.html", {"form": form})


@login_required
def profile_view(request):
    if request.method == "POST":
        old_photo_name = request.user.photo.name
        form = CustomUserUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            user = _save_form_with_uploaded_photo(
                form,
                operation="profile_update",
                old_photo_name=old_photo_name,
                user_id=request.user.pk,
            )
            if user is not None:
                return redirect("accounts:profile")
    else:
        form = CustomUserUpdateForm(instance=request.user)
    return render(request, "accounts/profile.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Bienvenue {user.first_name or user.username} !")
            return redirect("home")
        else:
            messages.error(request, "Email ou mot de passe incorrect.")
    else:
        form = AuthenticationForm()

    return render(request, "accounts/login.html", {"form": form})
