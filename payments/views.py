import uuid
import json
import stripe
import requests
import logging
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import redirect, render, get_object_or_404
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from shop.models import Commande
from shop.services import (
    SQLiteLockRetryExhausted,
    execute_with_sqlite_lock_retry,
    finalize_paid_order,
)
from .models import Payment

# --- LOGGING ---
logger = logging.getLogger(__name__)

# --- STRIPE ---
stripe.api_key = settings.STRIPE_SECRET_KEY


# ================================================================
# CHOIX / RÉCAPITULATIF AVANT PAIEMENT
# ================================================================
@login_required
def choice(request, order_id=None):
    """Page de choix avant paiement"""
    if order_id is None:
        return redirect("shop:checkout")

    commande = get_object_or_404(
        Commande.objects.filter(lignes__isnull=False).distinct(),
        id=order_id,
        client=request.user,
        payment_status__in=("PENDING", "PROCESSING", "FAILED", "CANCELED"),
        adresse__isnull=False,
        total__gt=0,
    )

    return render(request, "payments/choice.html", {
        "STRIPE_PUBLIC_KEY": getattr(settings, "STRIPE_PUBLIC_KEY", ""),
        "commande": commande
    })


def _get_payable_order(request, order_id):
    return get_object_or_404(
        Commande.objects.filter(lignes__isnull=False).distinct(),
        id=order_id,
        client=request.user,
        payment_status="PENDING",
        adresse__isnull=False,
        total__gt=0,
    )


class PaymentChannelConflict(Exception):
    pass


class PaymentInitializationInProgress(Exception):
    pass


class PaymentResolutionRequired(Exception):
    def __init__(self, payment_id):
        self.payment_id = payment_id


class OrderAlreadyPaid(Exception):
    pass


class PaymentAmountTooLow(Exception):
    def __init__(self, amount, currency, minimum):
        self.amount = amount
        self.currency = currency
        self.minimum = minimum


def _minimum_payment_amount(currency):
    configured = getattr(settings, "PAYMENT_MINIMUM_AMOUNTS", {})
    defaults = {"EUR": "0.50", "USD": "0.50", "XOF": "500"}
    value = configured.get(currency.upper(), defaults.get(currency.upper()))
    if value is None:
        raise ValueError(f"Aucun montant minimum configuré pour {currency.upper()}.")
    minimum = Decimal(str(value))
    if minimum <= 0:
        raise ValueError(f"Le minimum configuré pour {currency.upper()} doit être positif.")
    return minimum


def _validate_order_payment_amount(commande):
    currency = commande.currency.upper()
    amount = Decimal(str(commande.total))
    # Valide aussi la précision monétaire, notamment l'absence de fraction XOF.
    _minor_amount(amount, currency)
    minimum = _minimum_payment_amount(currency)
    if amount < minimum:
        raise PaymentAmountTooLow(amount, currency, minimum)


def _payment_amount_error_response(request, order_id, exc):
    messages.error(
        request,
        f"Le montant minimum de paiement est de {exc.minimum} {exc.currency}. "
        f"Le total actuel est de {exc.amount} {exc.currency}.",
    )
    return redirect("payments:choice", order_id=order_id)


def _payment_timeout_seconds():
    configured = int(getattr(settings, "PAYMENT_PROCESSING_TIMEOUT_SECONDS", 3600))
    return min(max(configured, 1800), 86400)


def _processing_expiration_cutoff():
    """Return the cutoff after which an unfinished provider attempt is abandoned."""
    return timezone.now() - timedelta(seconds=_payment_timeout_seconds())


def _lock_order_then_payment(payment_id):
    """Lock payment state in the global Commande -> Payment order."""
    commande_id = Payment.objects.only("commande_id").get(pk=payment_id).commande_id
    commande = Commande.objects.select_for_update().get(pk=commande_id)
    payment = Payment.objects.select_for_update().get(
        pk=payment_id,
        commande_id=commande.id,
    )
    return commande, payment


def _reserve_payment(request, order_id, channel):
    """Reserve one provider attempt for an order.

    PENDING/FAILED/CANCELED -> PROCESSING creates a fresh Payment. A recent
    PROCESSING attempt is reused for the same provider and blocks every other
    provider. An expired PROCESSING attempt becomes CANCELED before a fresh
    Payment is created. SUCCESS is terminal and can never be reserved again.
    """
    def reserve_once():
        with transaction.atomic():
            commande = get_object_or_404(
                Commande.objects.select_for_update().filter(
                    lignes__isnull=False
                ).distinct(),
                id=order_id,
                client=request.user,
                payment_status__in=("PENDING", "PROCESSING", "FAILED", "CANCELED"),
                adresse__isnull=False,
                total__gt=0,
            )
            _validate_order_payment_amount(commande)
            active = Payment.objects.select_for_update().filter(
                commande=commande,
                status="PROCESSING",
            ).first()
            if active:
                if active.updated_at > _processing_expiration_cutoff():
                    if active.channel != channel:
                        raise PaymentChannelConflict
                    return commande, active

                raise PaymentResolutionRequired(active.id)
            if commande.payment_status == "PROCESSING":
                raise PaymentChannelConflict

            local_reference = f"pending_{uuid.uuid4().hex}"
            payment = Payment.objects.create(
                commande=commande,
                montant=commande.total,
                devise=commande.currency.upper(),
                transaction_id=local_reference,
                channel=channel,
                status="PROCESSING",
            )
            commande.payment_status = "PROCESSING"
            commande.payment_channel = channel
            commande.transaction_id = local_reference
            commande.save(update_fields=[
                "payment_status",
                "payment_channel",
                "transaction_id",
            ])
            return commande, payment

    for _attempt in range(2):
        try:
            return execute_with_sqlite_lock_retry(reserve_once)
        except PaymentResolutionRequired as exc:
            outcome = _resolve_expired_payment(exc.payment_id)
            if outcome == "SUCCESS":
                raise OrderAlreadyPaid
            if outcome != "TERMINAL":
                raise PaymentChannelConflict
        except IntegrityError:
            active = Payment.objects.select_related("commande").filter(
                commande_id=order_id,
                commande__client=request.user,
                status="PROCESSING",
            ).first()
            if not active:
                raise
            if active.channel != channel:
                raise PaymentChannelConflict
            return active.commande, active
    raise PaymentChannelConflict


def _store_provider_checkout_once(payment_id, provider_reference, checkout_url):
    with transaction.atomic():
        commande, payment = _lock_order_then_payment(payment_id)
        if payment.status != "PROCESSING":
            return payment
        if not payment.transaction_id.startswith("pending_"):
            if payment.transaction_id != provider_reference:
                raise PaymentChannelConflict
            if checkout_url and not payment.checkout_url:
                payment.checkout_url = checkout_url
                payment.save(update_fields=["checkout_url", "updated_at"])
            return payment

        payment.transaction_id = provider_reference
        payment.checkout_url = checkout_url
        payment.save(update_fields=["transaction_id", "checkout_url", "updated_at"])
        commande.transaction_id = provider_reference
        commande.save(update_fields=["transaction_id"])
        return payment


def _store_provider_checkout(payment_id, provider_reference, checkout_url):
    return execute_with_sqlite_lock_retry(
        lambda: _store_provider_checkout_once(
            payment_id,
            provider_reference,
            checkout_url,
        )
    )


def _minor_amount(amount, currency):
    zero_decimal = {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}
    decimal_amount = Decimal(str(amount))
    exponent = Decimal("1") if currency.lower() in zero_decimal else Decimal("0.01")
    normalized = decimal_amount.quantize(exponent)
    if normalized != decimal_amount:
        raise ValueError(f"Le montant {decimal_amount} n'est pas valide pour {currency.upper()}.")
    multiplier = 1 if currency.lower() in zero_decimal else 100
    return int(normalized * multiplier)


def _confirm_payment_once(payment_id, raw_response):
    with transaction.atomic():
        commande, payment = _lock_order_then_payment(payment_id)
        if payment.status == "SUCCESS":
            return payment
        if payment.status != "PROCESSING":
            raise PaymentChannelConflict

        finalize_paid_order(commande.id)
        payment.status = "SUCCESS"
        payment.raw_response = raw_response
        payment.save(update_fields=["status", "raw_response", "updated_at"])
        return payment


def _confirm_payment(payment_id, raw_response):
    return execute_with_sqlite_lock_retry(
        lambda: _confirm_payment_once(payment_id, raw_response)
    )


def _fail_payment_once(payment_id, raw_response):
    with transaction.atomic():
        commande, payment = _lock_order_then_payment(payment_id)
        if payment.status == "SUCCESS":
            return payment
        if payment.status in ("FAILED", "CANCELED"):
            return payment
        payment.status = "FAILED"
        payment.raw_response = raw_response
        payment.save(update_fields=["status", "raw_response", "updated_at"])
        if (
            commande.payment_status == "PROCESSING"
            and commande.transaction_id == payment.transaction_id
            and commande.payment_channel == payment.channel
        ):
            commande.payment_status = "FAILED"
            commande.save(update_fields=["payment_status"])
        return payment


def _fail_payment(payment_id, raw_response):
    return execute_with_sqlite_lock_retry(
        lambda: _fail_payment_once(payment_id, raw_response)
    )


def _cancel_payment_once(payment_id, raw_response):
    with transaction.atomic():
        commande, payment = _lock_order_then_payment(payment_id)
        if payment.status == "SUCCESS":
            return "SUCCESS"
        if payment.status in ("FAILED", "CANCELED"):
            return "TERMINAL"
        if payment.status != "PROCESSING":
            return "ACTIVE"

        payment.status = "CANCELED"
        payment.raw_response = raw_response
        payment.save(update_fields=["status", "raw_response", "updated_at"])
        if (
            commande.payment_status == "PROCESSING"
            and commande.transaction_id == payment.transaction_id
            and commande.payment_channel == payment.channel
        ):
            commande.payment_status = "CANCELED"
            commande.save(update_fields=["payment_status"])
        return "TERMINAL"


def _cancel_payment(payment_id, raw_response):
    return execute_with_sqlite_lock_retry(
        lambda: _cancel_payment_once(payment_id, raw_response)
    )


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
@require_POST
def stripe_checkout(request, order_id):
    """Paiement d’une commande avec Stripe"""
    try:
        commande, payment = _reserve_payment(request, order_id, "STRIPE")
        if payment.checkout_url:
            return redirect(payment.checkout_url, code=303)

        montant = Decimal(str(commande.total))
        currency = commande.currency.lower()

        session = stripe.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": currency,
                    "product_data": {"name": f"Commande #{commande.id}"},
                    "unit_amount": _minor_amount(montant, currency),
                },
                "quantity": 1,
            }],
            success_url=request.build_absolute_uri(reverse("payments:success")),
            cancel_url=request.build_absolute_uri(reverse("payments:cancel")),
            customer_email=request.user.email or None,
            metadata={
                "commande_id": str(commande.id),
                "user_id": str(request.user.id),
                "payment_id": str(payment.id),
            },
            expires_at=int(timezone.now().timestamp()) + _payment_timeout_seconds(),
            idempotency_key=str(payment.idempotency_key),
        )
        payment = _store_provider_checkout(payment.id, session.id, session.url)
        return redirect(payment.checkout_url, code=303)
    except PaymentChannelConflict:
        return HttpResponse("Une autre tentative de paiement est déjà active.", status=409)
    except OrderAlreadyPaid:
        return redirect("payments:success")
    except PaymentAmountTooLow as exc:
        return _payment_amount_error_response(request, order_id, exc)
    except SQLiteLockRetryExhausted:
        return HttpResponse("RETRY", status=409)
    except Exception:
        logger.exception("Erreur Stripe commande")
        return redirect("payments:cancel")


# ================================================================
# MOBILE MONEY
# ================================================================
@login_required
def mobile_money_checkout(request, order_id):
    """Paiement via API Mobile Money"""
    commande = _get_payable_order(request, order_id)

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


def _cinetpay_payload(commande, payment, request, channel="MOBILE_MONEY"):
    return {
        "amount": str(Decimal(str(commande.total))),
        "currency": commande.currency,
        "apikey": settings.CINETPAY_API_KEY,
        "site_id": settings.CINETPAY_SITE_ID,
        "transaction_id": payment.transaction_id,
        "description": f"Commande #{commande.id}",
        "notify_url": _abs_url("payments:cinetpay_ipn", request),
        "return_url": _abs_url("payments:cinetpay_return", request),
        "cancel_url": _abs_url("payments:cinetpay_cancel", request),
        "channels": channel,
    }


def _claim_cinetpay_initialization_once(payment_id):
    """Atomically claim the single allowed CinetPay network initialization."""
    claim_token = uuid.uuid4()
    now = timezone.now()
    stale_before = now - timedelta(seconds=120)
    claimed = Payment.objects.filter(
        pk=payment_id,
        channel="CINETPAY",
        status="PROCESSING",
        checkout_url="",
    ).filter(
        Q(initialization_token__isnull=True)
        | Q(initialization_started_at__lt=stale_before)
    ).update(
        initialization_token=claim_token,
        initialization_started_at=now,
    )
    return claim_token if claimed else None


def _claim_cinetpay_initialization(payment_id):
    return execute_with_sqlite_lock_retry(
        lambda: _claim_cinetpay_initialization_once(payment_id)
    )


def _release_cinetpay_initialization(payment_id, claim_token):
    return execute_with_sqlite_lock_retry(
        lambda: Payment.objects.filter(
            pk=payment_id,
            initialization_token=claim_token,
            checkout_url="",
        ).update(initialization_token=None, initialization_started_at=None)
    )


def _complete_cinetpay_initialization_once(payment_id, claim_token, checkout_url):
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if payment.checkout_url:
            return payment
        if payment.initialization_token != claim_token:
            raise PaymentInitializationInProgress
        payment.checkout_url = checkout_url
        payment.initialization_token = None
        payment.initialization_started_at = None
        payment.save(update_fields=[
            "checkout_url",
            "initialization_token",
            "initialization_started_at",
            "updated_at",
        ])
        return payment


def _complete_cinetpay_initialization(payment_id, claim_token, checkout_url):
    return execute_with_sqlite_lock_retry(
        lambda: _complete_cinetpay_initialization_once(
            payment_id,
            claim_token,
            checkout_url,
        )
    )


@login_required
@require_POST
def cinetpay_create_payment(request, order_id):
    channel = request.POST.get("channel", "MOBILE_MONEY").upper()
    if channel not in ("MOBILE_MONEY", "CARD"):
        channel = "MOBILE_MONEY"

    claim_token = None
    payment = None
    try:
        commande, payment = _reserve_payment(request, order_id, "CINETPAY")
        if payment.checkout_url:
            return redirect(payment.checkout_url)

        if payment.transaction_id.startswith("pending_"):
            cinetpay_reference = payment.transaction_id.removeprefix("pending_")
            payment = _store_provider_checkout(
                payment.id,
                cinetpay_reference,
                "",
            )
        claim_token = _claim_cinetpay_initialization(payment.id)
        if claim_token is None:
            payment.refresh_from_db(fields=["checkout_url"])
            if payment.checkout_url:
                return redirect(payment.checkout_url)
            raise PaymentInitializationInProgress
        payload = _cinetpay_payload(commande, payment, request, channel=channel)
        r = requests.post(
            f"{settings.CINETPAY_BASE_URL}/payment",
            json=payload,
            headers=CINETPAY_HEADERS,
            timeout=30
        )
        data = r.json()
    except PaymentChannelConflict:
        return HttpResponse("Une autre tentative de paiement est déjà active.", status=409)
    except OrderAlreadyPaid:
        return redirect("payments:success")
    except PaymentAmountTooLow as exc:
        return _payment_amount_error_response(request, order_id, exc)
    except PaymentInitializationInProgress:
        return HttpResponse("Initialisation CinetPay déjà en cours.", status=409)
    except SQLiteLockRetryExhausted:
        return HttpResponse("RETRY", status=409)
    except Exception:
        if payment is not None and claim_token is not None:
            try:
                _release_cinetpay_initialization(payment.id, claim_token)
            except SQLiteLockRetryExhausted:
                return HttpResponse("RETRY", status=409)
        logger.exception("Erreur CinetPay")
        return render(request, "payments/cancel.html", {"message": "Erreur de connexion à CinetPay."})

    payment_url = (data.get("data") or {}).get("payment_url")
    if str(data.get("code")) in ("201", "200") and payment_url:
        try:
            payment = _complete_cinetpay_initialization(
                payment.id,
                claim_token,
                payment_url,
            )
        except PaymentInitializationInProgress:
            return HttpResponse("Initialisation CinetPay remplacée.", status=409)
        except SQLiteLockRetryExhausted:
            return HttpResponse("RETRY", status=409)
        return redirect(payment.checkout_url)

    try:
        _release_cinetpay_initialization(payment.id, claim_token)
    except SQLiteLockRetryExhausted:
        return HttpResponse("RETRY", status=409)
    return render(request, "payments/cancel.html", {"message": data})


@csrf_exempt
def cinetpay_ipn(request):
    """Notification serveur à serveur"""
    tx_id = request.POST.get("cpm_trans_id") or request.POST.get("transaction_id")
    if not tx_id:
        try:
            data = json.loads(request.body.decode("utf-8"))
        except (TypeError, ValueError, UnicodeDecodeError):
            return HttpResponse("INVALID_PAYLOAD", status=400)
        tx_id = data.get("transaction_id") or data.get("cpm_trans_id")
    if not tx_id:
        return HttpResponse("NO_TX", status=400)

    try:
        payment = Payment.objects.select_related("commande").get(
            transaction_id=tx_id,
            channel="CINETPAY",
        )
    except Payment.DoesNotExist:
        return HttpResponse("NO_PAYMENT", status=404)

    if payment.status in ("SUCCESS", "FAILED", "CANCELED"):
        return HttpResponse("OK", status=200)

    provider_data = _cinetpay_check_status(tx_id)
    status = provider_data.get("status")
    provider_currency = str(provider_data.get("currency") or "").upper()
    try:
        provider_amount = Decimal(str(provider_data.get("amount")))
    except (TypeError, ValueError):
        return HttpResponse("INVALID_AMOUNT", status=400)

    if (
        payment.commande.transaction_id != payment.transaction_id
        or provider_amount != payment.montant
        or provider_amount != payment.commande.total
        or provider_currency != payment.devise.upper()
        or provider_currency != payment.commande.currency.upper()
    ):
        return HttpResponse("PAYMENT_MISMATCH", status=400)

    if status in ("REFUSED", "CANCELED"):
        try:
            _fail_payment(payment.id, provider_data)
        except SQLiteLockRetryExhausted:
            return HttpResponse("RETRY", status=409)
        return HttpResponse("OK", status=200)
    if status != "ACCEPTED":
        return HttpResponse("OK", status=200)

    try:
        _confirm_payment(payment.id, provider_data)
    except SQLiteLockRetryExhausted:
        return HttpResponse("RETRY", status=409)
    except PaymentChannelConflict:
        return HttpResponse("INVALID_STATE", status=409)

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
        provider_data = data.get("data") or {}
        if "status" not in provider_data and data.get("status"):
            provider_data["status"] = data["status"]
        return provider_data
    except Exception:
        logger.exception("Erreur check status CinetPay")
        return {}


def _stripe_value(session, key):
    if isinstance(session, dict):
        return session.get(key)
    return getattr(session, key, None)


def _stripe_payment_matches(payment, session):
    commande = payment.commande
    return (
        _stripe_value(session, "id") == payment.transaction_id
        and commande.transaction_id == payment.transaction_id
        and _stripe_value(session, "amount_total")
        == _minor_amount(payment.montant, payment.devise)
        and str(_stripe_value(session, "currency") or "").upper()
        == payment.devise.upper()
        and payment.montant == commande.total
        and payment.devise.upper() == commande.currency.upper()
    )


def _cinetpay_payment_matches(payment, provider_data):
    try:
        provider_amount = Decimal(str(provider_data.get("amount")))
    except (TypeError, ValueError):
        return False
    provider_currency = str(provider_data.get("currency") or "").upper()
    commande = payment.commande
    return (
        commande.transaction_id == payment.transaction_id
        and provider_amount == payment.montant
        and provider_amount == commande.total
        and provider_currency == payment.devise.upper()
        and provider_currency == commande.currency.upper()
    )


def _resolve_expired_stripe_payment(payment):
    if payment.transaction_id.startswith("pending_"):
        return _cancel_payment(payment.id, {"reason": "provider_not_initialized"})

    try:
        session = stripe.checkout.Session.retrieve(payment.transaction_id)
    except Exception:
        logger.exception("Impossible de vérifier la session Stripe expirée")
        return "ACTIVE"

    if _stripe_value(session, "payment_status") == "paid":
        if not _stripe_payment_matches(payment, session):
            return "ACTIVE"
        _confirm_payment(payment.id, dict(session))
        return "SUCCESS"

    status = _stripe_value(session, "status")
    if status == "expired":
        return _cancel_payment(payment.id, dict(session))
    if status != "open":
        return "ACTIVE"

    try:
        expired_session = stripe.checkout.Session.expire(payment.transaction_id)
    except Exception:
        logger.exception("Impossible d'expirer la session Stripe")
        return "ACTIVE"
    if _stripe_value(expired_session, "status") != "expired":
        return "ACTIVE"
    return _cancel_payment(payment.id, dict(expired_session))


def _resolve_expired_cinetpay_payment(payment):
    provider_data = _cinetpay_check_status(payment.transaction_id)
    status = provider_data.get("status")
    if status == "ACCEPTED":
        if not _cinetpay_payment_matches(payment, provider_data):
            return "ACTIVE"
        _confirm_payment(payment.id, provider_data)
        return "SUCCESS"
    if status in ("REFUSED", "CANCELED"):
        _fail_payment(payment.id, provider_data)
        return "TERMINAL"
    return "ACTIVE"


def _resolve_expired_payment(payment_id):
    payment = Payment.objects.select_related("commande").get(pk=payment_id)
    if payment.status == "SUCCESS":
        return "SUCCESS"
    if payment.status in ("FAILED", "CANCELED"):
        return "TERMINAL"
    if payment.status != "PROCESSING":
        return "ACTIVE"
    if payment.channel == "STRIPE":
        return _resolve_expired_stripe_payment(payment)
    if payment.channel == "CINETPAY":
        return _resolve_expired_cinetpay_payment(payment)
    return "ACTIVE"


def cinetpay_return(request):
    tx_id = request.GET.get("transaction_id")
    provider_data = _cinetpay_check_status(tx_id) if tx_id else {}
    status = provider_data.get("status", "PENDING")
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
        metadata = session.get("metadata") or {}
        commande_id = metadata.get("commande_id")
        user_id = metadata.get("user_id")
        payment_id = metadata.get("payment_id")

        try:
            payment = Payment.objects.select_related("commande").get(
                id=payment_id,
                commande_id=commande_id,
                commande__client_id=user_id,
                channel="STRIPE",
            )
            if payment.status in ("SUCCESS", "FAILED", "CANCELED"):
                return HttpResponse(status=200)
            expected_amount = _minor_amount(payment.montant, payment.devise)
            if (
                session.get("id") != payment.transaction_id
                or payment.commande.transaction_id != payment.transaction_id
                or session.get("payment_status") != "paid"
                or session.get("amount_total") != expected_amount
                or str(session.get("currency") or "").upper() != payment.devise.upper()
                or payment.montant != payment.commande.total
                or payment.devise.upper() != payment.commande.currency.upper()
            ):
                return HttpResponse("PAYMENT_MISMATCH", status=400)

            _confirm_payment(payment.id, dict(session))

        except Payment.DoesNotExist:
            return HttpResponse("NO_PAYMENT", status=404)
        except PaymentChannelConflict:
            return HttpResponse("INVALID_STATE", status=409)
        except SQLiteLockRetryExhausted:
            return HttpResponse("RETRY", status=409)

    # ❌ Paiement échoué ou annulé
    elif event["type"] in (
        "checkout.session.async_payment_failed",
        "checkout.session.expired",
    ):
        session = event["data"]["object"]
        metadata = session.get("metadata") or {}
        commande_id = metadata.get("commande_id")
        payment_id = metadata.get("payment_id")

        try:
            payment = Payment.objects.get(
                id=payment_id,
                commande_id=commande_id,
                channel="STRIPE",
                transaction_id=session.get("id"),
            )
            _fail_payment(payment.id, dict(session))
        except Payment.DoesNotExist:
            return HttpResponse("NO_PAYMENT", status=404)
        except SQLiteLockRetryExhausted:
            return HttpResponse("RETRY", status=409)

    return HttpResponse(status=200)



# ================================================================
# SUCCESS / CANCEL
# ================================================================
def paiement_reussi(request):
    return render(request, "payments/success.html")


def paiement_annule(request):
    return render(request, "payments/cancel.html")
