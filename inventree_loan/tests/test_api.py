"""API visibility and permission tests."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from InvenTree.unit_test import InvenTreeAPITestCase
from part.models import Part, PartCategory
from stock.models import StockItem, StockLocation
from stock.status_codes import StockStatus

TEST_SIGNATURE = "data:image/png;base64,AAAA"

from inventree_loan.services.requests import create_request

from inventree_loan.models import (
    Loan,
    LoanItem,
    LoanRequest,
    LoanRequestLine,
    LoanRequestStatus,
    LoanStaff,
    LoanStaffRole,
)


class LoanAPIPermissionTests(InvenTreeAPITestCase):
    """Check object-level visibility and approval permissions."""

    def setUp(self):
        super().setUp()
        self.other = get_user_model().objects.create_user(
            username="other-user", password="other-password"
        )
        self.approver = get_user_model().objects.create_user(
            username="approver-user", password="approver-password"
        )
        LoanStaff.objects.create(user=self.approver, role=LoanStaffRole.APPROVER)

        self.category = PartCategory.objects.create(name="API Loan Category")
        self.part = Part.objects.create(
            name="API Loan Part", category=self.category, IPN="API-LOAN"
        )
        self.location = StockLocation.objects.create(name="API Loan Shelf")
        StockItem.objects.create(
            part=self.part,
            location=self.location,
            quantity=Decimal("10"),
            status=StockStatus.OK.value,
        )
        self.request = LoanRequest.objects.create(
            requester=self.user,
            status=LoanRequestStatus.PENDING,
            purpose="API testing",
            responsibility_ack=True,
        )
        LoanRequestLine.objects.create(
            request=self.request,
            part=self.part,
            quantity=Decimal("1"),
        )

    def test_requester_can_create_request(self):
        response = self.client.post(
            "/plugin/loan/api/requests/",
            {
                "lines": [{"part_id": self.part.pk, "quantity": 2}],
                "purpose": "Need it for a demo",
                "needed_by": "2030-01-01",
                "return_by": "2030-01-08",
                "responsibility_ack": True,
                "signature": TEST_SIGNATURE,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["reference"].startswith("REQ-"))
        self.assertEqual(response.data["status"], LoanRequestStatus.PENDING)

    def test_requester_cannot_view_another_users_request(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.get(f"/plugin/loan/api/requests/{self.request.pk}/")
        self.assertEqual(response.status_code, 404)

    def test_requester_cannot_approve(self):
        self.client.force_authenticate(user=self.other)
        response = self.client.post(
            f"/plugin/loan/api/requests/{self.request.pk}/approve/",
            {"notes": "should fail"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, LoanRequestStatus.PENDING)

    def test_approver_can_approve(self):
        self.client.force_authenticate(user=self.approver)
        response = self.client.post(
            f"/plugin/loan/api/requests/{self.request.pk}/approve/",
            {"notes": "Approved for demo"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.request.refresh_from_db()
        self.assertEqual(self.request.status, LoanRequestStatus.APPROVED)
        self.assertEqual(self.request.decision_notes, "Approved for demo")
        self.assertEqual(self.request.decided_by, self.approver)

    def test_anonymous_request_tracking_and_receipt(self):
        created = create_request(
            None,
            [{"part_id": self.part.pk, "quantity": 1}],
            requester_name="Anonymous Requester",
            requester_email="anon@example.com",
            purpose="Tracking test",
            responsibility_ack=True,
            signature=TEST_SIGNATURE,
            allow_anonymous=True,
        )
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/plugin/loan/request/").status_code, 200)
        self.assertEqual(
            self.client.get(f"/plugin/loan/track/{created.public_token}/").status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/plugin/loan/track/{created.public_token}/receipt/"
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                f"/plugin/loan/track/{created.public_token}/qr.svg"
            ).status_code,
            200,
        )
        lookup = self.client.post(
            "/plugin/loan/api/public/requests/lookup/",
            {"reference": created.reference, "email": "anon@example.com"},
            format="json",
        )
        self.assertEqual(lookup.status_code, 200)
        wrong = self.client.post(
            "/plugin/loan/api/public/requests/lookup/",
            {"reference": created.reference, "email": "wrong@example.com"},
            format="json",
        )
        self.assertEqual(wrong.status_code, 404)

    def test_public_request_rejects_fractional_quantity(self):
        from inventree_loan.api.serializers import PublicRequestCreateSerializer

        serializer = PublicRequestCreateSerializer(
            data={
                "requester_name": "Anon",
                "requester_email": "anon@example.com",
                "signature": TEST_SIGNATURE,
                "purpose": "Fraction test",
                "responsibility_ack": True,
                "lines": [{"part_id": self.part.pk, "quantity": 1.5}],
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("lines", serializer.errors)

    def test_request_list_filters_and_paginates(self):
        self.client.force_authenticate(user=self.approver)
        response = self.client.get("/plugin/loan/api/requests/?limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total"], 1)
        self.assertEqual(response.data["limit"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["item_count"], 1)
        self.assertEqual(row["total_quantity"], 1.0)
        self.assertNotIn("lines", row)

        response = self.client.get(
            "/plugin/loan/api/requests/?search=API%20Loan%20Part"
        )
        self.assertEqual(response.data["total"], 1)

        response = self.client.get("/plugin/loan/api/requests/?status=approved")
        self.assertEqual(response.data["total"], 0)

        response = self.client.get(
            "/plugin/loan/api/requests/?allocation=incomplete"
        )
        self.assertEqual(response.data["total"], 1)

    def test_request_list_query_count_is_constant(self):
        for index in range(8):
            request = LoanRequest.objects.create(
                requester=self.user,
                status=LoanRequestStatus.PENDING,
                purpose=f"Paging test {index}",
                responsibility_ack=True,
            )
            LoanRequestLine.objects.create(
                request=request, part=self.part, quantity=Decimal("1")
            )
        self.client.force_authenticate(user=self.approver)
        with CaptureQueriesContext(connection) as context:
            response = self.client.get("/plugin/loan/api/requests/?limit=25")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total"], 9)
        self.assertLess(len(context.captured_queries), 20)

    def test_loan_list_query_count_is_constant(self):
        for index in range(8):
            loan = Loan.objects.create(
                borrower=self.user,
                due_at=timezone.now() + timedelta(days=index + 1),
                status="active",
            )
            LoanItem.objects.create(
                loan=loan, part=self.part, quantity=Decimal("1")
            )
        self.client.force_authenticate(user=self.approver)
        with CaptureQueriesContext(connection) as context:
            response = self.client.get("/plugin/loan/api/loans/?limit=25")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total"], 8)
        self.assertLess(len(context.captured_queries), 20)

    def test_loan_list_filters_and_paginates(self):
        loan = Loan.objects.create(
            borrower=self.user,
            due_at=timezone.now() - timedelta(days=2),
            status="active",
        )
        LoanItem.objects.create(loan=loan, part=self.part, quantity=Decimal("2"))
        LoanItem.objects.create(loan=loan, part=self.part, quantity=Decimal("1"))

        self.client.force_authenticate(user=self.approver)
        response = self.client.get("/plugin/loan/api/loans/?limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["total"], 1)
        row = response.data["results"][0]
        self.assertEqual(row["item_count"], 2)
        self.assertEqual(row["total_quantity"], 3.0)
        self.assertEqual(row["remaining_quantity"], 3.0)
        self.assertNotIn("items", row)

        response = self.client.get("/plugin/loan/api/loans/?status=overdue")
        self.assertEqual(response.data["total"], 1)

        response = self.client.get(
            "/plugin/loan/api/loans/?search=API%20Loan%20Part"
        )
        self.assertEqual(response.data["total"], 1)

    def test_catalog_is_requester_safe(self):
        response = self.client.get("/plugin/loan/api/catalog/?search=API")
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertTrue(results)
        self.assertEqual(results[0]["pk"], self.part.pk)
        self.assertNotIn("purchase_price", results[0])

    def test_scan_unknown_barcode_returns_error_payload(self):
        response = self.client.post(
            "/plugin/loan/api/scan/",
            {"barcode": "definitely-not-a-known-barcode"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["success"])
