from __future__ import annotations

from abc import ABC, abstractmethod


class OcrProvider(ABC):
    @abstractmethod
    async def extract_invoice_items(self, content: bytes, filename: str) -> list[dict]:
        raise NotImplementedError


class MockOcrProvider(OcrProvider):
    async def extract_invoice_items(self, content: bytes, filename: str) -> list[dict]:
        return [
            {"name": "Amul Milk 500ml", "quantity": 24, "confidence": 0.91},
            {"name": "Vim Dishwash Bar", "quantity": 12, "confidence": 0.87},
            {"name": "Dove Shampoo 180ml", "quantity": 6, "confidence": 0.82},
        ]


def get_ocr_provider(provider_name: str) -> OcrProvider:
    if provider_name != "mock":
        return MockOcrProvider()
    return MockOcrProvider()
