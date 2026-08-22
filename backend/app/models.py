from typing import Any

from pydantic import BaseModel, Field


class InventoryUpdateRequest(BaseModel):
    text: str = Field(..., min_length=2)


class AskRequest(BaseModel):
    question: str = Field(..., min_length=3)


class AIChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    language: str = Field(default="en")


class AIChatResponse(BaseModel):
    response: str
    intent: str
    data: dict[str, Any]


class VoiceTranscriptionResponse(BaseModel):
    text: str
    language: str
    confidence: float | None = None


class VoiceQueryResponse(BaseModel):
    transcript: str
    language: str
    intent: str
    response: str
    data: dict[str, Any]


class VoiceSynthesisRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2500)
    language: str = Field(default="en")


class VoiceHealthResponse(BaseModel):
    sarvam_configured: bool
    transcription_available: bool
    tts_available: bool


class ConfirmedInvoiceItem(BaseModel):
    item_id: str | None = None
    product_name: str | None = None
    quantity: int = Field(..., gt=0)
    product_id: int | None = None
    matched_product_id: int | None = None
    unit_price: float | None = Field(default=None, ge=0)
    total_price: float | None = Field(default=None, ge=0)
    unit: str | None = None


class InvoiceConfirmRequest(BaseModel):
    items: list[ConfirmedInvoiceItem] = Field(default_factory=list)


class InvoiceActionResponse(BaseModel):
    invoice_id: str
    status: str
    processing_status: str
    warnings: list[Any] = Field(default_factory=list)


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


class CustomerMetrics(BaseModel):
    customer_id: str
    total_orders: int
    total_spend: float
    average_order_value: float
    first_purchase_date: str
    last_purchase_date: str
    purchase_frequency: float
    days_since_last_purchase: int
    favorite_category: str | None = None
    favorite_product: str | None = None
    total_quantity_purchased: int
    segment: str
    segment_reason: str


class CustomerPurchase(BaseModel):
    invoice_id: str
    invoice_date: str
    category: str | None = None
    product: str | None = None
    quantity: int
    spend: float


class CustomerDetail(CustomerMetrics):
    recent_purchases: list[CustomerPurchase]
    customer_insight: str


class CustomerListResponse(BaseModel):
    items: list[CustomerMetrics]
    total: int
    limit: int
    offset: int


class CustomerSummaryResponse(BaseModel):
    total_customers: int
    new_customers: int
    loyal_customers: int
    high_value_customers: int
    at_risk_customers: int
    methodology: dict[str, Any]


class CustomerSegmentCount(BaseModel):
    segment: str
    count: int


class CustomerSegmentsResponse(BaseModel):
    items: list[CustomerSegmentCount]
    methodology: dict[str, Any]


class CustomerRecommendation(BaseModel):
    customer_id: str
    priority: str
    reason: str
    recommended_action: str
    total_spend: float
    segment: str


class CustomerRecommendationsResponse(BaseModel):
    items: list[CustomerRecommendation]
    methodology: dict[str, Any]
