from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Product
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

    @staticmethod
    def _product_to_inventory_item(product: Product) -> dict:
        data = ProductRead.model_validate(product).model_dump(mode="json")
        data["sku"] = f"PROD{product.id:03d}"
        data["source"] = "postgresql"
        data["last_updated"] = data["updated_at"][:10]
        return data
