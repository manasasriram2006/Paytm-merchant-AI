from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from db.models import Invoice, Merchant

from .inventory_service import InventoryService
from .ocr import OcrExtractionError, OcrUnavailableError, OcrProvider


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
    OCR_UNAVAILABLE = "ocr_unavailable"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class InvoiceNotFoundError(ValueError):
    pass


@dataclass
class InvoiceReviewStore:
    db: Session | None = None
    invoices: dict[str, dict[str, Any]] = field(default_factory=dict)

    def save(self, invoice: dict[str, Any]) -> dict[str, Any]:
        if self.db is not None:
            return self._save_to_db(invoice)
        self.invoices[invoice["invoice_id"]] = invoice
        return invoice

    def get(self, invoice_id: str) -> dict[str, Any]:
        if self.db is not None:
            return self._get_from_db(invoice_id)
        invoice = self.invoices.get(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError(f"Invoice not found: {invoice_id}")
        return invoice

    def _save_to_db(self, invoice: dict[str, Any]) -> dict[str, Any]:
        try:
            existing = self._find_db_invoice(invoice.get("invoice_id"))
            if existing is None:
                db_invoice = Invoice(
                    merchant_id=_default_merchant_id(self.db),
                    file_name=invoice.get("filename") or "invoice",
                    extraction_status=_db_extraction_status(invoice.get("status")),
                    extracted_data={**invoice, "invoice_id": "pending"},
                )
                self.db.add(db_invoice)
                self.db.flush()
                invoice["invoice_id"] = f"inv_{db_invoice.id}"
                db_invoice.extracted_data = invoice
            else:
                existing.file_name = invoice.get("filename") or existing.file_name
                existing.extraction_status = _db_extraction_status(invoice.get("status"))
                existing.extracted_data = invoice
            self.db.commit()
        except SQLAlchemyError as exc:
            self.db.rollback()
            raise RuntimeError("Could not persist invoice data.") from exc
        return invoice

    def _get_from_db(self, invoice_id: str) -> dict[str, Any]:
        try:
            db_invoice = self._find_db_invoice(invoice_id)
        except SQLAlchemyError as exc:
            raise RuntimeError("Could not retrieve invoice data.") from exc
        if db_invoice is None:
            raise InvoiceNotFoundError(f"Invoice not found: {invoice_id}")
        data = dict(db_invoice.extracted_data or {})
        data.setdefault("invoice_id", f"inv_{db_invoice.id}")
        data.setdefault("filename", db_invoice.file_name)
        return data

    def _find_db_invoice(self, invoice_id: str | None) -> Invoice | None:
        if not invoice_id:
            return None
        db_id = _parse_invoice_db_id(invoice_id)
        if db_id is None:
            return None
        return self.db.get(Invoice, db_id)


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
        except OcrUnavailableError as exc:
            invoice = {
                "invoice_id": invoice_id,
                "filename": image["filename"],
                "status": InvoiceStatus.OCR_UNAVAILABLE,
                "processing_status": "ocr_unavailable",
                "message": str(exc),
                "metadata": _empty_metadata(),
                "items": [],
                "warnings": [],
            }
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
        if not confirmed_items:
            raise ValueError("At least one confirmed invoice item is required.")

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
        metadata = _normalize_metadata(raw_invoice.get("metadata") or {})
        return {
            "invoice_id": invoice_id,
            "filename": filename,
            "status": InvoiceStatus.REVIEW_REQUIRED,
            "processing_status": "REVIEW_REQUIRED",
            "metadata": metadata,
            "items": items,
            "warnings": _invoice_warnings(items, metadata),
        }

    @staticmethod
    def _normalize_item(index: int, raw_item: dict[str, Any], products: list[dict[str, Any]]) -> dict[str, Any]:
        product_name = _field(raw_item, "product_name", aliases=("name",))
        quantity = _field(raw_item, "quantity")
        unit_price = _field(raw_item, "unit_price")
        total_price = _field(raw_item, "total_price")
        unit = _field(raw_item, "unit")
        item_confidence = _confidence_or_none(raw_item.get("confidence"))
        matched_product = match_product(product_name["value"], products)
        review_reasons = []
        if product_name["value"] is None:
            review_reasons.append("missing_product_name")
        if quantity["value"] is None:
            review_reasons.append("missing_quantity")
        if quantity["value"] is not None and _positive_number_or_none(quantity["value"]) is None:
            review_reasons.append("invalid_quantity")
        for price_key, price_value in {"unit_price": unit_price, "total_price": total_price}.items():
            if price_value["value"] is not None and _non_negative_number_or_none(price_value["value"]) is None:
                review_reasons.append(f"invalid_{price_key}")
        for key, field_value in {
            "product_name": product_name,
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": total_price,
            "unit": unit,
        }.items():
            if _is_low_confidence(field_value["confidence"]):
                review_reasons.append(f"low_confidence_{key}")
        if _is_low_confidence(item_confidence):
            review_reasons.append("low_confidence_item")
        if matched_product is None:
            review_reasons.append("requires_product_mapping")
        item = {
            "item_id": f"line_{index}",
            "product_name": product_name["value"],
            "product_name_confidence": product_name["confidence"],
            "quantity": _positive_number_or_none(quantity["value"]),
            "quantity_confidence": quantity["confidence"],
            "unit_price": _non_negative_number_or_none(unit_price["value"]),
            "unit_price_confidence": unit_price["confidence"],
            "total_price": _non_negative_number_or_none(total_price["value"]),
            "total_price_confidence": total_price["confidence"],
            "unit": unit["value"],
            "unit_confidence": unit["confidence"],
            "extracted_text": _field(raw_item, "extracted_text", aliases=("raw_text", "text"))["value"],
            "matched_product": matched_product,
            "requires_review": bool(review_reasons),
            "review_reasons": review_reasons,
        }
        if item_confidence is not None:
            item["confidence"] = item_confidence
        return item


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
    metadata = {
        key: _reviewable_field(_field(raw_metadata, key), missing_requires_review=key not in optional_fields)
        for key in _empty_metadata()
    }
    invoice_date = metadata["invoice_date"]["value"]
    if invoice_date is not None and not _is_valid_iso_date(str(invoice_date)):
        metadata["invoice_date"]["requires_review"] = True
        metadata["invoice_date"]["validation_error"] = "Invoice date is not a valid ISO date."
    total_amount = metadata["total_amount"]["value"]
    if total_amount is not None and _non_negative_number_or_none(total_amount) is None:
        metadata["total_amount"]["requires_review"] = True
        metadata["total_amount"]["validation_error"] = "Invoice total must be a non-negative number."
    return metadata


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


def _invoice_warnings(items: list[dict[str, Any]], metadata: dict[str, dict[str, Any]]) -> list[Any]:
    warnings: list[Any] = []
    if any("requires_product_mapping" in item["review_reasons"] for item in items):
        warnings.append("Some items require product mapping before inventory can be updated.")
    if any(reason.startswith("low_confidence_") for item in items for reason in item["review_reasons"]):
        warnings.append("Some extracted fields have low OCR confidence and should be reviewed.")
    for item in items:
        for reason in item["review_reasons"]:
            if reason.startswith("invalid_"):
                warnings.append({"item_id": item["item_id"], "field": reason.removeprefix("invalid_"), "message": "Extracted value is not valid."})
    for field_name, field_value in metadata.items():
        if "validation_error" in field_value:
            warnings.append({"field": field_name, "message": field_value["validation_error"]})
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
    number = _non_negative_number_or_none(value)
    if number is None or number <= 0:
        return None
    return number


def _non_negative_number_or_none(value: Any) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _is_valid_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


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


def _parse_invoice_db_id(invoice_id: str) -> int | None:
    candidate = invoice_id[4:] if invoice_id.startswith("inv_") else invoice_id
    try:
        return int(candidate)
    except (TypeError, ValueError):
        return None


def _db_extraction_status(status: Any) -> str:
    normalized = str(status or "").upper()
    if normalized == InvoiceStatus.FAILED:
        return "failed"
    if str(status or "") == InvoiceStatus.OCR_UNAVAILABLE:
        return "failed"
    if normalized == InvoiceStatus.PROCESSING:
        return "processing"
    return "completed"


def _default_merchant_id(db: Session) -> int:
    merchant_id = db.scalar(select(Merchant.id).order_by(Merchant.id))
    if merchant_id is None:
        raise RuntimeError("No merchant exists for invoice persistence. Seed or create a merchant first.")
    return int(merchant_id)
