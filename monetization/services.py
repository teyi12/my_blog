from django.utils import timezone

from .models import AbonnementUtilisateur


def utilisateur_a_acces_premium(utilisateur):
    """Indique si un utilisateur peut consulter le contenu premium."""
    if not utilisateur.is_authenticated:
        return False

    if utilisateur.is_staff or utilisateur.is_superuser:
        return True

    maintenant = timezone.now()
    return AbonnementUtilisateur.objects.filter(
        utilisateur=utilisateur,
        actif=True,
        date_debut__lte=maintenant,
        date_fin__gt=maintenant,
    ).exists()
