"""Serializers for the loan plugin API."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from rest_framework import serializers

from ..models import (
    LoanCustomFieldType,
    LoanRequestCustomField,
    LoanStaffRole,
    ReturnCondition,
)


class RequestCreateSerializer(serializers.Serializer):
    """Input for a new loan request."""

    lines = serializers.ListField(child=serializers.DictField(), allow_empty=False)
    purpose = serializers.CharField(required=False, allow_blank=True, default="")
    needed_by = serializers.DateField(required=False, allow_null=True)
    return_by = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    responsibility_ack = serializers.BooleanField(required=False, default=False)
    signature = serializers.CharField(required=False, allow_blank=True, default="")
    requester_name = serializers.CharField(required=False, allow_blank=True, default="")
    requester_email = serializers.EmailField(required=False, allow_blank=True, default="")


class PublicRequestCreateSerializer(RequestCreateSerializer):
    """Input for an anonymous public loan request."""

    requester_name = serializers.CharField(max_length=150)
    requester_email = serializers.EmailField()
    signature = serializers.CharField(
        required=False, allow_blank=True, default=""
    )
    custom_fields = serializers.JSONField(required=False, default=dict)

    def validate(self, attrs):
        """Enforce the configurable public form field requirements."""
        from ..config import get_public_field_config

        config = get_public_field_config()
        required = {
            "purpose": "purpose",
            "notes": "notes",
        }
        errors = {}
        for field, key in required.items():
            if config.get(key) == "required" and not str(attrs.get(field) or "").strip():
                errors[field] = "This field is required."
        if config.get("pickup_date") == "required" and not attrs.get("needed_by"):
            errors["needed_by"] = "This field is required."
        if config.get("return_date") == "required" and not attrs.get("return_by"):
            errors["return_by"] = "This field is required."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def validate_lines(self, lines):
        """Public request quantities are whole units and never specific stock."""
        for line in lines:
            if line.get("stock_item_id") or line.get("stock_item"):
                raise serializers.ValidationError(
                    "Choose a part; the loan desk assigns the stock item."
                )
            try:
                quantity = Decimal(str(line.get("quantity", 1)))
            except (InvalidOperation, TypeError, ValueError):
                raise serializers.ValidationError("Enter a valid quantity") from None
            if quantity <= 0 or quantity != quantity.to_integral_value():
                raise serializers.ValidationError(
                    "Quantity must be a whole number"
                )
        return lines


class CustomFieldSerializer(serializers.ModelSerializer):
    """Create or update a custom public-form field."""

    field_type_display = serializers.CharField(
        source="get_field_type_display", read_only=True
    )

    class Meta:
        model = LoanRequestCustomField
        fields = [
            "pk",
            "key",
            "label",
            "field_type",
            "field_type_display",
            "help_text",
            "placeholder",
            "required",
            "active",
            "sort_order",
            "options",
        ]

    def validate_key(self, value):
        value = (value or "").strip().lower()
        if self.instance and value and value != self.instance.key:
            raise serializers.ValidationError(
                "The field key cannot be changed after creation."
            )
        if value and not re.fullmatch(r"[a-z][a-z0-9_]*", value):
            raise serializers.ValidationError(
                "Use lowercase letters, numbers and underscores."
            )
        return value

    def validate_options(self, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("Options must be a list.")
        return [str(option).strip() for option in value if str(option).strip()]

    def validate(self, attrs):
        field_type = attrs.get(
            "field_type", getattr(self.instance, "field_type", LoanCustomFieldType.TEXT)
        )
        options = attrs.get(
            "options", getattr(self.instance, "options", []) or []
        )
        if field_type == LoanCustomFieldType.SELECT and not options:
            raise serializers.ValidationError(
                {"options": "Add at least one dropdown option."}
            )
        if field_type != LoanCustomFieldType.SELECT:
            attrs["options"] = []
        return attrs


class DecisionSerializer(serializers.Serializer):
    """Approve or reject a request."""

    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ApprovalLineSerializer(serializers.Serializer):
    """Approved quantity for one request line."""

    line_id = serializers.IntegerField()
    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=5, min_value=0
    )


class ApproveSerializer(DecisionSerializer):
    """Approve some or all request quantities."""

    lines = ApprovalLineSerializer(many=True, required=False, allow_empty=True)


class ReadyForPickupSerializer(serializers.Serializer):
    """Pack a request into a pickup box and mark it ready."""

    name = serializers.CharField(
        required=False, allow_blank=True, max_length=100, default=""
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CheckoutLineSerializer(serializers.Serializer):
    """A line to issue for a walk-in loan."""

    part_id = serializers.IntegerField(required=False)
    stock_item_id = serializers.IntegerField(required=False)
    quantity = serializers.DecimalField(max_digits=15, decimal_places=5, default=1)
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("part_id") and not attrs.get("stock_item_id"):
            raise serializers.ValidationError("Each line requires a part or stock item")
        return attrs


class CheckoutSerializer(serializers.Serializer):
    """Issue an approved request, or create and issue a walk-in loan."""

    request_id = serializers.IntegerField(required=False, allow_null=True)
    borrower_id = serializers.IntegerField(required=False, allow_null=True)
    items = CheckoutLineSerializer(many=True, required=False)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    signature = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("request_id"):
            if not attrs.get("borrower_id"):
                raise serializers.ValidationError(
                    "Provide request_id, or borrower_id plus items"
                )
            if not attrs.get("items"):
                raise serializers.ValidationError("Provide at least one item")
        return attrs


class ReturnLineSerializer(serializers.Serializer):
    """One line to return."""

    item_id = serializers.IntegerField()
    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=5, required=False, allow_null=True
    )
    condition = serializers.ChoiceField(
        choices=ReturnCondition.choices, default=ReturnCondition.GOOD
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    location = serializers.IntegerField(required=False, allow_null=True)


class ReturnSerializer(serializers.Serializer):
    """Return one or more lines."""

    lines = ReturnLineSerializer(many=True, required=False)
    signature = serializers.CharField(required=False, allow_blank=True, default="")


class RenewSerializer(serializers.Serializer):
    """Extend a loan."""

    due_at = serializers.DateTimeField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class ScanSerializer(serializers.Serializer):
    """A barcode scan."""

    barcode = serializers.CharField()


class StaffCreateSerializer(serializers.Serializer):
    """Grant or update a loan staff role."""

    username = serializers.CharField(required=False, allow_blank=True)
    user_id = serializers.IntegerField(required=False)
    role = serializers.ChoiceField(choices=LoanStaffRole.choices, default=LoanStaffRole.APPROVER)
    active = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if not attrs.get("username") and not attrs.get("user_id"):
            raise serializers.ValidationError("Provide username or user_id")
        return attrs


class StaffUpdateSerializer(serializers.Serializer):
    """Update a staff role."""

    role = serializers.ChoiceField(choices=LoanStaffRole.choices, required=False)
    active = serializers.BooleanField(required=False)


class LostSerializer(serializers.Serializer):
    """Mark a loan line lost."""

    notes = serializers.CharField(required=False, allow_blank=True, default="")


class RequestAllocateSerializer(serializers.Serializer):
    """Auto-allocate a request, or add one manual allocation."""

    auto = serializers.BooleanField(default=False)
    clear = serializers.BooleanField(default=False)
    line_id = serializers.IntegerField(required=False)
    stock_item_id = serializers.IntegerField(required=False)
    quantity = serializers.DecimalField(
        max_digits=15, decimal_places=5, required=False, default=1
    )

    def validate(self, attrs):
        if attrs.get("auto") or attrs.get("clear"):
            return attrs
        if not attrs.get("line_id") or not attrs.get("stock_item_id"):
            raise serializers.ValidationError(
                "Provide auto=true, clear=true, or line_id plus stock_item_id"
            )
        return attrs


class PublicRequestLookupSerializer(serializers.Serializer):
    """Look up an anonymous request by reference and email."""

    reference = serializers.CharField(max_length=32)
    email = serializers.EmailField()
