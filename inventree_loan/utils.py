"""Small shared helpers for the loan plugin."""

from __future__ import annotations

from datetime import date

from django.utils import timezone


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
