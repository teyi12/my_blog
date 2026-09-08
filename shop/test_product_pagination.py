import warnings

from django.core.paginator import UnorderedObjectListWarning
from django.test import TestCase
from django.urls import reverse

from .models import Produit


class ProductPaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.products = [
            Produit.objects.create(
                nom=f"Produit {index:02d}",
                slug=f"produit-{index:02d}",
                prix="10.00",
            )
            for index in range(14)
        ]

    def test_catalog_pagination_is_stable_and_ordered_by_primary_key(self):
        first_page = self.client.get(reverse("shop:liste"))
        second_page = self.client.get(reverse("shop:liste"), {"page": 2})
        repeated_second_page = self.client.get(reverse("shop:liste"), {"page": 2})

        expected_ids = [product.pk for product in self.products]
        first_ids = [product.pk for product in first_page.context["produits"]]
        second_ids = [product.pk for product in second_page.context["produits"]]
        repeated_ids = [
            product.pk for product in repeated_second_page.context["produits"]
        ]

        self.assertEqual(first_ids, expected_ids[:12])
        self.assertEqual(second_ids, expected_ids[12:])
        self.assertEqual(repeated_ids, second_ids)
        self.assertTrue(first_page.context["paginator"].object_list.ordered)

    def test_catalog_pagination_does_not_emit_unordered_queryset_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", UnorderedObjectListWarning)
            response = self.client.get(reverse("shop:liste"), {"page": 2})

        self.assertEqual(response.status_code, 200)
