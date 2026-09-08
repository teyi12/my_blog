import re
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be"}


def extract_youtube_id(value):
    """Return a safe YouTube video id from one of the supported HTTPS URLs."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValidationError(_("Saisissez une URL YouTube HTTPS valide."))
    if any(character in value for character in ("<", ">", '"', "'")):
        raise ValidationError(_("Le code HTML n’est pas autorisé."))

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValidationError(_("Saisissez une URL YouTube HTTPS valide.")) from error

    hostname = (parsed.hostname or "").lower()
    if (
        parsed.scheme.lower() != "https"
        or hostname not in YOUTUBE_HOSTS
        or parsed.username
        or parsed.password
        or port not in (None, 443)
    ):
        raise ValidationError(_("Seules les URLs HTTPS de YouTube sont autorisées."))

    video_id = None
    path_parts = [part for part in parsed.path.split("/") if part]
    if hostname in {"youtube.com", "www.youtube.com"}:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query, keep_blank_values=True).get("v", [])
            if len(values) == 1:
                video_id = values[0]
        elif len(path_parts) == 2 and path_parts[0] == "shorts":
            video_id = path_parts[1]
    elif hostname == "youtu.be" and len(path_parts) == 1:
        video_id = path_parts[0]

    if not video_id or not YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id):
        raise ValidationError(_("L’identifiant de la vidéo YouTube est invalide."))
    return video_id


def validate_youtube_url(value):
    extract_youtube_id(value)


def is_youtube_short_url(value):
    """Return whether a supported, validated YouTube URL uses the Shorts path."""
    extract_youtube_id(value)
    parsed = urlsplit(value)
    path_parts = [part for part in parsed.path.split("/") if part]
    return (
        (parsed.hostname or "").lower() in {"youtube.com", "www.youtube.com"}
        and len(path_parts) == 2
        and path_parts[0] == "shorts"
    )
