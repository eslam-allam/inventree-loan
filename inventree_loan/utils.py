"""Small shared helpers for the loan plugin."""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

MAX_SIGNATURE_LENGTH = 400_000
_SIGNATURE_PREFIXES = (
    "data:image/png;base64,",
    "data:image/jpeg;base64,",
    "data:image/svg+xml;base64,",
)


def clean_signature(value, *, required: bool = False, field: str = "signature") -> str:
    """Validate a signature captured as an image data URL.

    The browser stores the canvas as a data URL.  Reject arbitrary HTML or
    oversized payloads before they reach the database.
    """
    value = (value or "").strip()
    if not value:
        if required:
            raise ValidationError({field: _("A signature is required")})
        return ""
    if not value.startswith(_SIGNATURE_PREFIXES):
        raise ValidationError({field: _("The signature must be an image")})
    if len(value) > MAX_SIGNATURE_LENGTH:
        raise ValidationError({field: _("The signature is too large")})
    return value


def local_today() -> date:
    """Return today's date in the active timezone.

    ``django.utils.timezone.localdate()`` raises when ``USE_TZ`` is disabled
    (for example while InvenTree's test suite is running), because ``now()``
    returns a naive datetime in that configuration.  This helper accepts both
    aware and naive datetimes.
    """
    now = timezone.now()
    if timezone.is_aware(now):
        return timezone.localtime(now).date()
    return now.date()
