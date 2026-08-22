from pydantic import BaseModel, Field


class InventoryUpdateRequest(BaseModel):
    text: str = Field(..., min_length=2)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3)


class MerchantProfile(BaseModel):
    business_name: str
    business_type: str
    city: str
    owner_name: str


class InventoryItem(BaseModel):
    sku: str
    name: str
    category: str
    current_stock: int
    reorder_level: int
    last_updated: str
    source: str
