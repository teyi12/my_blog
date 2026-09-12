from decimal import Decimal

from django.utils.translation import gettext as _


ZERO_DECIMAL_CURRENCIES = {
    "bif",
    "clp",
    "djf",
    "gnf",
    "jpy",
    "kmf",
    "krw",
    "mga",
    "pyg",
    "rwf",
    "ugx",
    "vnd",
    "vuv",
    "xaf",
    "xof",
    "xpf",
}


def minor_amount(amount, currency):
    decimal_amount = Decimal(str(amount))
    exponent = (
        Decimal("1")
        if currency.lower() in ZERO_DECIMAL_CURRENCIES
        else Decimal("0.01")
    )
    normalized = decimal_amount.quantize(exponent)
    if normalized != decimal_amount:
        raise ValueError(
            _("Le montant %(amount)s n'est pas valide pour %(currency)s.")
            % {"amount": decimal_amount, "currency": currency.upper()}
        )
    multiplier = 1 if currency.lower() in ZERO_DECIMAL_CURRENCIES else 100
    return int(normalized * multiplier)
