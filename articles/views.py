from django.shortcuts import render, redirect
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.urls import reverse
from .forms import ArticleForm 
from .models import Article
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.contrib import messages



def articles_view(request):
    article_list = Article.objects.all().order_by('-date_publication')
    paginator = Paginator(article_list, 6)  # 6 articles par page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'articles/list.html', context={'page_obj': page_obj})


def article_view(request, slug):
    article = get_object_or_404(Article, slug=slug)
    return render(request, 'articles/detail.html', context={'article': article})
    if article.is_premium and not request.user.is_authenticated:
        messages.warning(request, "Cet article est réservé aux abonnés.")
        return redirect('login')


@login_required
def creer_view(request):
    form = ArticleForm()
    if request.method == 'POST':
        form = ArticleForm(request.POST, request.FILES)
        if form.is_valid():
            article = form.save(commit=False)
            article.auteur = request.user  # Ajout de l’auteur
            article.save()
            return HttpResponseRedirect(reverse('articles:articles'))
    return render(request, 'articles/creer.html', context={'form': form})

@login_required
def modifier_view(request, slug):
    article = get_object_or_404(Article, slug=slug, auteur=request.user)
    form = ArticleForm(instance=article)

    if request.method == 'POST':
        form = ArticleForm(request.POST, request.FILES, instance=article)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse('articles:articles'))

    return render(request, 'articles/creer.html', context={'form': form})


@login_required
def supprimer_view(request, slug):
    article = get_object_or_404(Article, slug=slug, auteur=request.user)

    if request.method == 'POST':
        article.delete()
        return HttpResponseRedirect(reverse('articles:articles'))

    return render(request, 'articles/supprimer.html', context={'article': article})



   

