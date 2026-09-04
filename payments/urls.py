from django.urls import path
from django.views.generic import TemplateView
from . import views

app_name = "payments"

urlpatterns = [
    # Pages client : candidates à une séparation i18n dans un lot ultérieur.
    path("choice/", views.choice, name="choice"),
    path("choice/<int:order_id>/", views.choice, name="choice"),

    # Déclenchements client Stripe, conservés non préfixés pour compatibilité.
    path("donate/", views.create_donation_checkout, name="create_donation_checkout"),
    path("subscribe/", views.create_subscription_checkout, name="create_subscription_checkout"),
    path("checkout/card/<int:order_id>/", views.stripe_checkout, name="stripe_checkout"),
    # Mobile Money (API custom)
    path("checkout/mobile/<int:order_id>/", views.mobile_money_checkout, name="mobile_checkout"),

    # CinetPay : création client puis retours et IPN techniques non préfixés.
    path("cinetpay/<int:order_id>/", views.cinetpay_create_payment, name="cinetpay_create"),
    path("cinetpay/return/", views.cinetpay_return, name="cinetpay_return"),
    path("cinetpay/cancel/", views.cinetpay_cancel, name="cinetpay_cancel"),
    path("cinetpay/ipn/", views.cinetpay_ipn, name="cinetpay_ipn"),  # webhook / notify_url

    # Webhook Stripe machine-à-machine : ne jamais le placer dans i18n_patterns.
    path("webhook/", views.stripe_webhook, name="stripe_webhook"),

    # Résultats
    path("success/", TemplateView.as_view(template_name="payments/success.html"), name="success"),
    path("cancel/", TemplateView.as_view(template_name="payments/cancel.html"), name="cancel"),
]
