from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any
from uuid import uuid4

from .inventory_service import InventoryService
from .ocr import OcrExtractionError, OcrProvider


MAX_INVOICE_IMAGE_BYTES = 5 * 1024 * 1024
SUPPORTED_IMAGE_TYPES = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
}
LOW_CONFIDENCE_THRESHOLD = 0.75
PRODUCT_MATCH_THRESHOLD = 0.72


class InvoiceStatus(StrEnum):
    PROCESSING = "PROCESSING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class InvoiceNotFoundError(ValueError):
    pass


@dataclass
class InvoiceReviewStore:
    invoices: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, invoice: dict[str, Any]) -> dict[str, Any]:
        self.invoices[invoice["invoice_id"]] = invoice
        return invoice

    def get(self, invoice_id: str) -> dict[str, Any]:
        invoice = self.invoices.get(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError(f"Invoice not found: {invoice_id}")
        return invoice


@dataclass
class InvoiceOcrService:
    provider: OcrProvider
    inventory_service: InventoryService
    store: InvoiceReviewStore

    async def scan(self, filename: str | None, content_type: str | None, content: bytes) -> dict[str, Any]:
        image = validate_invoice_image(filename, content_type, content)
        invoice_id = f"inv_{uuid4().hex}"
        try:
            raw_invoice = await self.provider.extract_invoice(content, image["filename"])
            invoice = self._normalize_invoice(invoice_id, image["filename"], raw_invoice)
        except OcrExtractionError:
            invoice = {
                "invoice_id": invoice_id,
                "filename": image["filename"],
                "status": InvoiceStatus.FAILED,
                "processing_status": "FAILED",
                "metadata": _empty_metadata(),
                "items": [],
                "warnings": ["OCR returned an unreadable or empty invoice."],
            }
            self.store.save(invoice)
            raise
        return self.store.save(invoice)

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        return self.store.get(invoice_id)

    def reject(self, invoice_id: str) -> dict[str, Any]:
        invoice = self.store.get(invoice_id)
        if invoice["status"] == InvoiceStatus.CONFIRMED:
            raise ValueError("Confirmed invoices cannot be rejected.")
        invoice["status"] = InvoiceStatus.REJECTED
        invoice["processing_status"] = "REJECTED"
        invoice["inventory_update_status"] = "not_updated"
        return self.store.save(invoice)

    def confirm(self, invoice_id: str, confirmed_items: list[dict[str, Any]]) -> dict[str, Any]:
        invoice = self.store.get(invoice_id)
        if invoice["status"] != InvoiceStatus.REVIEW_REQUIRED:
            raise ValueError("Only REVIEW_REQUIRED invoices can be confirmed.")

        updates = self.inventory_service.apply_invoice_confirmation(confirmed_items, invoice_id)
        invoice["status"] = InvoiceStatus.CONFIRMED
        invoice["processing_status"] = "CONFIRMED"
        invoice["confirmed_items"] = updates["confirmed_items"]
        invoice["inventory_update_status"] = updates["status"]
        invoice["warnings"] = [*invoice.get("warnings", []), *updates["warnings"]]
        return self.store.save(invoice)

    def _normalize_invoice(self, invoice_id: str, filename: str, raw_invoice: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw_invoice, dict):
            raise OcrExtractionError("OCR result could not be read.")
        raw_items = raw_invoice.get("items") or []
        if not raw_items:
            raise OcrExtractionError("OCR result did not contain invoice items.")

        products = self.inventory_service.list_items()
        items = [self._normalize_item(index, item, products) for index, item in enumerate(raw_items, start=1)]
        return {
            "invoice_id": invoice_id,
            "filename": filename,
            "status": InvoiceStatus.REVIEW_REQUIRED,
            "processing_status": "REVIEW_REQUIRED",
            "metadata": _normalize_metadata(raw_invoice.get("metadata") or {}),
            "items": items,
            "warnings": _invoice_warnings(items),
        }

    @staticmethod
    def _normalize_item(index: int, raw_item: dict[str, Any], products: list[dict[str, Any]]) -> dict[str, Any]:
        product_name = _field(raw_item, "product_name", aliases=("name",))
        quantity = _field(raw_item, "quantity")
        unit_price = _field(raw_item, "unit_price")
        total_price = _field(raw_item, "total_price")
        unit = _field(raw_item, "unit")
        matched_product = match_product(product_name["value"], products)
        review_reasons = []
        if product_name["value"] is None:
            review_reasons.append("missing_product_name")
        if quantity["value"] is None:
            review_reasons.append("missing_quantity")
        for key, field_value in {
            "product_name": product_name,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": total_price,
            "unit": unit,
        }.items():
            if _is_low_confidence(field_value["confidence"]):
                review_reasons.append(f"low_confidence_{key}")
        if matched_product is None:
            review_reasons.append("requires_product_mapping")
        return {
            "item_id": f"line_{index}",
            "product_name": product_name["value"],
            "product_name_confidence": product_name["confidence"],
            "quantity": _positive_number_or_none(quantity["value"]),
            "quantity_confidence": quantity["confidence"],
            "unit_price": _positive_number_or_none(unit_price["value"]),
            "unit_price_confidence": unit_price["confidence"],
            "total_price": _positive_number_or_none(total_price["value"]),
            "total_price_confidence": total_price["confidence"],
            "unit": unit["value"],
            "unit_confidence": unit["confidence"],
            "matched_product": matched_product,
            "requires_review": bool(review_reasons),
            "review_reasons": review_reasons,
        }


def validate_invoice_image(filename: str | None, content_type: str | None, content: bytes) -> dict[str, str]:
    clean_filename = filename or "invoice"
    normalized_type = (content_type or "").split(";")[0].strip().lower()
    suffix = f".{clean_filename.rsplit('.', 1)[-1].lower()}" if "." in clean_filename else ""
    if normalized_type not in SUPPORTED_IMAGE_TYPES or suffix not in SUPPORTED_IMAGE_TYPES[normalized_type]:
        raise ValueError("Unsupported invoice image type. Use JPG, JPEG, PNG, or WEBP.")
    if not content:
        raise ValueError("Invoice image upload is empty.")
    if len(content) > MAX_INVOICE_IMAGE_BYTES:
        raise ValueError("Invoice image is too large.")
    if not _has_valid_image_signature(normalized_type, content):
        raise ValueError("Invoice image appears malformed or does not match its declared type.")
    return {"filename": clean_filename, "content_type": normalized_type}


def match_product(extracted_name: str | None, products: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not extracted_name:
        return None
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    for product in products:
        score = _product_similarity(extracted_name, product["name"])
        if score > best[0]:
            best = (score, product)
    if best[1] is None or best[0] < PRODUCT_MATCH_THRESHOLD:
        return None
    return {
        "product_id": best[1]["id"],
        "name": best[1]["name"],
        "match_confidence": round(best[0], 2),
        "extracted_name": extracted_name,
    }


def _normalize_metadata(raw_metadata: dict[str, Any]) -> dict[str, dict[str, Any]]:
    optional_fields = {"supplier_gstin"}
    return {
        key: _reviewable_field(_field(raw_metadata, key), missing_requires_review=key not in optional_fields)
        for key in _empty_metadata()
    }


def _empty_metadata() -> dict[str, dict[str, Any]]:
    return {
        "invoice_number": {"value": None, "confidence": None, "requires_review": True},
        "invoice_date": {"value": None, "confidence": None, "requires_review": True},
        "supplier_name": {"value": None, "confidence": None, "requires_review": True},
        "supplier_gstin": {"value": None, "confidence": None, "requires_review": False},
        "total_amount": {"value": None, "confidence": None, "requires_review": True},
    }


def _field(container: dict[str, Any], key: str, aliases: tuple[str, ...] = ()) -> dict[str, Any]:
    value = None
    confidence = None
    raw = None
    for candidate in (key, *aliases):
        if candidate in container:
            raw = container[candidate]
            break
    if isinstance(raw, dict):
        value = raw.get("value")
        confidence = raw.get("confidence")
    elif raw is not None:
        value = raw
    return {"value": value, "confidence": _confidence_or_none(confidence)}


def _reviewable_field(field_value: dict[str, Any], missing_requires_review: bool = True) -> dict[str, Any]:
    return {
        "value": field_value["value"],
        "confidence": field_value["confidence"],
        "requires_review": (field_value["value"] is None and missing_requires_review) or _is_low_confidence(field_value["confidence"]),
    }


def _invoice_warnings(items: list[dict[str, Any]]) -> list[str]:
    warnings = []
    if any("requires_product_mapping" in item["review_reasons"] for item in items):
        warnings.append("Some items require product mapping before inventory can be updated.")
    if any(reason.startswith("low_confidence_") for item in items for reason in item["review_reasons"]):
        warnings.append("Some extracted fields have low OCR confidence and should be reviewed.")
    return warnings


def _confidence_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence > 1:
        confidence = confidence / 100
    return round(max(0.0, min(1.0, confidence)), 4)


def _is_low_confidence(value: float | None) -> bool:
    return value is not None and value < LOW_CONFIDENCE_THRESHOLD


def _positive_number_or_none(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _has_valid_image_signature(content_type: str, content: bytes) -> bool:
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


def _product_similarity(left: str, right: str) -> float:
    left_normalized = _normalize_product_text(left)
    right_normalized = _normalize_product_text(right)
    sequence_score = SequenceMatcher(None, left_normalized, right_normalized).ratio()
    left_tokens = set(left_normalized.split())
    right_tokens = set(right_normalized.split())
    token_score = len(left_tokens & right_tokens) / len(left_tokens | right_tokens) if left_tokens and right_tokens else 0
    return max(sequence_score, (sequence_score * 0.7) + (token_score * 0.3))


def _normalize_product_text(value: str) -> str:
    return " ".join("".join(char.lower() if char.isalnum() else " " for char in value).split())
