from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Product, StockMovement
from db.schemas import ProductRead


@dataclass
class InventoryService:
    db: Session

    def list_items(self) -> list[dict]:
        products = self.db.scalars(select(Product).order_by(Product.id)).all()
        return [self._product_to_inventory_item(product) for product in products]

    def apply_text_update(self, text: str) -> dict:
        normalized = text.lower()
        quantity_match = re.search(r"(\d+)", normalized)
        quantity = int(quantity_match.group(1)) if quantity_match else 1

        matched_item = None
        products = self.db.scalars(select(Product).order_by(Product.id)).all()
        for product in products:
            tokens = product.name.lower().split()
            if any(token in normalized for token in tokens[:2]):
                matched_item = product
                break

        if matched_item is None:
            return {
                "status": "needs_review",
                "message": "I could not confidently match that item. Please add the product name and quantity.",
                "parsed": {"quantity": quantity, "source": "voice_or_text"},
            }

        direction = -1 if any(word in normalized for word in ["sold", "used", "remove", "minus"]) else 1
        matched_item.current_stock = max(0, matched_item.current_stock + direction * quantity)
        matched_item.last_updated = date.today()
        matched_item.source = "voice_or_text"
        self.db.commit()
        self.db.refresh(matched_item)

        item = self._product_to_inventory_item(matched_item)
        return {
            "status": "updated",
            "message": f"Updated {item['name']} stock to {item['current_stock']}.",
            "item": item,
        }

    def low_stock(self) -> list[dict]:
        low = self.db.scalars(
            select(Product)
            .where(Product.current_stock <= Product.reorder_level)
            .order_by(Product.id)
        ).all()
        return [self._product_to_inventory_item(product) for product in low]

    def low_stock_count(self) -> int:
        return len(self.low_stock())

    def apply_invoice_confirmation(self, items: list[dict], invoice_id: str) -> dict:
        confirmed_items = []
        warnings = []
        products_by_id = {product.id: product for product in self.db.scalars(select(Product).order_by(Product.id)).all()}

        for item in items:
            product_id = item.get("product_id") or item.get("matched_product_id")
            quantity = _confirmed_quantity(item.get("quantity"))
            if product_id is None:
                warnings.append(
                    {
                        "item_id": item.get("item_id"),
                        "product_name": item.get("product_name"),
                        "status": "requires_product_mapping",
                    }
                )
                confirmed_items.append({**item, "status": "requires_product_mapping"})
                continue
            product = products_by_id.get(int(product_id))
            if product is None:
                warnings.append(
                    {
                        "item_id": item.get("item_id"),
                        "product_id": product_id,
                        "status": "product_not_found",
                    }
                )
                confirmed_items.append({**item, "status": "product_not_found"})
                continue
            if quantity is None:
                warnings.append(
                    {
                        "item_id": item.get("item_id"),
                        "product_id": product_id,
                        "status": "invalid_quantity",
                    }
                )
                confirmed_items.append({**item, "status": "invalid_quantity"})
                continue

            product.current_stock += quantity
            product.last_updated = date.today()
            movement = StockMovement(
                merchant_id=product.merchant_id,
                product_id=product.id,
                movement_type="purchase",
                quantity=quantity,
                source="invoice",
                notes=f"Confirmed OCR invoice {invoice_id}",
            )
            self.db.add(movement)
            confirmed_items.append(
                {
                    **item,
                    "product_id": product.id,
                    "matched_product_name": product.name,
                    "quantity": quantity,
                    "status": "inventory_updated",
                    "new_stock": product.current_stock,
                }
            )

        self.db.commit()
        for item in confirmed_items:
            product_id = item.get("product_id")
            if item.get("status") == "inventory_updated" and product_id in products_by_id:
                self.db.refresh(products_by_id[product_id])
                item["new_stock"] = int(products_by_id[product_id].current_stock)

        return {
            "status": "updated" if any(item.get("status") == "inventory_updated" for item in confirmed_items) else "requires_review",
            "confirmed_items": confirmed_items,
            "warnings": warnings,
        }

    @staticmethod
    def _product_to_inventory_item(product: Product) -> dict:
        data = ProductRead.model_validate(product).model_dump(mode="json")
        data["sku"] = f"PROD{product.id:03d}"
        data["source"] = "postgresql"
        data["last_updated"] = data["updated_at"][:10]
        return data


def _confirmed_quantity(value) -> int | None:
    try:
        quantity = int(value)
    except (TypeError, ValueError):
        return None
    return quantity if quantity > 0 else None
