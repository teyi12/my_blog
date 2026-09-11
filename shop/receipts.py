from decimal import Decimal
from importlib import resources
from io import BytesIO
from threading import Lock
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import formats, timezone, translation
from django.utils.translation import gettext as _
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.doctemplate import LayoutError

from .models import OrderReceipt


SUPPORTED_RECEIPT_LANGUAGES = {"fr", "de", "en"}
RECEIPT_FONT = "OrderReceiptVera"
RECEIPT_FONT_BOLD = "OrderReceiptVeraBold"
_FONT_LOCK = Lock()


class OrderReceiptPDFError(Exception):
    """An expected failure while producing a receipt PDF."""


def normalize_receipt_language(language_code):
    return language_code if language_code in SUPPORTED_RECEIPT_LANGUAGES else "fr"


def decimal_snapshot(value):
    return format(Decimal(value), "f")


def receipt_snapshot_defaults(order, issued_at=None):
    customer = order.client
    address = order.adresse
    customer_name = " ".join(
        part.strip()
        for part in (customer.first_name or "", customer.last_name or "")
        if part.strip()
    )
    address_snapshot = {}
    if address is not None:
        address_snapshot = {
            "street": address.rue or "",
            "postal_code": address.code_postal or "",
            "city": address.ville or "",
            "country": address.pays or "",
        }

    items_snapshot = []
    for line in order.lignes.order_by("pk"):
        quantity = int(line.quantite)
        unit_price = Decimal(line.prix_unitaire)
        items_snapshot.append(
            {
                "name": line.nom_produit_snapshot or "Produit indisponible",
                "quantity": quantity,
                "unit_price": decimal_snapshot(unit_price),
                "subtotal": decimal_snapshot(unit_price * quantity),
            }
        )

    return {
        "issued_at": issued_at or timezone.now(),
        "language_code": normalize_receipt_language(order.language_code),
        "currency": (order.currency or "EUR").upper(),
        "total": order.total,
        "payment_channel": order.payment_channel or "",
        "issuer_name": settings.ORDER_RECEIPT_ISSUER_NAME,
        "issuer_contact": settings.ORDER_RECEIPT_ISSUER_CONTACT,
        "customer_name": customer_name,
        "customer_email": customer.email,
        "address_snapshot": address_snapshot,
        "items_snapshot": items_snapshot,
    }


def ensure_order_receipt(order, issued_at=None):
    """Create the sole immutable receipt for a paid order, if missing."""
    if order.payment_status != "SUCCESS":
        return None
    receipt, _created = OrderReceipt.objects.get_or_create(
        commande=order,
        defaults=receipt_snapshot_defaults(order, issued_at=issued_at),
    )
    return receipt


def _register_receipt_fonts():
    with _FONT_LOCK:
        registered = set(pdfmetrics.getRegisteredFontNames())
        fonts_directory = resources.files("reportlab").joinpath("fonts")
        if RECEIPT_FONT not in registered:
            pdfmetrics.registerFont(
                TTFont(RECEIPT_FONT, str(fonts_directory.joinpath("Vera.ttf")))
            )
        if RECEIPT_FONT_BOLD not in registered:
            pdfmetrics.registerFont(
                TTFont(
                    RECEIPT_FONT_BOLD,
                    str(fonts_directory.joinpath("VeraBd.ttf")),
                )
            )


def _safe_paragraph_text(value):
    return escape(str(value or "")).replace("\n", "<br/>")


def _money(value, currency):
    amount = decimal_snapshot(value)
    if currency == "EUR":
        return f"{amount} €"
    return f"{amount} {currency}"


def receipt_pdf_labels(language_code):
    """Return translated PDF labels for tests and document generation."""
    with translation.override(normalize_receipt_language(language_code)):
        return {
            "title": str(_("Reçu de paiement")),
            "reference": str(_("Référence du reçu")),
            "order": str(_("Commande")),
            "issued_at": str(_("Date d’émission")),
            "issuer": str(_("Émetteur")),
            "customer": str(_("Client")),
            "address": str(_("Adresse")),
            "channel": str(_("Canal de paiement")),
            "item": str(_("Article")),
            "quantity": str(_("Quantité")),
            "unit_price": str(_("Prix unitaire")),
            "subtotal": str(_("Sous-total")),
            "total": str(_("Total")),
            "status": str(_("Statut")),
            "paid": str(_("Payé")),
            "page": str(_("Page")),
            "legal_note": str(
                _(
                    "Ce reçu confirme le paiement de la commande. "
                    "Il ne constitue pas une facture fiscale."
                )
            ),
            "not_provided": str(_("Non renseigné")),
            "card": str(_("Carte bancaire")),
            "mobile_money": str(_("Mobile Money")),
            "stripe": str(_("Stripe")),
            "cinetpay": str(_("CinetPay")),
            "other": str(_("Autre")),
        }


def _payment_channel_label(channel, labels):
    return {
        "CARD": labels["card"],
        "MOBILE_MONEY": labels["mobile_money"],
        "STRIPE": labels["stripe"],
        "CINETPAY": labels["cinetpay"],
    }.get(channel, labels["other"] if channel else labels["not_provided"])


def _draw_page_number(canvas, document, labels):
    canvas.saveState()
    canvas.setFont(RECEIPT_FONT, 8)
    canvas.setFillColor(colors.HexColor("#667085"))
    canvas.drawRightString(
        A4[0] - 20 * mm,
        12 * mm,
        f"{labels['page']} {document.page}",
    )
    canvas.restoreState()


def render_order_receipt_pdf(receipt):
    """Render a receipt entirely in memory using its historical language."""
    try:
        _register_receipt_fonts()
        buffer = BytesIO()
        labels = receipt_pdf_labels(receipt.language_code)
        styles = getSampleStyleSheet()
        body = ParagraphStyle(
            "ReceiptBody",
            parent=styles["BodyText"],
            fontName=RECEIPT_FONT,
            fontSize=9,
            leading=13,
            textColor=colors.HexColor("#344054"),
        )
        heading = ParagraphStyle(
            "ReceiptHeading",
            parent=body,
            fontName=RECEIPT_FONT_BOLD,
            fontSize=20,
            leading=24,
            textColor=colors.HexColor("#101828"),
            spaceAfter=6,
        )
        section = ParagraphStyle(
            "ReceiptSection",
            parent=body,
            fontName=RECEIPT_FONT_BOLD,
            fontSize=10,
            textColor=colors.HexColor("#101828"),
        )
        right = ParagraphStyle("ReceiptRight", parent=body, alignment=TA_RIGHT)
        centered_note = ParagraphStyle(
            "ReceiptNote",
            parent=body,
            alignment=TA_CENTER,
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#475467"),
        )
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=20 * mm,
            leftMargin=20 * mm,
            topMargin=18 * mm,
            bottomMargin=20 * mm,
            title=labels["title"],
            author=receipt.issuer_name,
        )

        with translation.override(normalize_receipt_language(receipt.language_code)):
            issued_at = formats.date_format(
                timezone.localtime(receipt.issued_at),
                "SHORT_DATETIME_FORMAT",
            )

        story = [
            Paragraph(_safe_paragraph_text(labels["title"]), heading),
            Paragraph(
                _safe_paragraph_text(
                    f"{labels['reference']} : {receipt.public_id}"
                ),
                body,
            ),
            Spacer(1, 7 * mm),
        ]
        summary_data = [
            [
                Paragraph(_safe_paragraph_text(labels["order"]), section),
                Paragraph(f"#{receipt.commande_id}", right),
            ],
            [
                Paragraph(_safe_paragraph_text(labels["issued_at"]), section),
                Paragraph(_safe_paragraph_text(issued_at), right),
            ],
            [
                Paragraph(_safe_paragraph_text(labels["channel"]), section),
                Paragraph(
                    _safe_paragraph_text(
                        _payment_channel_label(receipt.payment_channel, labels)
                    ),
                    right,
                ),
            ],
            [
                Paragraph(_safe_paragraph_text(labels["status"]), section),
                Paragraph(_safe_paragraph_text(labels["paid"]), right),
            ],
        ]
        summary = Table(summary_data, colWidths=[70 * mm, 90 * mm])
        summary.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#EAECF0")),
                ]
            )
        )
        story.extend([summary, Spacer(1, 8 * mm)])

        address = receipt.address_snapshot or {}
        address_lines = [
            address.get("street", ""),
            " ".join(
                value
                for value in (
                    address.get("postal_code", ""),
                    address.get("city", ""),
                )
                if value
            ),
            address.get("country", ""),
        ]
        address_text = "\n".join(value for value in address_lines if value)
        parties = Table(
            [
                [
                    Paragraph(_safe_paragraph_text(labels["issuer"]), section),
                    Paragraph(_safe_paragraph_text(labels["customer"]), section),
                ],
                [
                    Paragraph(
                        _safe_paragraph_text(
                            "\n".join(
                                value
                                for value in (
                                    receipt.issuer_name,
                                    receipt.issuer_contact,
                                )
                                if value
                            )
                        ),
                        body,
                    ),
                    Paragraph(
                        _safe_paragraph_text(
                            "\n".join(
                                value
                                for value in (
                                    receipt.customer_name,
                                    receipt.customer_email,
                                    address_text,
                                )
                                if value
                            )
                        ),
                        body,
                    ),
                ],
            ],
            colWidths=[80 * mm, 80 * mm],
        )
        parties.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D5DD")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#EAECF0")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F9FAFB")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.extend([parties, Spacer(1, 9 * mm)])

        item_rows = [
            [
                Paragraph(_safe_paragraph_text(labels["item"]), section),
                Paragraph(_safe_paragraph_text(labels["quantity"]), section),
                Paragraph(_safe_paragraph_text(labels["unit_price"]), section),
                Paragraph(_safe_paragraph_text(labels["subtotal"]), section),
            ]
        ]
        for item in receipt.items_snapshot:
            item_rows.append(
                [
                    Paragraph(_safe_paragraph_text(item["name"]), body),
                    Paragraph(_safe_paragraph_text(item["quantity"]), right),
                    Paragraph(
                        _safe_paragraph_text(
                            _money(item["unit_price"], receipt.currency)
                        ),
                        right,
                    ),
                    Paragraph(
                        _safe_paragraph_text(
                            _money(item["subtotal"], receipt.currency)
                        ),
                        right,
                    ),
                ]
            )
        item_table = LongTable(
            item_rows,
            repeatRows=1,
            colWidths=[77 * mm, 23 * mm, 31 * mm, 31 * mm],
        )
        item_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#98A2B3")),
                    ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#EAECF0")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.extend([item_table, Spacer(1, 7 * mm)])

        total_table = Table(
            [
                [
                    Paragraph(_safe_paragraph_text(labels["total"]), section),
                    Paragraph(
                        _safe_paragraph_text(
                            f"{_money(receipt.total, receipt.currency)} "
                            f"({receipt.currency})"
                        ),
                        ParagraphStyle(
                            "ReceiptTotal",
                            parent=right,
                            fontName=RECEIPT_FONT_BOLD,
                            fontSize=11,
                        ),
                    ),
                ]
            ],
            colWidths=[80 * mm, 80 * mm],
        )
        total_table.setStyle(
            TableStyle(
                [
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#101828")),
                ]
            )
        )
        story.extend(
            [
                total_table,
                Spacer(1, 10 * mm),
                Paragraph(_safe_paragraph_text(labels["legal_note"]), centered_note),
            ]
        )

        page_callback = lambda canvas, doc: _draw_page_number(canvas, doc, labels)
        document.build(
            story,
            onFirstPage=page_callback,
            onLaterPages=page_callback,
        )
        return buffer.getvalue()
    except (TTFError, LayoutError, OSError, UnicodeError) as exc:
        raise OrderReceiptPDFError from None
