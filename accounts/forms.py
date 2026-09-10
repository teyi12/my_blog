import warnings

from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from PIL import Image

from .models import CustomUser


class ProfilePhotoField(forms.ImageField):
    """Validate profile photos from their bytes before they reach storage."""

    allowed_image_formats = {"JPEG", "PNG", "WEBP"}
    default_error_messages = {
        **forms.ImageField.default_error_messages,
        "invalid_image": _(
            "Le fichier sélectionné n’est pas une image valide."
        ),
        "file_too_large": _(
            "La photo dépasse la taille maximale autorisée de %(max_size_mb)s Mo."
        ),
        "unsupported_format": _(
            "Format non pris en charge. Utilisez une image JPEG, PNG ou WebP."
        ),
    }

    def __init__(self, *args, **kwargs):
        max_size = settings.PROFILE_PHOTO_MAX_UPLOAD_SIZE
        max_size_mb = f"{max_size / (1024 * 1024):g}"
        self.max_size = max_size
        kwargs.setdefault("required", False)
        kwargs.setdefault("label", _("Photo de profil"))
        kwargs.setdefault(
            "help_text",
            _(
                "Formats acceptés : JPEG, PNG et WebP. "
                "Taille maximale : %(max_size_mb)s Mo."
            )
            % {"max_size_mb": max_size_mb},
        )
        super().__init__(*args, **kwargs)
        self.widget.attrs["accept"] = "image/jpeg,image/png,image/webp"

    def to_python(self, data):
        if data:
            if getattr(data, "size", 0) > self.max_size:
                raise ValidationError(
                    self.error_messages["file_too_large"],
                    code="file_too_large",
                    params={
                        "max_size_mb": f"{self.max_size / (1024 * 1024):g}"
                    },
                )

        # Django's ImageField delegates to Pillow's Image.open() and verify().
        # Treat decompression-bomb warnings as invalid images as well.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            uploaded_file = super().to_python(data)

        if uploaded_file is None:
            return None

        detected_format = getattr(uploaded_file.image, "format", "")
        if detected_format.upper() not in self.allowed_image_formats:
            raise ValidationError(
                self.error_messages["unsupported_format"],
                code="unsupported_format",
            )

        uploaded_file.seek(0)
        return uploaded_file


class CustomUserCreationForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, required=False, label="Prénom")
    last_name = forms.CharField(max_length=150, required=False, label="Nom")
    photo = ProfilePhotoField()
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
    photo = ProfilePhotoField()

    class Meta:
        model = CustomUser
        fields = ["first_name", "last_name", "photo", "telephone", "bio"]


class ProfileForm(forms.ModelForm):
    photo = ProfilePhotoField()

    class Meta:
        model = CustomUser
        fields = ("first_name", "last_name", "photo", "bio")
