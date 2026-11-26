"""Validation and display helpers for custom public-form fields."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _

from ..models import LoanCustomFieldType, LoanRequestCustomField


def public_custom_fields():
    """Return active custom field definitions in display order."""
    return LoanRequestCustomField.objects.filter(active=True)


def _plain_value(value) -> str:
    return "" if value is None else str(value).strip()


def normalize_custom_fields(raw, definitions=None) -> dict:
    """Validate and normalize submitted custom-field values."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValidationError({"custom_fields": _("Invalid custom fields")})

    definitions = (
        list(public_custom_fields()) if definitions is None else list(definitions)
    )
    cleaned = {}
    errors = {}

    for definition in definitions:
        key = definition.key
        value = raw.get(key)
        field_type = definition.field_type

        if field_type == LoanCustomFieldType.CHECKBOX:
            if isinstance(value, str):
                value = value.strip().lower() in {"1", "true", "on", "yes"}
            else:
                value = bool(value)
            if definition.required and not value:
                errors[key] = _("This field is required.")
            cleaned[key] = value
            continue

        text = _plain_value(value)

        if field_type == LoanCustomFieldType.NUMBER and text:
            try:
                text = str(Decimal(text))
            except (InvalidOperation, TypeError, ValueError):
                errors[key] = _("Enter a valid number.")
                continue
        elif field_type == LoanCustomFieldType.EMAIL and text:
            try:
                validate_email(text)
            except Exception:
                errors[key] = _("Enter a valid email address.")
                continue
        elif field_type == LoanCustomFieldType.DATE and text:
            parsed = parse_date(text)
            if parsed is None:
                errors[key] = _("Enter a valid date.")
                continue
            text = parsed.isoformat()
        elif field_type == LoanCustomFieldType.SELECT and text:
            options = [str(option).strip() for option in (definition.options or [])]
            if text not in options:
                errors[key] = _("Choose one of the available options.")
                continue

        if definition.required and not text:
            errors[key] = _("This field is required.")
            continue
        cleaned[key] = text

    if errors:
        labels = {definition.key: definition.label for definition in definitions}
        messages = [
            f"{labels.get(key, key)}: {message}"
            for key, message in errors.items()
        ]
        raise ValidationError({"custom_fields": messages})
    return cleaned


def custom_field_values(loan_request, include_inactive: bool = True) -> list[dict]:
    """Return submitted custom field values with labels and display values."""
    stored = loan_request.custom_fields or {}
    if not isinstance(stored, dict):
        return []

    definitions = list(LoanRequestCustomField.objects.all())
    definitions_by_key = {definition.key: definition for definition in definitions}
    results = []
    seen = set()

    for definition in definitions:
        if definition.key not in stored:
            continue
        if not include_inactive and not definition.active:
            continue
        value = stored[definition.key]
        if definition.field_type == LoanCustomFieldType.CHECKBOX:
            if not value:
                continue
            display = "Yes"
        else:
            if value in (None, ""):
                continue
            display = str(value)
        results.append(
            {
                "key": definition.key,
                "label": definition.label,
                "field_type": definition.field_type,
                "value": value,
                "display": display,
            }
        )
        seen.add(definition.key)

    for key in sorted(set(stored) - seen):
        value = stored[key]
        if value in (None, ""):
            continue
        results.append(
            {
                "key": key,
                "label": key,
                "field_type": LoanCustomFieldType.TEXT,
                "value": value,
                "display": "" if value in (None, "") else str(value),
            }
        )
    return results
