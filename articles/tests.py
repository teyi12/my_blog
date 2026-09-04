from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from monetization.models import Abonnement, AbonnementUtilisateur

from .models import Article


class ArticlePremiumAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.auteur = get_user_model().objects.create_user(
            email="auteur@example.com",
            password="test-password",
        )
        cls.utilisateur_gratuit = get_user_model().objects.create_user(
            email="gratuit@example.com",
            password="test-password",
        )
        cls.utilisateur_abonne = get_user_model().objects.create_user(
            email="abonne@example.com",
            password="test-password",
        )
        cls.utilisateur_expire = get_user_model().objects.create_user(
            email="expire@example.com",
            password="test-password",
        )
        cls.staff = get_user_model().objects.create_user(
            email="staff@example.com",
            password="test-password",
            is_staff=True,
        )
        cls.formule = Abonnement.objects.create(
            nom="Premium",
            prix="9.99",
            duree_jours=30,
            description="Accès aux articles premium",
        )
        maintenant = timezone.now()
        AbonnementUtilisateur.objects.create(
            utilisateur=cls.utilisateur_abonne,
            abonnement=cls.formule,
            date_fin=maintenant + timedelta(days=30),
            actif=True,
        )
        AbonnementUtilisateur.objects.create(
            utilisateur=cls.utilisateur_expire,
            abonnement=cls.formule,
            date_fin=maintenant - timedelta(days=1),
            actif=True,
        )
        cls.article_premium = Article.objects.create(
            titre="Article premium",
            contenu="Contenu réservé",
            slug="article-premium",
            auteur=cls.auteur,
            is_premium=True,
        )
        cls.article_public = Article.objects.create(
            titre="Article public",
            contenu="Contenu public",
            slug="article-public",
            auteur=cls.auteur,
            is_premium=False,
        )

    def test_visiteur_anonyme_est_redirige_vers_login_avec_next(self):
        url = reverse("articles:article_detail", args=[self.article_premium.slug])

        response = self.client.get(url)

        login_url = reverse("accounts:login")
        self.assertRedirects(response, f"{login_url}?next={url}")

    def test_utilisateur_gratuit_est_redirige_vers_les_abonnements(self):
        self.client.force_login(self.utilisateur_gratuit)

        response = self.client.get(
            reverse("articles:article_detail", args=[self.article_premium.slug])
        )

        self.assertRedirects(response, reverse("monetization:abonnements"))

    def test_utilisateur_avec_abonnement_actif_accede_a_article(self):
        self.client.force_login(self.utilisateur_abonne)

        response = self.client.get(
            reverse("articles:article_detail", args=[self.article_premium.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.article_premium.contenu)

    def test_utilisateur_avec_abonnement_expire_est_refuse(self):
        self.client.force_login(self.utilisateur_expire)

        response = self.client.get(
            reverse("articles:article_detail", args=[self.article_premium.slug])
        )

        self.assertRedirects(response, reverse("monetization:abonnements"))

    def test_staff_accede_a_article_premium_sans_abonnement(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("articles:article_detail", args=[self.article_premium.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.article_premium.contenu)

    def test_article_non_premium_reste_accessible_sans_connexion(self):
        response = self.client.get(
            reverse("articles:article_detail", args=[self.article_public.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.article_public.contenu)
