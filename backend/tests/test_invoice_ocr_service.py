from __future__ import annotations

from dataclasses import dataclass, field
from unittest import IsolatedAsyncioTestCase, TestCase, main

from fastapi.testclient import TestClient

from app.main import app, get_invoice_ocr_service
from app.services.invoice_ocr_service import (
    InvoiceOcrService,
    InvoiceReviewStore,
    InvoiceStatus,
    match_product,
    validate_invoice_image,
)
from app.services.ocr import OcrProvider, OcrProviderError, UnconfiguredOcrProvider


PNG_IMAGE = b"\x89PNG\r\n\x1a\n" + b"invoice"


class FakeOcrProvider(OcrProvider):
    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self.result = result or valid_ocr_result()
        self.error = error

    async def extract_invoice(self, content: bytes, filename: str) -> dict:
        if self.error:
            raise self.error
        return self.result


@dataclass
class FakeInventoryService:
    update_calls: int = 0
    confirmed_items: list[dict] = field(default_factory=list)

    def list_items(self) -> list[dict]:
        return [
            {"id": 1, "name": "Britannia Biscuits", "current_stock": 10},
            {"id": 2, "name": "Amul Milk 500ml", "current_stock": 5},
        ]

    def apply_invoice_confirmation(self, items: list[dict], invoice_id: str) -> dict:
        self.update_calls += 1
        confirmed = []
        warnings = []
        for item in items:
            product_id = item.get("product_id") or item.get("matched_product_id")
            if product_id is None:
                warnings.append({"item_id": item.get("item_id"), "status": "requires_product_mapping"})
                confirmed.append({**item, "status": "requires_product_mapping"})
            else:
                confirmed.append({**item, "product_id": product_id, "status": "inventory_updated", "new_stock": 50})
        self.confirmed_items.extend(confirmed)
        return {"status": "updated", "confirmed_items": confirmed, "warnings": warnings}


class BrokenInvoiceService:
    def get_invoice(self, invoice_id: str) -> dict:
        raise RuntimeError("Could not retrieve invoice data.")

    def confirm(self, invoice_id: str, confirmed_items: list[dict]) -> dict:
        raise RuntimeError("Could not persist invoice data.")

    def reject(self, invoice_id: str) -> dict:
        raise RuntimeError("Could not persist invoice data.")


def valid_ocr_result() -> dict:
    return {
        "metadata": {
            "invoice_number": {"value": "INV-1024", "confidence": 0.95},
            "invoice_date": {"value": "2026-08-20", "confidence": 0.92},
            "supplier_name": {"value": "ABC Distributors", "confidence": 0.9},
            "supplier_gstin": {"value": None, "confidence": None},
            "total_amount": {"value": 12500, "confidence": 0.88},
        },
        "items": [
            {
                "product_name": {"value": "Britania Bisct", "confidence": 0.7},
                "quantity": {"value": 40, "confidence": 0.96},
                "unit_price": {"value": 25, "confidence": 0.9},
                "total_price": {"value": 1000, "confidence": 0.9},
                "unit": {"value": "pcs", "confidence": None},
            }
        ],
    }


def make_service(provider: OcrProvider | None = None, inventory: FakeInventoryService | None = None) -> InvoiceOcrService:
    return InvoiceOcrService(provider or FakeOcrProvider(), inventory or FakeInventoryService(), InvoiceReviewStore())


class InvoiceValidationTests(TestCase):
    def test_valid_invoice_image_accepts_common_formats(self) -> None:
        self.assertEqual(validate_invoice_image("invoice.png", "image/png", PNG_IMAGE)["content_type"], "image/png")
        self.assertEqual(validate_invoice_image("invoice.jpg", "image/jpeg", b"\xff\xd8\xffdata")["content_type"], "image/jpeg")
        self.assertEqual(validate_invoice_image("invoice.webp", "image/webp", b"RIFF1234WEBPdata")["content_type"], "image/webp")

    def test_invalid_empty_oversized_unsupported_and_malformed_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            validate_invoice_image("invoice.pdf", "application/pdf", b"%PDF")
        with self.assertRaisesRegex(ValueError, "empty"):
            validate_invoice_image("invoice.png", "image/png", b"")
        with self.assertRaisesRegex(ValueError, "too large"):
            validate_invoice_image("invoice.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "malformed"):
            validate_invoice_image("invoice.png", "image/png", b"not-a-real-png")

    def test_product_matching_suggests_without_replacing_original_name(self) -> None:
        match = match_product("Britania Bisct", [{"id": 1, "name": "Britannia Biscuits"}])

        self.assertIsNotNone(match)
        self.assertEqual(match["name"], "Britannia Biscuits")
        self.assertEqual(match["extracted_name"], "Britania Bisct")

    def test_product_matching_returns_null_when_not_safe(self) -> None:
        self.assertIsNone(match_product("Cooking Oil", [{"id": 1, "name": "Britannia Biscuits"}]))


class InvoiceOcrServiceTests(IsolatedAsyncioTestCase):
    async def test_successful_extraction_missing_fields_and_low_confidence_require_review(self) -> None:
        service = make_service()

        invoice = await service.scan("invoice.png", "image/png", PNG_IMAGE)

        self.assertEqual(invoice["status"], InvoiceStatus.REVIEW_REQUIRED)
        self.assertEqual(invoice["metadata"]["supplier_gstin"]["value"], None)
        self.assertTrue(invoice["metadata"]["supplier_gstin"]["requires_review"] is False)
        self.assertEqual(invoice["items"][0]["product_name"], "Britania Bisct")
        self.assertEqual(invoice["items"][0]["matched_product"]["name"], "Britannia Biscuits")
        self.assertIn("low_confidence_product_name", invoice["items"][0]["review_reasons"])

    async def test_unmatched_product_is_marked_for_mapping(self) -> None:
        result = valid_ocr_result()
        result["items"][0]["product_name"]["value"] = "Unknown Fancy Item"
        invoice = await make_service(FakeOcrProvider(result)).scan("invoice.png", "image/png", PNG_IMAGE)

        self.assertIsNone(invoice["items"][0]["matched_product"])
        self.assertIn("requires_product_mapping", invoice["items"][0]["review_reasons"])

    async def test_invalid_date_and_numeric_fields_return_validation_warnings(self) -> None:
        result = valid_ocr_result()
        result["metadata"]["invoice_date"]["value"] = "20/08/2026"
        result["items"][0]["quantity"]["value"] = "ten"
        result["items"][0]["unit_price"]["value"] = -5

        invoice = await make_service(FakeOcrProvider(result)).scan("invoice.png", "image/png", PNG_IMAGE)

        self.assertTrue(invoice["metadata"]["invoice_date"]["requires_review"])
        self.assertIn("invalid_quantity", invoice["items"][0]["review_reasons"])
        self.assertIn("invalid_unit_price", invoice["items"][0]["review_reasons"])
        self.assertTrue(any(warning.get("field") == "invoice_date" for warning in invoice["warnings"] if isinstance(warning, dict)))

    async def test_no_inventory_update_before_confirmation_then_confirmation_updates(self) -> None:
        inventory = FakeInventoryService()
        service = make_service(inventory=inventory)
        invoice = await service.scan("invoice.png", "image/png", PNG_IMAGE)

        self.assertEqual(inventory.update_calls, 0)

        confirmed = service.confirm(
            invoice["invoice_id"],
            [{"item_id": "line_1", "product_id": 1, "product_name": "Britania Bisct", "quantity": 40}],
        )

        self.assertEqual(confirmed["status"], InvoiceStatus.CONFIRMED)
        self.assertEqual(inventory.update_calls, 1)
        self.assertEqual(confirmed["confirmed_items"][0]["status"], "inventory_updated")

    async def test_rejection_does_not_update_inventory(self) -> None:
        inventory = FakeInventoryService()
        service = make_service(inventory=inventory)
        invoice = await service.scan("invoice.png", "image/png", PNG_IMAGE)

        rejected = service.reject(invoice["invoice_id"])

        self.assertEqual(rejected["status"], InvoiceStatus.REJECTED)
        self.assertEqual(inventory.update_calls, 0)

    async def test_confirmation_requires_items(self) -> None:
        service = make_service()
        invoice = await service.scan("invoice.png", "image/png", PNG_IMAGE)

        with self.assertRaisesRegex(ValueError, "At least one"):
            service.confirm(invoice["invoice_id"], [])


class InvoiceApiTests(TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_scan_get_confirm_and_reject_endpoints(self) -> None:
        service = make_service()
        app.dependency_overrides[get_invoice_ocr_service] = lambda: service
        client = TestClient(app)

        scan = client.post("/api/invoices/scan", files={"file": ("invoice.png", PNG_IMAGE, "image/png")})
        self.assertEqual(scan.status_code, 200)
        invoice_id = scan.json()["invoice_id"]

        fetched = client.get(f"/api/invoices/{invoice_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["status"], "REVIEW_REQUIRED")

        confirm = client.post(
            f"/api/invoices/{invoice_id}/confirm",
            json={"items": [{"item_id": "line_1", "product_id": 1, "product_name": "Britania Bisct", "quantity": 40}]},
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertEqual(confirm.json()["status"], "CONFIRMED")

        second = make_service()
        app.dependency_overrides[get_invoice_ocr_service] = lambda: second
        scan_reject = client.post("/api/invoices/scan", files={"file": ("invoice.png", PNG_IMAGE, "image/png")})
        rejected = client.post(f"/api/invoices/{scan_reject.json()['invoice_id']}/reject")
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["status"], "REJECTED")

    def test_scan_invalid_file_and_provider_errors_are_clean_json(self) -> None:
        client = TestClient(app)
        app.dependency_overrides[get_invoice_ocr_service] = lambda: make_service()

        invalid = client.post("/api/invoices/scan", files={"file": ("invoice.pdf", b"%PDF", "application/pdf")})
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("detail", invalid.json())

        app.dependency_overrides[get_invoice_ocr_service] = lambda: make_service(UnconfiguredOcrProvider())
        unavailable = client.post("/api/invoices/scan", files={"file": ("invoice.png", PNG_IMAGE, "image/png")})
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.json()["detail"], "OCR provider is not configured.")

        app.dependency_overrides[get_invoice_ocr_service] = lambda: make_service(FakeOcrProvider(error=OcrProviderError("OCR request failed.")))
        failed = client.post("/api/invoices/scan", files={"file": ("invoice.png", PNG_IMAGE, "image/png")})
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(failed.json()["detail"], "OCR request failed.")

    def test_database_failures_return_clean_json(self) -> None:
        client = TestClient(app)
        app.dependency_overrides[get_invoice_ocr_service] = BrokenInvoiceService

        fetched = client.get("/api/invoices/inv_1")
        self.assertEqual(fetched.status_code, 500)
        self.assertEqual(fetched.json()["detail"], "Could not retrieve invoice data.")

        confirmed = client.post("/api/invoices/inv_1/confirm", json={"items": [{"product_id": 1, "quantity": 1}]})
        self.assertEqual(confirmed.status_code, 500)
        self.assertEqual(confirmed.json()["detail"], "Could not persist invoice data.")


if __name__ == "__main__":
    main()
