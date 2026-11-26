"""API visibility and permission tests."""

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from InvenTree.unit_test import InvenTreeAPITestCase
from part.models import Part, PartCategory
from stock.models import StockItem, StockLocation
from stock.status_codes import StockStatus

TEST_SIGNATURE = "data:image/png;base64,AAAA"

from inventree_loan.services.requests import (
    catalog_categories,
    catalog_part_count,
    create_request,
)

from inventree_loan.models import (
    Loan,
    LoanItem,
    LoanRequest,
    LoanRequestCustomField,
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

    def test_ready_for_pickup_flow(self):
        self.client.force_authenticate(user=self.approver)
        response = self.client.post(
            f"/plugin/loan/api/requests/{self.request.pk}/approve/",
            {"notes": "Approved"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.request.refresh_from_db()
        self.assertEqual(self.request.pickup.status, "packing")

        response = self.client.post(
            f"/plugin/loan/api/requests/{self.request.pk}/ready/",
            {"name": "Blue box"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            f"/plugin/loan/api/requests/{self.request.pk}/allocate/",
            {"auto": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_fully_allocated"])

        with patch(
            "inventree_loan.services.pickups.notify_request_ready"
        ) as notify_ready:
            response = self.client.post(
                f"/plugin/loan/api/requests/{self.request.pk}/ready/",
                {"name": "Blue box", "notes": "Top shelf"},
                format="json",
            )
        self.assertTrue(notify_ready.called)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "ready_for_pickup")
        pickup = response.data["pickup"]
        self.assertEqual(pickup["name"], "Blue box")
        self.assertEqual(pickup["status"], "ready")
        self.assertTrue(pickup["reference"].startswith("BOX-"))

        self.client.force_login(self.approver)
        label = self.client.get(pickup["label_url"])
        self.assertEqual(label.status_code, 200)
        self.assertContains(label, self.request.reference)
        self.assertContains(label, pickup["reference"])

        qr = self.client.get(pickup["qr_url"])
        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr["Content-Type"], "image/svg+xml")

        sheet = self.client.get(pickup["return_sheet_url"])
        self.assertEqual(sheet.status_code, 200)
        self.assertContains(sheet, pickup["reference"])
        self.assertContains(sheet, self.request.reference)

        from inventree_loan.models import LoanPickup
        from inventree_loan.models import LoanRequestAllocation

        allocation = LoanRequestAllocation.objects.filter(
            line__request=self.request
        ).first()
        item_qr = self.client.get(
            reverse(
                "plugin:loan:pickup_item_qr",
                args=[pickup["pk"], allocation.stock_item_id],
            )
        )
        self.assertEqual(item_qr.status_code, 200)
        self.assertEqual(item_qr["Content-Type"], "image/svg+xml")

        from inventree_loan.services.barcode import pickup_payload, resolve_barcode

        scanned = resolve_barcode(
            self.approver,
            pickup_payload(LoanPickup.objects.get(pk=pickup["pk"])),
        )
        self.assertEqual(scanned["type"], "pickup")
        self.assertEqual(scanned["data"]["request_pk"], self.request.pk)

        request_scan = resolve_barcode(
            self.approver, self.request.reference
        )
        self.assertEqual(request_scan["type"], "request")
        self.assertEqual(request_scan["data"]["pk"], self.request.pk)

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

    def test_public_request_rejects_specific_stock(self):
        from inventree_loan.api.serializers import PublicRequestCreateSerializer

        serializer = PublicRequestCreateSerializer(
            data={
                "requester_name": "Anon",
                "requester_email": "anon@example.com",
                "signature": TEST_SIGNATURE,
                "purpose": "Specific stock test",
                "responsibility_ack": True,
                "lines": [
                    {
                        "part_id": self.part.pk,
                        "stock_item_id": 999999,
                        "quantity": 1,
                    }
                ],
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("lines", serializer.errors)

    def test_create_request_rejects_specific_stock(self):
        with self.assertRaises(ValidationError):
            create_request(
                self.user,
                [
                    {
                        "part_id": self.part.pk,
                        "stock_item_id": 1,
                        "quantity": 1,
                    }
                ],
                purpose="Specific stock test",
                responsibility_ack=True,
                signature=TEST_SIGNATURE,
            )

    def test_public_request_slug_setting(self):
        def fake_setting(key, default=None):
            if key == "PUBLIC_REQUEST_SLUG":
                return "borrow"
            return default

        with patch("inventree_loan.config.get_setting", side_effect=fake_setting):
            response = self.client.get("/plugin/loan/borrow/")
            self.assertEqual(response.status_code, 200)
            legacy = self.client.get("/plugin/loan/request/")
            self.assertEqual(legacy.status_code, 302)
            self.assertIn("/plugin/loan/borrow/", legacy["Location"])

    def test_public_form_fields_can_be_hidden(self):
        def fake_setting(key, default=None):
            if key == "PUBLIC_FIELD_PHONE":
                return "hidden"
            if key == "PUBLIC_FIELD_PURPOSE":
                return "hidden"
            return default

        with patch("inventree_loan.config.get_setting", side_effect=fake_setting):
            response = self.client.get("/plugin/loan/request/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="requester_phone"')
        self.assertNotContains(response, 'id="purpose"')
        self.assertContains(response, 'id="requester_name"')

    def test_public_form_optional_purpose_can_be_blank(self):
        def fake_setting(key, default=None):
            if key == "PUBLIC_FIELD_PURPOSE":
                return "hidden"
            return default

        with patch("inventree_loan.config.get_setting", side_effect=fake_setting):
            response = self.client.post(
                "/plugin/loan/api/public/requests/",
                {
                    "requester_name": "Anon",
                    "requester_email": "anon@example.com",
                    "signature": TEST_SIGNATURE,
                    "responsibility_ack": True,
                    "lines": [{"part_id": self.part.pk, "quantity": 1}],
                },
                format="json",
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], LoanRequestStatus.PENDING)

    def test_public_form_required_field_setting(self):
        from inventree_loan.api.serializers import PublicRequestCreateSerializer

        def fake_setting(key, default=None):
            if key == "PUBLIC_FIELD_PHONE":
                return "required"
            return default

        with patch("inventree_loan.config.get_setting", side_effect=fake_setting):
            serializer = PublicRequestCreateSerializer(
                data={
                    "requester_name": "Anon",
                    "requester_email": "anon@example.com",
                    "purpose": "Test",
                    "responsibility_ack": True,
                    "signature": TEST_SIGNATURE,
                    "lines": [{"part_id": self.part.pk, "quantity": 1}],
                }
            )
            self.assertFalse(serializer.is_valid())
        self.assertIn("requester_phone", serializer.errors)

    def test_public_part_detail_hides_stock_items(self):
        response = self.client.get(
            f"/plugin/loan/api/public/catalog/{self.part.pk}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("stock_items", response.data)

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

    def test_public_custom_field_is_rendered_and_stored(self):
        LoanRequestCustomField.objects.create(
            key="cost_center",
            label="Cost center",
            field_type="text",
            required=True,
        )
        page = self.client.get("/plugin/loan/request/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'data-custom-field="cost_center"')
        self.assertContains(page, "Cost center")

        base_payload = {
            "requester_name": "Anon",
            "requester_email": "anon@example.com",
            "purpose": "Custom field test",
            "responsibility_ack": True,
            "signature": TEST_SIGNATURE,
            "lines": [{"part_id": self.part.pk, "quantity": 1}],
        }
        missing = self.client.post(
            "/plugin/loan/api/public/requests/", base_payload, format="json"
        )
        self.assertEqual(missing.status_code, 400)
        self.assertIn("custom_fields", missing.data)

        created = self.client.post(
            "/plugin/loan/api/public/requests/",
            {**base_payload, "custom_fields": {"cost_center": "CC-42"}},
            format="json",
        )
        self.assertEqual(created.status_code, 201)
        loan_request = LoanRequest.objects.get(reference=created.data["reference"])
        self.assertEqual(loan_request.custom_fields, {"cost_center": "CC-42"})

        detail = self.client.get(
            f"/plugin/loan/api/public/requests/{loan_request.public_token}/"
        )
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["custom_fields"][0]["label"], "Cost center")
        self.assertEqual(detail.data["custom_fields"][0]["display"], "CC-42")

        receipt = self.client.get(
            f"/plugin/loan/track/{loan_request.public_token}/receipt/"
        )
        self.assertEqual(receipt.status_code, 200)
        self.assertContains(receipt, "CC-42")

    def test_custom_field_crud_requires_admin(self):
        admin_user = get_user_model().objects.create_user(
            username="field-admin", password="field-admin"
        )
        LoanStaff.objects.create(user=admin_user, role=LoanStaffRole.ADMIN)
        self.client.force_authenticate(user=admin_user)
        response = self.client.post(
            "/plugin/loan/api/custom-fields/",
            {
                "label": "Supervisor",
                "field_type": "select",
                "required": True,
                "options": ["Alice", "Bob"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        field_id = response.data["pk"]
        self.assertTrue(response.data["key"].startswith("supervisor"))

        response = self.client.patch(
            f"/plugin/loan/api/custom-fields/{field_id}/",
            {"label": "Approving supervisor", "options": ["Alice", "Bob", "Cara"]},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["label"], "Approving supervisor")

        response = self.client.delete(
            f"/plugin/loan/api/custom-fields/{field_id}/"
        )
        self.assertEqual(response.status_code, 204)
        self.assertFalse(LoanRequestCustomField.objects.get(pk=field_id).active)

    def test_custom_fields_are_exported_to_csv(self):
        LoanRequestCustomField.objects.create(
            key="cost_center", label="Cost center", field_type="text"
        )
        self.request.custom_fields = {"cost_center": "CC-99"}
        self.request.save(update_fields=["custom_fields"])
        self.client.force_authenticate(user=self.approver)
        response = self.client.get("/plugin/loan/api/export/requests.csv")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Cost center", content)
        self.assertIn("CC-99", content)

    def test_catalog_category_counts_include_children(self):
        child = PartCategory.objects.create(
            name="API Loan Child", parent=self.category
        )
        Part.objects.create(name="Child Loan Part", category=child)
        categories = {item["pk"]: item for item in catalog_categories()}
        self.assertEqual(categories[self.category.pk]["part_count"], 2)
        self.assertEqual(categories[child.pk]["part_count"], 1)
        self.assertTrue(categories[self.category.pk]["has_children"])
        self.assertGreaterEqual(catalog_part_count(), 2)

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
