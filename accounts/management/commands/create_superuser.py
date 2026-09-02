import os

from django.core.management.base import BaseCommand, CommandError
from accounts.models import CustomUser


class Command(BaseCommand):
    help = "Crée un superutilisateur depuis des variables d'environnement explicites."

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not email or not password:
            raise CommandError(
                "DJANGO_SUPERUSER_EMAIL et DJANGO_SUPERUSER_PASSWORD sont obligatoires."
            )

        existing = CustomUser.objects.filter(email=email).first()
        if existing:
            if not existing.is_superuser:
                raise CommandError(
                    "Un utilisateur non-superutilisateur existe déjà avec cet e-mail."
                )
            self.stdout.write(
                f"Le superutilisateur {email} existe déjà ; aucune modification effectuée."
            )
            return

        CustomUser.objects.create_superuser(
            email=email,
            password=password,
            first_name=os.environ.get("DJANGO_SUPERUSER_FIRST_NAME", "Admin"),
            last_name=os.environ.get("DJANGO_SUPERUSER_LAST_NAME", ""),
        )
        self.stdout.write(self.style.SUCCESS(f"Superutilisateur créé : {email}."))
