from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import CustomUser


class CustomUserCreationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=False, label="Prénom")
    last_name = forms.CharField(max_length=150, required=False, label="Nom")
    photo = forms.ImageField(required=False, label="Photo de profil")
    telephone = forms.CharField(max_length=20, required=False, label="Téléphone")
    bio = forms.CharField(widget=forms.Textarea, required=False, label="Bio")

    class Meta:
        model = CustomUser
        fields = [
            "email",
            "password1",
            "password2",
            "first_name",
            "last_name",
            "photo",
            "telephone",
            "bio",
        ]


class CustomUserUpdateForm(forms.ModelForm):
    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "photo", "telephone", "bio"]
