"""Idempotent setup helpers for the loan plugin."""

from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from ..config import get_model_setting, get_setting, set_setting


class LoanSetupError(Exception):
    """Raised when the plugin has not been configured yet."""


def get_loan_location():
    """Return the configured On Loan stock location, if any."""
    from stock.models import StockLocation

    value = get_model_setting("LOAN_LOCATION")
    if not value:
        return None
    if hasattr(value, "pk"):
        return value
    return StockLocation.objects.filter(pk=value).first()


def get_on_loan_status():
    """Return the configured custom stock status, if it exists."""
    from common.models import InvenTreeCustomUserStateModel
    from django.contrib.contenttypes.models import ContentType
    from stock.models import StockItem

    content_type = ContentType.objects.get_for_model(StockItem)
    name = (get_setting("ON_LOAN_STATUS_NAME", "ON_LOAN") or "ON_LOAN").strip().upper()
    state = InvenTreeCustomUserStateModel.objects.filter(
        model=content_type, reference_status="StockStatus", name=name
    ).first()
    if state is None:
        return None
    from stock.status_codes import StockStatus

    if state.logical_key != StockStatus.QUARANTINED.value:
        return None
    return state


def get_on_loan_status_key() -> int:
    """Return the status key to use for loaned items.

    Falls back to InvenTree's built-in QUARANTINED status if the custom status
    has not been created yet.  QUARANTINED is excluded from the available stock
    status group, so the item is still unavailable while on loan.
    """
    from stock.status_codes import StockStatus

    state = get_on_loan_status()
    return state.key if state else StockStatus.QUARANTINED.value


def ensure_on_loan_status():
    """Create the custom On Loan stock status if it does not exist."""
    from common.models import InvenTreeCustomUserStateModel
    from django.contrib.contenttypes.models import ContentType
    from generic.states import ColorEnum
    from stock.models import StockItem
    from stock.status_codes import StockStatus

    content_type = ContentType.objects.get_for_model(StockItem)
    name = (get_setting("ON_LOAN_STATUS_NAME", "ON_LOAN") or "ON_LOAN").strip().upper()
    if not name.isidentifier() or name != name.upper():
        name = "ON_LOAN"

    state = InvenTreeCustomUserStateModel.objects.filter(
        model=content_type, reference_status="StockStatus", name=name
    ).first()
    if state:
        if state.logical_key != StockStatus.QUARANTINED.value:
            raise ValueError(
                "The configured On Loan status must use the Quarantined logical value. "
                "Choose a different status name or edit the existing custom status."
            )
        return state

    key = 500
    while InvenTreeCustomUserStateModel.objects.filter(
        reference_status="StockStatus", key=key
    ).exists():
        key += 1

    return InvenTreeCustomUserStateModel.objects.create(
        reference_status="StockStatus",
        logical_key=StockStatus.QUARANTINED.value,
        key=key,
        name=name,
        label=str(_("On Loan")),
        color=ColorEnum.info.value,
        model=content_type,
    )


def ensure_loan_location(name: str = "On Loan", parent=None):
    """Create or select the On Loan stock location and save it as a setting."""
    from stock.models import StockLocation

    location = StockLocation.objects.filter(
        parent=parent, name=name, structural=False
    ).first()
    if location is None:
        location = StockLocation.objects.create(
            parent=parent,
            name=name,
            description=str(_("Items currently loaned to users")),
            structural=False,
        )
    set_setting("LOAN_LOCATION", location.pk)
    return location


def ensure_setup(create_location: bool = False, location_name: str = "On Loan", parent=None) -> dict:
    """Create the required status and optionally the loan location.

    Returns a dictionary containing the current setup objects.  This function
    is intentionally explicit: the plugin never creates stock locations during
    migrations or app startup.
    """
    status = ensure_on_loan_status()
    location = get_loan_location()
    if location is None and create_location:
        location = ensure_loan_location(name=location_name, parent=parent)
    return {"status": status, "location": location}


def is_configured() -> bool:
    """Return True when the loan location and custom status are available."""
    return get_loan_location() is not None and get_on_loan_status() is not None
