from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class MerchantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    business_name: str
    business_type: str
    city: str
    created_at: datetime
    updated_at: datetime


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    name: str = Field(..., max_length=255)
    category: str = Field(..., max_length=120)
    current_stock: int = Field(..., ge=0)
    reorder_level: int = Field(..., ge=0)
    supplier_lead_time_days: int = Field(..., ge=0)
    unit_cost: Decimal = Field(..., ge=0)
    selling_price: Decimal = Field(..., ge=0)
    created_at: datetime
    updated_at: datetime


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    merchant_id: int
    product_id: int
    movement_type: str
    quantity: int
    source: str
    notes: str | None
    created_at: datetime


class DatabaseHealth(BaseModel):
    status: str
    database: str
