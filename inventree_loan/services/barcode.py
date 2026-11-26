"""Barcode and QR code helpers."""

from __future__ import annotations

import io
import json
import uuid

from django.utils.translation import gettext_lazy as _

from ..config import get_setting
from ..models import Loan, LoanItem
from ..permissions import can_view_all, can_view_loan


def qr_payload(loan: Loan) -> str:
    """Return the JSON payload encoded in a loan QR code."""
    return json.dumps({"inventree_loan": str(loan.token)}, separators=(",", ":"))


def parse_loan_token(barcode: str):
    """Extract a loan UUID from a QR payload, or return None."""
    if not barcode:
        return None
    value = str(barcode).strip()
    prefix = (get_setting("LOAN_QR_PREFIX", "LOAN:") or "LOAN:").strip()
    if prefix and value.startswith(prefix):
        value = value[len(prefix):].strip()

    try:
        payload = json.loads(value)
        if isinstance(payload, dict):
            value = payload.get("inventree_loan") or payload.get("loan") or value
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _stock_payload(stock_item, user, full: bool = False) -> dict:

    active = (
        LoanItem.objects.filter(
            stock_item=stock_item, returned_at__isnull=True, lost=False
        )
        .select_related("loan", "loan__borrower")
        .first()
    )
    data = {
        "pk": stock_item.pk,
        "part": stock_item.part_id,
        "part_name": stock_item.part.name,
        "ipn": stock_item.part.IPN or "",
        "quantity": float(stock_item.quantity),
        "serial": stock_item.serial or "",
        "trackable": bool(getattr(stock_item.part, "trackable", False)),
        "status": stock_item.status,
        "status_text": stock_item.status_text,
        "location": stock_item.location.name if stock_item.location else "",
        "location_id": stock_item.location_id,
        "in_stock": stock_item.in_stock,
        "on_loan": bool(active),
    }
    if active:
        data["loan_id"] = active.loan_id
        data["loan_reference"] = active.loan.reference
        data["due_at"] = active.loan.due_at.isoformat()
        if full or can_view_all(user):
            data["borrower"] = str(active.loan.borrower)
    if full or can_view_all(user):
        data["notes"] = stock_item.notes or ""
        data["batch"] = stock_item.batch or ""
    return data


def _part_payload(part) -> dict:
    return {
        "pk": part.pk,
        "name": part.name,
        "ipn": part.IPN or "",
        "description": part.description or "",
        "category": part.category.name if part.category else "",
        "trackable": bool(getattr(part, "trackable", False)),
    }


def resolve_barcode(user, barcode: str) -> dict:
    """Resolve a scanned barcode to a loan, stock item, part, or location."""
    barcode = (barcode or "").strip()
    if not barcode:
        return {"success": False, "error": str(_("Empty barcode"))}

    token = parse_loan_token(barcode)
    if token:
        try:
            loan = Loan.objects.select_related(
                "borrower", "issued_by", "request"
            ).get(token=token)
        except Loan.DoesNotExist:
            return {"success": False, "error": str(_("Loan QR code not found"))}

        if not can_view_loan(user, loan):
            return {"success": False, "error": str(_("You cannot view this loan"))}

        return {
            "success": True,
            "type": "loan",
            "data": {
                "pk": loan.pk,
                "reference": loan.reference,
                "status": loan.status,
                "status_text": loan.get_status_display(),
                "borrower": str(loan.borrower) if can_view_all(user) else "",
                "due_at": loan.due_at.isoformat(),
                "is_overdue": loan.is_overdue,
                "items": [
                    {
                        "pk": item.pk,
                        "part_name": item.part.name,
                        "quantity": float(item.quantity),
                        "remaining": float(item.remaining_quantity),
                        "lost": item.lost,
                    }
                    for item in loan.items.select_related("part")
                ],
            },
        }

    # Delegate to InvenTree's registered barcode plugins.
    try:
        from plugin import PluginMixinEnum, registry

        for plugin in registry.with_mixin(PluginMixinEnum.BARCODE):
            try:
                result = plugin.scan(barcode, user=user)
            except Exception:
                continue
            if not result:
                continue
            if "stockitem" in result:
                from stock.models import StockItem

                pk = result["stockitem"].get("pk") if isinstance(result["stockitem"], dict) else result["stockitem"]
                item = StockItem.objects.select_related("part", "location").filter(pk=pk).first()
                if item:
                    return {"success": True, "type": "stockitem", "data": _stock_payload(item, user)}
            if "part" in result:
                from part.models import Part

                pk = result["part"].get("pk") if isinstance(result["part"], dict) else result["part"]
                part = Part.objects.select_related("category").filter(pk=pk).first()
                if part:
                    return {"success": True, "type": "part", "data": _part_payload(part)}
            if "stocklocation" in result:
                from stock.models import StockLocation

                pk = result["stocklocation"].get("pk") if isinstance(result["stocklocation"], dict) else result["stocklocation"]
                location = StockLocation.objects.filter(pk=pk).first()
                if location:
                    return {
                        "success": True,
                        "type": "stocklocation",
                        "data": {"pk": location.pk, "name": location.name, "path": location.pathstring},
                    }
    except Exception:  # pragma: no cover - barcode plugins may be unavailable
        pass

    return {"success": False, "error": str(_("No matching item found"))}


def generate_qr_svg_payload(payload: str) -> bytes:
    """Generate an SVG QR code from an arbitrary payload."""
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(
        payload,
        image_factory=qrcode.image.svg.SvgPathImage,
        box_size=12,
        border=2,
    )
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue()


def generate_qr_svg(loan: Loan) -> bytes:
    """Generate an SVG QR code for a loan."""
    return generate_qr_svg_payload(qr_payload(loan))


def generate_qr_png(loan: Loan) -> bytes:
    """Generate a PNG QR code for a loan.

    Requires the optional Pillow dependency.  SVG is the default.
    """
    import qrcode

    image = qrcode.make(qr_payload(loan), box_size=10, border=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
