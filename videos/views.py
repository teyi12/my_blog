from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _

from monetization.services import utilisateur_a_acces_premium
from blog.seo import build_dynamic_seo

from .models import Video


def video_list(request):
    videos = (
        Video.objects.select_related("auteur", "categorie")
        .filter(est_publie=True)
        .order_by(
            F("ordre_affichage").asc(nulls_last=True),
            "-date_publication",
            "-pk",
        )
    )
    featured_video = videos.filter(en_vedette=True).first()
    if featured_video:
        videos = videos.exclude(pk=featured_video.pk)

    paginator = Paginator(videos, 6)
    page_obj = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "videos/list.html",
        {"featured_video": featured_video, "page_obj": page_obj},
    )


def video_detail(request, slug):
    video = get_object_or_404(
        Video.objects.select_related("auteur", "categorie"),
        slug=slug,
        est_publie=True,
    )
    if video.is_premium and not utilisateur_a_acces_premium(request.user):
        messages.warning(request, _("Cette vidéo est réservée aux abonnés."))
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), reverse("accounts:login"))
        return redirect("monetization:abonnements")

    seo = build_dynamic_seo(
        request,
        instance=video,
        view_name="videos:detail",
        kwargs={"slug": video.slug},
        title_field="titre",
        description_field="description",
        required_fields=("titre", "description"),
        image_field="miniature",
        og_type="video.other",
    )
    return render(request, "videos/detail.html", {"video": video, "seo": seo})

# Create your views here.
