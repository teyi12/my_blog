from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from payments.cancellations import cancel_order
from payments.models import Adresse, Payment
from shop.models import Commande, LigneCommande, Produit


class CanceledOrderPaymentPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.customer = user_model.objects.create_user(
            email="cancel-return@example.test",
            password="test-password",
        )
        cls.other_customer = user_model.objects.create_user(
            email="other-cancel-return@example.test",
            password="test-password",
        )

    def setUp(self):
        self.client.force_login(self.customer)
        self.address = Adresse.objects.create(
            utilisateur=self.customer,
            rue="1 rue du Retour",
            ville="Paris",
            code_postal="75001",
            pays="France",
        )
        self.product = Produit.objects.create(
            nom="Produit retour Stripe",
            slug="produit-retour-stripe",
            prix=Decimal("20.00"),
            stock=3,
        )
        self.order = Commande.objects.create(
            client=self.customer,
            adresse=self.address,
            total=Decimal("20.00"),
            currency="EUR",
        )
        LigneCommande.objects.create(
            commande=self.order,
            produit=self.product,
            quantite=1,
            prix_unitaire=self.product.prix,
        )

    def _start_stripe(self):
        session = SimpleNamespace(
            id=f"cs_cancel_return_{self.order.pk}",
            url="https://stripe.example.test/checkout",
        )
        with patch(
            "payments.views.stripe.checkout.Session.create",
            return_value=session,
        ) as create:
            response = self.client.post(
                reverse("payments:stripe_checkout", args=[self.order.pk])
            )
        self.assertEqual(response.status_code, 302)
        cancel_url = create.call_args.kwargs["cancel_url"]
        parsed = urlsplit(cancel_url)
        self.assertEqual(parsed.path, reverse("payments:cancel"))
        self.assertIn("order_context=", parsed.query)
        return f"{parsed.path}?{parsed.query}"

    def _cancel_order(self):
        with patch(
            "payments.cancellations.stripe.checkout.Session.expire",
            return_value={"status": "expired"},
        ):
            return cancel_order(self.order.pk, self.customer, "CUSTOMER")

    def test_canceled_order_return_hides_resume_and_links_to_order(self):
        cancel_url = self._start_stripe()
        self._cancel_order()

        response = self.client.get(cancel_url)

        self.assertContains(response, "Cette commande a déjà été annulée")
        self.assertNotContains(response, "Reprendre le paiement")
        self.assertContains(
            response,
            reverse("shop:ma_commande_detail", args=[self.order.pk]),
        )
        self.assertContains(response, reverse("shop:mes_commandes"))

    def test_unpaid_order_return_keeps_order_specific_resume(self):
        cancel_url = self._start_stripe()

        response = self.client.get(cancel_url)

        self.assertContains(response, "Reprendre le paiement")
        self.assertContains(
            response,
            reverse("payments:choice", args=[self.order.pk]),
        )

    def test_signed_context_does_not_reveal_another_customers_order(self):
        cancel_url = self._start_stripe()
        self._cancel_order()
        self.client.force_login(self.other_customer)

        response = self.client.get(cancel_url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Cette commande a déjà été annulée")
        self.assertNotContains(
            response,
            reverse("shop:ma_commande_detail", args=[self.order.pk]),
        )

    def test_forged_payment_restarts_for_canceled_order_are_refused(self):
        self._start_stripe()
        self._cancel_order()
        payment_count = Payment.objects.filter(commande=self.order).count()

        self.assertEqual(
            self.client.get(
                reverse("payments:choice", args=[self.order.pk])
            ).status_code,
            404,
        )
        with patch(
            "payments.views.stripe.checkout.Session.create"
        ) as stripe_create:
            stripe_response = self.client.post(
                reverse("payments:stripe_checkout", args=[self.order.pk])
            )
        with patch("payments.views.requests.post") as provider_post:
            cinetpay_response = self.client.post(
                reverse("payments:cinetpay_create", args=[self.order.pk])
            )
            mobile_response = self.client.post(
                reverse("payments:mobile_checkout", args=[self.order.pk])
            )

        self.assertEqual(stripe_response.status_code, 404)
        self.assertEqual(cinetpay_response.status_code, 404)
        self.assertEqual(mobile_response.status_code, 404)
        stripe_create.assert_not_called()
        provider_post.assert_not_called()
        self.assertEqual(
            Payment.objects.filter(commande=self.order).count(),
            payment_count,
        )

    def test_cancel_pages_without_order_keep_generic_behavior(self):
        generic = self.client.get(reverse("payments:cancel"))
        cinetpay = self.client.get(reverse("payments:cinetpay_cancel"))

        for response in (generic, cinetpay):
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Aucun paiement n’a été finalisé.")
            self.assertContains(response, "Reprendre le paiement")
            self.assertNotContains(response, "Cette commande a déjà été annulée")

    def test_donation_checkout_keeps_generic_cancel_url(self):
        with patch(
            "payments.views.donations_are_available",
            return_value=True,
        ), patch(
            "payments.views.stripe.checkout.Session.create",
            return_value=SimpleNamespace(
                id="cs_donation_cancel_compatibility",
                url="https://stripe.example.test/donation",
            ),
        ) as create:
            response = self.client.post(
                reverse("payments:create_donation_checkout"),
                {"amount": "10.00"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            create.call_args.kwargs["cancel_url"],
            f"http://testserver{reverse('payments:cancel')}",
        )
