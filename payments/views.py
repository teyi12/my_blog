import uuid
import json
import stripe
import requests
import logging
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import redirect, render, get_object_or_404
from django.http import HttpResponse
from django.urls import reverse

from shop.models import Commande
from .forms import AdresseForm
from .utils import get_panier, get_total, enrichir_panier

# --- LOGGING ---
logger = logging.getLogger(__name__)

# --- STRIPE ---
stripe.api_key = settings.STRIPE_SECRET_KEY


@login_required
def choice(request):
    return render(request, "payments/choice.html", {
        "STRIPE_PUBLIC_KEY": settings.STRIPE_PUBLIC_KEY
    })


@login_required
def create_donation_checkout(request):
    """Don ponctuel avec montant libre"""
    if request.method != "POST":
        return redirect("payments:choice")

    try:
        amount = Decimal(request.POST.get("amount", "0"))
        currency = (request.POST.get("currency") or "eur").lower()
        if amount <= 0:
            return redirect("payments:choice")

        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": currency,
                    "product_data": {"name": f"Don à {request.user.first_name or request.user.email}"},
                    "unit_amount": int(amount * 100),
                },
                "quantity": 1,
            }],
            success_url=request.build_absolute_uri(reverse("payments:success")),
            cancel_url=request.build_absolute_uri(reverse("payments:cancel")),
            customer_email=request.user.email or None,
        )
        return redirect(session.url, code=303)
    except Exception as e:
        logger.error(f"Erreur Stripe donation: {e}")
        return redirect("payments:cancel")


@login_required
def create_subscription_checkout(request):
    """Abonnement mensuel"""
    price_id = settings.STRIPE_PRICE_MONTHLY
    if not price_id:
        return redirect("payments:choice")

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=request.build_absolute_uri(reverse("payments:success")),
            cancel_url=request.build_absolute_uri(reverse("payments:cancel")),
            customer_email=request.user.email or None,
        )
        return redirect(session.url, code=303)
    except Exception as e:
        logger.error(f"Erreur Stripe abonnement: {e}")
        return redirect("payments:cancel")


@login_required
def stripe_checkout(request, order_id):
    """Paiement d’une commande avec Stripe"""
    commande = get_object_or_404(Commande, id=order_id, client=request.user)
    try:
        montant = Decimal(str(commande.total))
        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "product_data": {"name": f"Commande #{commande.id}"},
                    "unit_amount": int(montant * 100),
                },
                "quantity": 1,
            }],
            success_url=request.build_absolute_uri(reverse("payments:success")),
            cancel_url=request.build_absolute_uri(reverse("payments:cancel")),
            customer_email=request.user.email or None,
        )
        return redirect(session.url, code=303)
    except Exception as e:
        logger.error(f"Erreur Stripe commande: {e}")
        return redirect("payments:cancel")


# --- MOBILE MONEY ---
@login_required
def mobile_money_checkout(request, order_id):
    """Paiement via API Mobile Money"""
    commande = get_object_or_404(Commande, id=order_id, client=request.user)
    
    payload = {
        "invoice": {
            "total_amount": str(Decimal(str(commande.total))),
            "description": f"Commande #{commande.id}"
        },
        "store": {
            "name": "Ma Boutique",
            "website_url": "https://maboutique.com"
        },
        "actions": {
            "cancel_url": request.build_absolute_uri(reverse("payments:cancel")),
            "return_url": request.build_absolute_uri(reverse("payments:success"))
        }
    }

    headers = {
        "Content-Type": "application/json",
        "ApiKey": settings.MOBILE_MONEY_API_KEY,
        "ApiSecret": settings.MOBILE_MONEY_SECRET_KEY
    }

    try:
        r = requests.post(settings.MOBILE_MONEY_BASE_URL, json=payload, headers=headers, timeout=30)
        data = r.json()
    except Exception as e:
        logger.error(f"Erreur Mobile Money: {e}")
        return render(request, "payments/error.html", {"error": "Impossible de contacter Mobile Money."})

    payment_url = data.get("invoice_url") or data.get("payment_url")
    if payment_url:
        return redirect(payment_url)
    else:
        return render(request, "payments/error.html", {"error": data})


# --- CINETPAY ---
CINETPAY_HEADERS = {"Content-Type": "application/json"}

def _abs_url(name, request):
    """Construit une URL absolue basée sur la requête"""
    return request.build_absolute_uri(reverse(name))


def _cinetpay_payload(commande, request, channel="MOBILE_MONEY"):
    tx_id = commande.transaction_id or uuid.uuid4().hex
    commande.transaction_id = tx_id
    commande.payment_channel = channel
    commande.save(update_fields=["transaction_id", "payment_channel"])

    return {
        "amount": str(Decimal(str(commande.total))),
        "currency": commande.currency or settings.DEFAULT_CURRENCY,
        "apikey": settings.CINETPAY_API_KEY,
        "site_id": settings.CINETPAY_SITE_ID,
        "transaction_id": tx_id,
        "description": f"Commande #{commande.id}",
        "notify_url": _abs_url("payments:cinetpay_ipn", request),
        "return_url": _abs_url("payments:cinetpay_return", request),
        "cancel_url": _abs_url("payments:cinetpay_cancel", request),
        "channels": channel,
    }


@login_required
def cinetpay_create_payment(request, order_id):
    commande = get_object_or_404(Commande, id=order_id, client=request.user)
    channel = request.GET.get("channel", "MOBILE_MONEY").upper()
    if channel not in ("MOBILE_MONEY", "CARD"):
        channel = "MOBILE_MONEY"

    payload = _cinetpay_payload(commande, request, channel=channel)
    try:
        r = requests.post(
            f"{settings.CINETPAY_BASE_URL}/payment",
            json=payload,
            headers=CINETPAY_HEADERS,
            timeout=30
        )
        data = r.json()
    except Exception as e:
        logger.error(f"Erreur CinetPay: {e}")
        return render(request, "payments/cancel.html", {"message": "Erreur de connexion à CinetPay."})

    payment_url = (data.get("data") or {}).get("payment_url")
    if str(data.get("code")) in ("201", "200") and payment_url:
        return redirect(payment_url)

    return render(request, "payments/cancel.html", {"message": data})


@csrf_exempt
def cinetpay_ipn(request):
    """Notification serveur à serveur"""
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception as e:
        logger.error(f"IPN invalide: {e}")
        return HttpResponse("INVALID_JSON", status=400)

    tx_id = data.get("transaction_id")
    if not tx_id:
        return HttpResponse("NO_TX", status=400)

    status = _cinetpay_check_status(tx_id)
    try:
        commande = Commande.objects.get(transaction_id=tx_id)
    except Commande.DoesNotExist:
        return HttpResponse("NO_ORDER", status=404)

    if status == "ACCEPTED":
        commande.payment_status = "SUCCESS"
    elif status in ("REFUSED", "CANCELED"):
        commande.payment_status = "FAILED"
    else:
        commande.payment_status = "PENDING"
    commande.save(update_fields=["payment_status"])

    return HttpResponse("OK", status=200)


def _cinetpay_check_status(transaction_id):
    try:
        r = requests.post(
            f"{settings.CINETPAY_BASE_URL}/payment/check",
            json={
                "apikey": settings.CINETPAY_API_KEY,
                "site_id": settings.CINETPAY_SITE_ID,
                "transaction_id": transaction_id,
            },
            headers=CINETPAY_HEADERS,
            timeout=30
        )
        data = r.json()
        return (data.get("data") or {}).get("status") or data.get("status")
    except Exception as e:
        logger.error(f"Erreur check status CinetPay: {e}")
        return "PENDING"


def cinetpay_return(request):
    tx_id = request.GET.get("transaction_id")
    status = _cinetpay_check_status(tx_id) if tx_id else "PENDING"
    ctx = {"status": status}
    return render(
        request,
        "payments/success.html" if status == "ACCEPTED" else "payments/cancel.html",
        ctx
    )


def cinetpay_cancel(request):
    return render(request, "payments/cancel.html")



