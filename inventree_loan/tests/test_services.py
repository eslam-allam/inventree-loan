"""Service-level tests for checkout and return behaviour."""

from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from InvenTree.unit_test import InvenTreeTestCase
from part.models import Part, PartCategory
from stock.models import StockItem, StockLocation
from stock.status_codes import StockStatus

from inventree_loan.models import (
    Loan,
    LoanItem,
    LoanRequest,
    LoanRequestLine,
    LoanRequestStatus,
    LoanStaff,
    LoanStaffRole,
    LoanStatus,
)
from inventree_loan.services.checkout import checkout_request
from inventree_loan.services.returns import return_item


class LoanCheckoutServiceTests(InvenTreeTestCase):
    """End-to-end stock movement for a simple whole-item loan."""

    def setUp(self):
        super().setUp()
        self.desk_user = get_user_model().objects.create_user(
            username="desk-user", password="desk-password"
        )
        LoanStaff.objects.create(user=self.desk_user, role=LoanStaffRole.DESK)

        self.category = PartCategory.objects.create(name="Loan Test Category")
        self.part = Part.objects.create(
            name="Loan Test Part", category=self.category, IPN="LOAN-TEST"
        )
        self.location = StockLocation.objects.create(
            name="Loan Test Shelf", description="Original location"
        )
        self.loan_location = StockLocation.objects.create(
            name="Loan Test On Loan", description="On loan location"
        )
        self.stock_item = StockItem.objects.create(
            part=self.part,
            location=self.location,
            quantity=Decimal("5"),
            status=StockStatus.OK.value,
        )
        self.request = LoanRequest.objects.create(
            requester=self.user,
            status=LoanRequestStatus.APPROVED,
            purpose="Testing",
            needed_by=None,
            return_by=None,
            responsibility_ack=True,
        )
        LoanRequestLine.objects.create(
            request=self.request,
            part=self.part,
            stock_item=self.stock_item,
            quantity=Decimal("2"),
        )

    @patch("inventree_loan.services.requests._loan_location")
    @patch("inventree_loan.services.checkout.get_loan_location")
    @patch("inventree_loan.services.checkout.get_on_loan_status_key")
    @patch("inventree_loan.services.returns.get_loan_location")
    def test_partial_checkout_and_return(
        self, return_location, status_key, checkout_location, request_location
    ):
        status_key.return_value = StockStatus.QUARANTINED.value
        checkout_location.return_value = self.loan_location
        return_location.return_value = self.loan_location
        request_location.return_value = self.loan_location

        loan = checkout_request(self.request, self.desk_user)
        self.assertEqual(loan.status, LoanStatus.ACTIVE)
        self.assertTrue(loan.reference.startswith("LOAN-"))
        self.assertEqual(loan.item_count, 1)

        loan_item = loan.items.get()
        self.assertEqual(loan_item.quantity, Decimal("2"))
        self.assertEqual(loan_item.original_location_id, self.location.pk)

        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantity, Decimal("3"))
        loaned_item = loan_item.stock_item
        loaned_item.refresh_from_db()
        self.assertEqual(loaned_item.quantity, Decimal("2"))
        self.assertEqual(loaned_item.location_id, self.loan_location.pk)
        self.assertEqual(loaned_item.status, StockStatus.QUARANTINED.value)
        self.assertFalse(loaned_item.in_stock)

        self.request.refresh_from_db()
        self.assertEqual(self.request.status, LoanRequestStatus.FULFILLED)

        return_item(loan_item, self.desk_user, quantity=Decimal("1"))
        loan.refresh_from_db()
        self.assertEqual(loan.status, LoanStatus.PARTIALLY_RETURNED)
        loan_item.refresh_from_db()
        self.assertEqual(loan_item.returned_quantity, Decimal("1"))

        return_item(loan_item, self.desk_user, quantity=Decimal("1"))
        loan.refresh_from_db()
        loan_item.refresh_from_db()
        self.assertEqual(loan.status, LoanStatus.RETURNED)
        self.assertIsNotNone(loan.returned_at)
        self.assertIsNotNone(loan_item.returned_at)

        loaned_item.refresh_from_db()
        self.assertEqual(loaned_item.location_id, self.location.pk)
        self.assertEqual(loaned_item.status, StockStatus.OK.value)
        self.assertTrue(loaned_item.in_stock)

    @patch("inventree_loan.services.requests._loan_location")
    @patch("inventree_loan.services.checkout.get_loan_location")
    @patch("inventree_loan.services.checkout.get_on_loan_status_key")
    def test_insufficient_stock_rolls_back(
        self, status_key, checkout_location, request_location
    ):
        status_key.return_value = StockStatus.QUARANTINED.value
        checkout_location.return_value = self.loan_location
        request_location.return_value = self.loan_location

        line = self.request.lines.get()
        line.quantity = Decimal("10")
        line.save()

        with self.assertRaises(ValidationError):
            checkout_request(self.request, self.desk_user)

        self.assertFalse(Loan.objects.filter(request=self.request).exists())
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantity, Decimal("5"))
        self.assertEqual(self.stock_item.location_id, self.location.pk)

    def test_returned_quantity_cannot_exceed_quantity(self):
        item = LoanItem(
            loan=Loan.objects.create(
                borrower=self.user,
                issued_by=self.desk_user,
                due_at=self.request.created,
            ),
            part=self.part,
            stock_item=self.stock_item,
            quantity=Decimal("1"),
            returned_quantity=Decimal("2"),
        )
        with self.assertRaises(ValidationError):
            item.clean()
