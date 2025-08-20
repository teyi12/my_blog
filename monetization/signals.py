from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Don, AbonnementUtilisateur, Publicite, Revenu
from django.utils.timezone import now


@receiver(post_save, sender=Don)
def enregistrer_revenu_don(sender, instance, created, **kwargs):
    """Enregistrer automatiquement un revenu quand un don est fait"""
    if created:
        Revenu.objects.create(
            type="DON",
            montant=instance.montant,
            date=now()
        )


@receiver(post_save, sender=AbonnementUtilisateur)
def enregistrer_revenu_abonnement(sender, instance, created, **kwargs):
    """Enregistrer un revenu à l'achat d'un abonnement"""
    if created:
        Revenu.objects.create(
            type="SUB",
            montant=instance.abonnement.prix,
            date=now()
        )


@receiver(post_save, sender=Publicite)
def enregistrer_revenu_pub(sender, instance, created, **kwargs):
    """Exemple : on enregistre un revenu quand une pub est créée et activée"""
    if created and instance.actif:
        # Tu peux ici adapter le montant (forfait pub, CPM, etc.)
        Revenu.objects.create(
            type="PUB",
            montant=50.00,  # Exemple fixe, à adapter à ton modèle économique
            date=now()
        )
