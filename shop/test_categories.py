from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from shop.models import Categorie, Produit


class CategoryManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            email="staff@example.com",
            password="test-password",
            is_staff=True,
        )
        self.customer = user_model.objects.create_user(
            email="customer@example.com",
            password="test-password",
        )
        self.category = Categorie.objects.create(nom="Mode")

    def test_category_management_requires_staff(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("shop:categorie_gestion_liste"))
        self.assertEqual(response.status_code, 302)

    def test_staff_can_list_categories_with_product_count(self):
        Produit.objects.create(
            nom="Jean",
            slug="jean",
            prix=Decimal("45.00"),
            categorie=self.category,
        )
        self.client.force_login(self.staff)

        response = self.client.get(reverse("shop:categorie_gestion_liste"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mode")
        category = response.context["categories"].get(pk=self.category.pk)
        self.assertEqual(category.nombre_produits, 1)

    def test_staff_can_create_category_and_slug_is_generated(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("shop:categorie_creer"),
            {"nom": "Accessoires Maison"},
        )

        self.assertRedirects(response, reverse("shop:categorie_gestion_liste"))
        category = Categorie.objects.get(nom="Accessoires Maison")
        self.assertEqual(category.slug, "accessoires-maison")

    def test_duplicate_category_name_is_rejected_case_insensitively(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("shop:categorie_creer"),
            {"nom": "mode"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Une catégorie portant ce nom existe déjà.")
        self.assertEqual(Categorie.objects.count(), 1)

    def test_staff_can_rename_category_and_slug_is_updated(self):
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("shop:categorie_modifier", args=[self.category.slug]),
            {"nom": "Mode Premium"},
        )

        self.assertRedirects(response, reverse("shop:categorie_gestion_liste"))
        self.category.refresh_from_db()
        self.assertEqual(self.category.nom, "Mode Premium")
        self.assertEqual(self.category.slug, "mode-premium")

    def test_deleting_category_keeps_products(self):
        product = Produit.objects.create(
            nom="Jean",
            slug="jean",
            prix=Decimal("45.00"),
            categorie=self.category,
        )
        self.client.force_login(self.staff)

        response = self.client.post(
            reverse("shop:categorie_supprimer", args=[self.category.slug])
        )

        self.assertRedirects(response, reverse("shop:categorie_gestion_liste"))
        self.assertFalse(Categorie.objects.filter(pk=self.category.pk).exists())
        product.refresh_from_db()
        self.assertIsNone(product.categorie)
