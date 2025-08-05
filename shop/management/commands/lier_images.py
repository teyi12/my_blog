from django.core.management.base import BaseCommand
from shop.models import Produit
from django.core.files import File
import os

class Command(BaseCommand):
    help = "Lie les images du dossier media/produits/ aux objets Produit."

    def handle(self, *args, **kwargs):
        media_path = os.path.join('media', 'produits')

        if not os.path.exists(media_path):
            self.stdout.write(self.style.ERROR("❌ Le dossier media/produits/ n'existe pas."))
            return

        produits = Produit.objects.all()

        for produit in produits:
            if not produit.image:
                image_name = f"{produit.nom.lower().replace(' ', '_')}.jpg"
                image_file_path = os.path.join(media_path, image_name)

                if os.path.exists(image_file_path):
                    with open(image_file_path, 'rb') as f:
                        produit.image.save(image_name, File(f), save=True)
                        self.stdout.write(self.style.SUCCESS(f"✅ Image liée à : {produit.nom}"))
                else:
                    self.stdout.write(self.style.WARNING(f"⚠️ Aucune image trouvée pour : {produit.nom}"))
            else:
                self.stdout.write(f"ℹ️ Produit déjà lié : {produit.nom}")
