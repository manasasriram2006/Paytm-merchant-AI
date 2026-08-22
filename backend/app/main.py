from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import AskRequest, InventoryUpdateRequest, MerchantProfile
from .services.customer_intelligence_service import CustomerIntelligenceService
from .services.data_service import DataService
from .services.forecasting_service import ForecastingService
from .services.inventory_service import InventoryService
from .services.llm import get_llm_provider
from .services.ocr import get_ocr_provider
from .services.transaction_data_service import TransactionDataError, TransactionDataService
from db.database import DatabaseConnectionError, check_database_connection, get_connected_database_name, get_db
from db.schemas import DatabaseHealth


def get_data_service(settings: Settings = Depends(get_settings)) -> DataService:
    return DataService(settings.data_dir)


def get_transaction_data_service(settings: Settings = Depends(get_settings)) -> TransactionDataService:
    return TransactionDataService(settings.data_dir)


def get_forecasting_service(
    transaction_data: TransactionDataService = Depends(get_transaction_data_service),
) -> ForecastingService:
    return ForecastingService(transaction_data)


def get_customer_intelligence_service(
    transaction_data: TransactionDataService = Depends(get_transaction_data_service),
) -> CustomerIntelligenceService:
    return CustomerIntelligenceService(transaction_data)


def get_inventory_service(db: Session = Depends(get_db)) -> InventoryService:
    return InventoryService(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    check_database_connection()
    yield


app = FastAPI(title="Paytm Business AI API", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


@app.get("/api/db/health")
def database_health() -> DatabaseHealth:
    try:
        check_database_connection()
    except (DatabaseConnectionError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return DatabaseHealth(status="ok", database=get_connected_database_name())


@app.get("/api/merchant")
def merchant() -> MerchantProfile:
    return MerchantProfile(
        business_name="Sharma Daily Needs",
        business_type="Kirana Store",
        city="Pune",
        owner_name="Amit Sharma",
    )


@app.get("/api/dashboard")
def dashboard(
    data_service: DataService = Depends(get_data_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> dict:
    return data_service.dashboard(inventory_service.low_stock_count())


@app.get("/api/health-score")
def health_score(
    data_service: DataService = Depends(get_data_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> dict:
    return data_service.business_health(inventory_service.low_stock_count())


@app.get("/api/forecast")
def forecast(
    horizon: int = Query(default=7),
    forecasting_service: ForecastingService = Depends(get_forecasting_service),
) -> dict:
    try:
        return forecasting_service.forecast(horizon)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/customers")
def customers(data_service: DataService = Depends(get_data_service)) -> dict:
    return data_service.customer_intelligence()


@app.get("/api/customers/summary")
def customer_summary(customer_service: CustomerIntelligenceService = Depends(get_customer_intelligence_service)) -> dict:
    return customer_service.summary()


@app.get("/api/customers/segments")
def customer_segments(customer_service: CustomerIntelligenceService = Depends(get_customer_intelligence_service)) -> list[dict]:
    return customer_service.segments()


@app.get("/api/customers/top")
def top_customers(
    limit: int = Query(default=10),
    customer_service: CustomerIntelligenceService = Depends(get_customer_intelligence_service),
) -> list[dict]:
    return customer_service.top_customers(limit)


@app.get("/api/customers/at-risk")
def at_risk_customers(
    limit: int = Query(default=10),
    customer_service: CustomerIntelligenceService = Depends(get_customer_intelligence_service),
) -> dict:
    return customer_service.at_risk(limit)


@app.get("/api/customers/demographics")
def customer_demographics(customer_service: CustomerIntelligenceService = Depends(get_customer_intelligence_service)) -> dict:
    return customer_service.demographics()


@app.get("/api/customers/loyalty")
def customer_loyalty(customer_service: CustomerIntelligenceService = Depends(get_customer_intelligence_service)) -> dict:
    return customer_service.loyalty()


@app.get("/api/customers/insights")
def customer_insights(customer_service: CustomerIntelligenceService = Depends(get_customer_intelligence_service)) -> list[dict]:
    return customer_service.insights()


@app.get("/api/customers/value")
def customer_value(customer_service: CustomerIntelligenceService = Depends(get_customer_intelligence_service)) -> dict:
    return customer_service.value_summary()


@app.get("/api/transactions/profile")
def transaction_profile(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.profile)


@app.get("/api/transactions/summary")
def transaction_summary(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.summary)


@app.get("/api/transactions/daily")
def transaction_daily(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    transaction_data: TransactionDataService = Depends(get_transaction_data_service),
) -> dict:
    return _transaction_response(transaction_data.time_series, "daily", start_date, end_date)


@app.get("/api/transactions/weekly")
def transaction_weekly(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    transaction_data: TransactionDataService = Depends(get_transaction_data_service),
) -> dict:
    return _transaction_response(transaction_data.time_series, "weekly", start_date, end_date)


@app.get("/api/transactions/monthly")
def transaction_monthly(
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    transaction_data: TransactionDataService = Depends(get_transaction_data_service),
) -> dict:
    return _transaction_response(transaction_data.time_series, "monthly", start_date, end_date)


@app.get("/api/analytics/products")
def product_analytics(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.product_analytics)


@app.get("/api/analytics/categories")
def category_analytics(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.category_analytics)


@app.get("/api/analytics/brands")
def brand_analytics(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.brand_analytics)


@app.get("/api/analytics/payments")
def payment_analytics(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.payment_analytics)


@app.get("/api/analytics/business")
def business_analytics(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.business_analytics)


@app.get("/api/customers/basic-summary")
def customer_basic_summary(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.customer_basic_summary)


@app.get("/api/inventory")
def inventory(inventory_service: InventoryService = Depends(get_inventory_service)) -> dict:
    return {"items": inventory_service.list_items(), "lowStock": inventory_service.low_stock()}


@app.get("/api/inventory/data-summary")
def inventory_data_summary(transaction_data: TransactionDataService = Depends(get_transaction_data_service)) -> dict:
    return _transaction_response(transaction_data.inventory_data_summary)


def _transaction_response(handler, *args) -> dict:
    try:
        return handler(*args)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date filter: {exc}") from exc
    except TransactionDataError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/inventory/update")
def update_inventory(
    payload: InventoryUpdateRequest,
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> dict:
    return inventory_service.apply_text_update(payload.text)


@app.post("/api/invoice/ocr")
async def invoice_ocr(file: UploadFile = File(...), app_settings: Settings = Depends(get_settings)) -> dict:
    content = await file.read()
    provider = get_ocr_provider(app_settings.ocr_provider)
    items = await provider.extract_invoice_items(content, file.filename or "invoice")
    return {
        "filename": file.filename,
        "provider": app_settings.ocr_provider,
        "items": items,
        "message": "Demo OCR extracted invoice items. Review before applying stock changes.",
    }


@app.post("/api/ask")
def ask(
    payload: AskRequest,
    app_settings: Settings = Depends(get_settings),
    data_service: DataService = Depends(get_data_service),
    inventory_service: InventoryService = Depends(get_inventory_service),
) -> dict:
    provider = get_llm_provider(app_settings.llm_provider)
    context = {
        "summary": data_service.summary(inventory_service.low_stock_count()),
        "low_stock": inventory_service.low_stock(),
        "forecast": data_service.forecast(),
    }
    return {"answer": provider.answer(payload.question, context), "provider": app_settings.llm_provider}
