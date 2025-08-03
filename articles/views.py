from django.shortcuts import render
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.urls import reverse

from .forms import ArticleForm 
from .models import Article

def articles_view(request):
    articles = Article.objects.all().order_by ('-date_publication')
    return render(request, 'articles/list.html', context={'articles': articles})

def article_view(request, slug):
    article = get_object_or_404(Article, slug=slug)
    return render(request, 'articles/detail.html', context={'article': article})

from django.contrib.auth.decorators import login_required

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



   

