"""Serializers for the loan plugin API."""

from __future__ import annotations

from rest_framework import serializers

from ..models import LoanStaffRole, ReturnCondition


class RequestCreateSerializer(serializers.Serializer):
    """Input for a new loan request."""

    lines = serializers.ListField(child=serializers.DictField(), allow_empty=False)
    purpose = serializers.CharField(required=False, allow_blank=True, default="")
    needed_by = serializers.DateField(required=False, allow_null=True)
    return_by = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    contact = serializers.CharField(required=False, allow_blank=True, default="")
    project = serializers.CharField(required=False, allow_blank=True, default="")
    responsibility_ack = serializers.BooleanField(required=False, default=False)


class DecisionSerializer(serializers.Serializer):
    """Approve or reject a request."""

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
