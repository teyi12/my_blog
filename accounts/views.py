# Create your views here.
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from .forms import CustomUserCreationForm
from django.contrib.auth.decorators import login_required
from .forms import CustomUserUpdateForm
from django.contrib.auth.forms import AuthenticationForm
from django.contrib import messages


def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            login(request, user)  # Connexion automatique après inscription
            return redirect('home')  # redirige vers la vue nommée 'home'
    else:
        form = CustomUserCreationForm()
    return render(request, 'accounts/register.html', {'form': form})


@login_required
def profile_view(request):
    if request.method == 'POST':
        form = CustomUserUpdateForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            return redirect('profile')  # nom de l'URL de profil
    else:
        form = CustomUserUpdateForm(instance=request.user)
    return render(request, 'accounts/profile.html', {'form': form})


def login_view(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Bienvenue {user.first_name or user.username} !")
            return redirect('home')
        else:
            messages.error(request, "Email ou mot de passe incorrect.")
    else:
        form = AuthenticationForm()
    
    return render(request, 'accounts/login.html', {'form': form})