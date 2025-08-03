from django.core.management.base import BaseCommand
from accounts.models import CustomUser

class Command(BaseCommand):
    help = "Crée un superutilisateur par défaut (si inexistant)"

    def handle(self, *args, **options):
        email = 'admin@example.com'
        password = 'admin123'

        if not CustomUser.objects.filter(email=email).exists():
            CustomUser.objects.create_superuser(
                email=email,
                password=password,
                first_name='Admin',
                last_name='User'
            )
            self.stdout.write(self.style.SUCCESS(f'Superutilisateur créé: {email} / {password}'))
        else:
            self.stdout.write('Le superutilisateur existe déjà.')
