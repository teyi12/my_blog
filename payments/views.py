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

from shop.models import Commande, Cart
from .utils import get_total

# --- LOGGING ---
logger = logging.getLogger(__name__)

# --- STRIPE ---
stripe.api_key = settings.STRIPE_SECRET_KEY


# ================================================================
# CHOIX / RÉCAPITULATIF AVANT PAIEMENT
# ================================================================
@login_required
def choice(request):
    """Page de choix avant paiement"""
    commande = Commande.objects.filter(client=request.user, payment_status="PENDING").first()
    if not commande:
        total = get_total(request) or Decimal("1000.00")
        commande = Commande.objects.create(
            client=request.user,
            total=total,
            currency=getattr(settings, "DEFAULT_CURRENCY", "EUR"),
            payment_status="PENDING"
        )

    return render(request, "payments/choice.html", {
        "STRIPE_PUBLIC_KEY": getattr(settings, "STRIPE_PUBLIC_KEY", ""),
        "commande": commande
    })


# ================================================================
# STRIPE : DON
# ================================================================
@login_required
def create_donation_checkout(request):
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
                    "product_data": {"name": f"Don {request.user.email}"},
                    "unit_amount": int(amount * 100),
                },
                "quantity": 1,
            }],
            success_url=request.build_absolute_uri(reverse("payments:success")),
            cancel_url=request.build_absolute_uri(reverse("payments:cancel")),
            customer_email=request.user.email or None,
            metadata={
                "donation": "1",
                "user_id": str(request.user.id)
            }
        )
        return redirect(session.url, code=303)
    except Exception:
        logger.exception("Erreur Stripe donation")
        return redirect("payments:cancel")


# ================================================================
# STRIPE : ABONNEMENT
# ================================================================
@login_required
def create_subscription_checkout(request):
    price_id = getattr(settings, "STRIPE_PRICE_MONTHLY", None)
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
            metadata={"user_id": str(request.user.id)}
        )
        return redirect(session.url, code=303)
    except Exception:
        logger.exception("Erreur Stripe abonnement")
        return redirect("payments:cancel")


# ================================================================
# STRIPE : COMMANDE
# ================================================================
@login_required
def stripe_checkout(request, order_id):
    """Paiement d’une commande avec Stripe"""
    commande = get_object_or_404(Commande, id=order_id, client=request.user)
    try:
        montant = Decimal(str(commande.total))
        currency = (commande.currency or getattr(settings, "DEFAULT_CURRENCY", "EUR")).lower()

        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": currency,
                    "product_data": {"name": f"Commande #{commande.id}"},
                    "unit_amount": int(montant * 100),
                },
                "quantity": 1,
            }],
            success_url=request.build_absolute_uri(reverse("payments:success")),
            cancel_url=request.build_absolute_uri(reverse("payments:cancel")),
            customer_email=request.user.email or None,
            metadata={
                "commande_id": str(commande.id),
                "user_id": str(request.user.id)
            },
        )
        return redirect(session.url, code=303)
    except Exception:
        logger.exception("Erreur Stripe commande")
        return redirect("payments:cancel")


# ================================================================
# MOBILE MONEY
# ================================================================
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
        "ApiSecret": settings.MOBILE_MONEY_SECRET_KEY,
    }

    try:
        r = requests.post(settings.MOBILE_MONEY_BASE_URL, json=payload, headers=headers, timeout=30)
        data = r.json()
    except Exception:
        logger.exception("Erreur Mobile Money")
        return render(request, "payments/error.html", {"error": "Impossible de contacter Mobile Money."})

    payment_url = data.get("invoice_url") or data.get("payment_url")
    if payment_url:
        return redirect(payment_url)

    return render(request, "payments/error.html", {"error": data})


# ================================================================
# CINETPAY
# ================================================================
CINETPAY_HEADERS = {"Content-Type": "application/json"}


def _abs_url(name, request):
    return request.build_absolute_uri(reverse(name))


def _cinetpay_payload(commande, request, channel="MOBILE_MONEY"):
    tx_id = commande.transaction_id or uuid.uuid4().hex
    commande.transaction_id = tx_id
    commande.payment_channel = channel
    commande.save(update_fields=["transaction_id", "payment_channel"])

    return {
        "amount": str(Decimal(str(commande.total))),
        "currency": commande.currency or getattr(settings, "DEFAULT_CURRENCY", "EUR"),
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
    except Exception:
        logger.exception("Erreur CinetPay")
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
    except Exception:
        logger.exception("IPN invalide")
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
    except Exception:
        logger.exception("Erreur check status CinetPay")
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


# ================================================================
# STRIPE WEBHOOK
# ================================================================
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, endpoint_secret
        )
    except ValueError:
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        return HttpResponse(status=400)

    # ✅ Paiement réussi
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        commande_id = session["metadata"].get("commande_id")
        user_id = session["metadata"].get("user_id")

        try:
            commande = Commande.objects.get(id=commande_id, client_id=user_id)
            commande.payment_status = "SUCCESS"
            commande.save(update_fields=["payment_status"])

            # 🧹 Vider le panier de l'utilisateur
            from shop.models import Cart
            cart = Cart.objects.filter(user_id=user_id).first()
            if cart:
                cart.items.all().delete()

        except Commande.DoesNotExist:
            pass

    # ❌ Paiement échoué ou annulé
    elif event["type"] == "checkout.session.async_payment_failed":
        session = event["data"]["object"]
        commande_id = session["metadata"].get("commande_id")

        try:
            commande = Commande.objects.get(id=commande_id)
            commande.payment_status = "FAILED"
            commande.save(update_fields=["payment_status"])
        except Commande.DoesNotExist:
            pass

    return HttpResponse(status=200)



# ================================================================
# SUCCESS / CANCEL
# ================================================================
def paiement_reussi(request):
    return render(request, "payments/success.html")


def paiement_annule(request):
    return render(request, "payments/cancel.html")
