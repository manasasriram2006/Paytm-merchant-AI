from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class OcrError(RuntimeError):
    status_code = 500


class OcrUnavailableError(OcrError):
    status_code = 503


class OcrProviderError(OcrError):
    status_code = 502


class OcrTimeoutError(OcrError):
    status_code = 504


class OcrExtractionError(OcrError):
    status_code = 422


class OcrProvider(ABC):
    @abstractmethod
    async def extract_invoice(self, content: bytes, filename: str) -> dict[str, Any]:
        raise NotImplementedError

    async def extract_invoice_items(self, content: bytes, filename: str) -> list[dict]:
        invoice = await self.extract_invoice(content, filename)
        return invoice.get("items", [])


class UnconfiguredOcrProvider(OcrProvider):
    async def extract_invoice(self, content: bytes, filename: str) -> dict[str, Any]:
        raise OcrUnavailableError("OCR provider is not configured.")


class MockOcrProvider(OcrProvider):
    async def extract_invoice(self, content: bytes, filename: str) -> dict[str, Any]:
        return {
            "metadata": {
                "invoice_number": {"value": "DEMO-INV-001", "confidence": None},
                "invoice_date": {"value": None, "confidence": None},
                "supplier_name": {"value": "Demo Supplier", "confidence": None},
                "supplier_gstin": {"value": None, "confidence": None},
                "total_amount": {"value": None, "confidence": None},
            },
            "items": [
                {
                    "product_name": {"value": "Amul Milk 500ml", "confidence": None},
                    "quantity": {"value": 24, "confidence": None},
                    "unit_price": {"value": None, "confidence": None},
                    "total_price": {"value": None, "confidence": None},
                    "unit": {"value": None, "confidence": None},
                },
                {
                    "product_name": {"value": "Vim Dishwash Bar", "confidence": None},
                    "quantity": {"value": 12, "confidence": None},
                    "unit_price": {"value": None, "confidence": None},
                    "total_price": {"value": None, "confidence": None},
                    "unit": {"value": None, "confidence": None},
                },
                {
                    "product_name": {"value": "Dove Shampoo 180ml", "confidence": None},
                    "quantity": {"value": 6, "confidence": None},
                    "unit_price": {"value": None, "confidence": None},
                    "total_price": {"value": None, "confidence": None},
                    "unit": {"value": None, "confidence": None},
                },
            ],
        }

    async def extract_invoice_items(self, content: bytes, filename: str) -> list[dict]:
        return [
            {"name": "Amul Milk 500ml", "quantity": 24, "confidence": 0.91},
            {"name": "Vim Dishwash Bar", "quantity": 12, "confidence": 0.87},
            {"name": "Dove Shampoo 180ml", "quantity": 6, "confidence": 0.82},
        ]


def get_ocr_provider(provider_name: str) -> OcrProvider:
    normalized = (provider_name or "").strip().lower()
    if normalized in {"", "none", "disabled", "unconfigured"}:
        return UnconfiguredOcrProvider()
    if normalized == "mock":
        return MockOcrProvider()
    return UnconfiguredOcrProvider()
