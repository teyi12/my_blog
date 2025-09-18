from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect
from django.urls import reverse
from .forms import ArticleForm
from .models import Article, ArticleMedia
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import JsonResponse



def articles_view(request):
    article_list = Article.objects.all().order_by("-date_publication")
    paginator = Paginator(article_list, 6)  # 6 articles par page
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(request, "articles/list.html", {"page_obj": page_obj})


def article_view(request, slug):
    article = get_object_or_404(Article, slug=slug)

    # Gestion des articles premium
    if article.is_premium and not request.user.is_authenticated:
        messages.warning(request, "Cet article est réservé aux abonnés.")
        return redirect("login")

    return render(request, "articles/detail.html", {"article": article})


# ---- Restreindre aux STAFF uniquement ----
@staff_member_required
def creer_view(request):
    if request.method == "POST":
        form = ArticleForm(request.POST, request.FILES)
        if form.is_valid():
            article = form.save(commit=False)
            article.auteur = request.user  # Ajout de l’auteur
            article.save()
            messages.success(request, "✅ Article créé avec succès.")
            return HttpResponseRedirect(reverse("articles:articles"))
    else:
        form = ArticleForm()

    return render(request, "articles/creer.html", {"form": form})


@staff_member_required
def modifier_view(request, slug):
    article = get_object_or_404(Article, slug=slug)

    if request.method == "POST":
        form = ArticleForm(request.POST, request.FILES, instance=article)
        if form.is_valid():
            form.save()
            messages.success(request, "✏️ Article modifié avec succès.")
            return HttpResponseRedirect(reverse("articles:articles"))
    else:
        form = ArticleForm(instance=article)

    return render(request, "articles/creer.html", {"form": form, "article": article})


@staff_member_required
def supprimer_view(request, slug):
    article = get_object_or_404(Article, slug=slug)

    if request.method == "POST":
        article.delete()
        messages.success(request, "🗑 Article supprimé avec succès.")
        return HttpResponseRedirect(reverse("articles:articles"))

    return render(request, "articles/supprimer.html", {"article": article})

def article_media_json(request, slug):
    article = get_object_or_404(Article, slug=slug)
    media_type = request.GET.get("type", None)  # "image" ou "video"
    page = request.GET.get("page", 1)

    medias = article.medias.all().order_by("-date_ajout")
    if media_type in ["image", "video"]:
        medias = medias.filter(type=media_type)

    paginator = Paginator(medias, 6)  # 6 médias par page
    page_obj = paginator.get_page(page)

    media_data = []
    for media in page_obj:
        media_data.append({
            "id": media.id,
            "url": media.fichier.url,
            "type": media.type,
        })

    return JsonResponse({
        "media": media_data,
        "has_next": page_obj.has_next(),
        "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
    })