from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.core.mail import send_mail                                                                        
from shop.models import Produit
from .forms import ContactForm

def home_view(request):
    produits_vedettes = Produit.objects.filter(en_vedette=True)[:6]
    return render(request, 'home.html', {
        'produits_vedettes': produits_vedettes
    })

def contact_view(request):
    form = ContactForm()
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            nom = form.cleaned_data['nom']
            prenom = form.cleaned_data['prenom']
            email = form.cleaned_data['email']
            message = form.cleaned_data['message']

            titre = f'Blog | {nom} {prenom} {email}'
            send_mail(titre, message, 'teyi9lawson9@gmail.com', 
            ['teyi9lawson9@gmail.com'])

        return HttpResponseRedirect(reverse("remerciement"))
    return render(request, 'contact.html', {"form": form})

def remerciement_view(request):
    return HttpResponse('Merci de nous avoir contacter')
