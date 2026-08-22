from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Product

from .forecasting_service import ForecastingService
from .transaction_data_service import TransactionDataService, _round_money


VALID_RISK_LEVELS = {"HIGH", "MEDIUM", "LOW"}
RECENT_WINDOW_DAYS = 14
REVIEW_CYCLE_DAYS = 7


class InventoryIntelligenceError(RuntimeError):
    pass


class ProductNotFoundError(InventoryIntelligenceError):
    pass


@dataclass(frozen=True)
class DemandProfile:
    status: str
    match_type: str | None
    historical_days: int
    average_daily_demand: float
    recent_daily_demand: float
    demand_stddev: float
    forecast_daily_demand: float


@dataclass(frozen=True)
class InventoryPolicyResult:
    stock_coverage_days: float | None
    safety_stock: int
    reorder_point: int
    recommended_order_quantity: int
    risk_level: str
    requires_reorder: bool
    reason: str


@dataclass
class SmartInventoryService:
    db: Session
    transaction_data: TransactionDataService
    forecasting_service: ForecastingService

    def summary(self) -> dict[str, Any]:
        items = self._recommendation_items()
        return {
            "total_products": len(items),
            "low_stock_products": sum(1 for item in items if item["current_stock"] <= item["reorder_point"]),
            "low_risk_products": sum(1 for item in items if item["risk_level"] == "LOW"),
            "medium_risk_products": sum(1 for item in items if item["risk_level"] == "MEDIUM"),
            "high_risk_products": sum(1 for item in items if item["risk_level"] == "HIGH"),
            "products_requiring_reorder": sum(1 for item in items if item["requires_reorder"]),
            "total_inventory_value": self._inventory_value(),
            "value_note": "Calculated from PostgreSQL current_stock * unit_cost; null when no products are available.",
        }

    def alerts(self, risk: str | None = None, category: str | None = None, limit: int | None = None) -> dict[str, Any]:
        normalized_risk = normalize_risk_filter(risk)
        items = self._recommendation_items()
        if normalized_risk:
            items = [item for item in items if item["risk_level"] == normalized_risk]
        if category:
            items = [item for item in items if item["category"].casefold() == category.casefold()]
        items = [item for item in items if item["requires_reorder"] or item["risk_level"] in {"HIGH", "MEDIUM"}]
        items.sort(key=lambda item: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}[item["risk_level"]], item["stock_coverage_days"] or 999999))
        if limit is not None:
            items = items[:limit]
        return {"items": items, "count": len(items)}

    def recommendations(self) -> dict[str, Any]:
        items = [item for item in self._recommendation_items() if item["requires_reorder"]]
        items.sort(key=lambda item: ({"HIGH": 0, "MEDIUM": 1, "LOW": 2}[item["risk_level"]], item["product_id"]))
        return {"items": items, "count": len(items)}

    def product_detail(self, product_id: int) -> dict[str, Any]:
        product = self.db.get(Product, product_id)
        if product is None:
            raise ProductNotFoundError(f"Product {product_id} does not exist.")
        return self._product_recommendation(product, include_history=True)

    def _recommendation_items(self) -> list[dict[str, Any]]:
        products = self.db.scalars(select(Product).order_by(Product.id)).all()
        aggregate_forecast = self._aggregate_forecast_daily_units()
        return [self._product_recommendation(product, aggregate_forecast_daily_units=aggregate_forecast) for product in products]

    def _product_recommendation(
        self,
        product: Product,
        include_history: bool = False,
        aggregate_forecast_daily_units: float | None = None,
    ) -> dict[str, Any]:
        df = self.transaction_data.dataframe()
        aggregate_forecast = aggregate_forecast_daily_units if aggregate_forecast_daily_units is not None else self._aggregate_forecast_daily_units()
        demand = build_demand_profile(df, product, aggregate_forecast)
        expected_daily_demand = max(demand.forecast_daily_demand, demand.recent_daily_demand, demand.average_daily_demand)
        policy = calculate_inventory_policy(
            current_stock=int(product.current_stock),
            expected_daily_demand=expected_daily_demand,
            demand_stddev=demand.demand_stddev,
            lead_time_days=int(product.supplier_lead_time_days),
            status=demand.status,
        )

        item = {
            "product_id": int(product.id),
            "product": product.name,
            "category": product.category,
            "current_stock": int(product.current_stock),
            "average_daily_demand": round(demand.average_daily_demand, 2),
            "recent_daily_demand": round(demand.recent_daily_demand, 2),
            "forecast_daily_demand": round(demand.forecast_daily_demand, 2),
            "expected_daily_demand": round(expected_daily_demand, 2),
            "lead_time_days": int(product.supplier_lead_time_days),
            "stock_coverage_days": round(policy.stock_coverage_days, 2) if policy.stock_coverage_days is not None else None,
            "safety_stock": policy.safety_stock,
            "reorder_point": policy.reorder_point,
            "recommended_order_quantity": policy.recommended_order_quantity,
            "risk_level": policy.risk_level,
            "requires_reorder": policy.requires_reorder,
            "status": demand.status,
            "reason": policy.reason,
            "data_source": {
                "current_stock": "products.current_stock in PostgreSQL, updated by inventory APIs and audited by stock_movements",
                "demand": f"data/fmcg_sales_enriched.csv matched by {demand.match_type or 'no_match'}",
                "forecast": "existing aggregate ForecastingService allocated by historical unit share",
            },
        }
        if include_history:
            item["historical_demand_summary"] = {
                "historical_days": demand.historical_days,
                "match_type": demand.match_type,
                "average_daily_demand": round(demand.average_daily_demand, 2),
                "recent_window_days": RECENT_WINDOW_DAYS,
                "recent_daily_demand": round(demand.recent_daily_demand, 2),
                "demand_stddev": round(demand.demand_stddev, 2),
            }
            item["formula_assumptions"] = formula_assumptions()
        return item

    def _aggregate_forecast_daily_units(self) -> float:
        forecast = self.forecasting_service.forecast(7)
        items = forecast.get("forecast", [])
        if not items:
            return 0.0
        return float(sum(float(item.get("units", 0)) for item in items) / len(items))

    def _inventory_value(self) -> float | None:
        products = self.db.scalars(select(Product)).all()
        if not products:
            return None
        value = sum(float(product.unit_cost) * int(product.current_stock) for product in products)
        return _round_money(value)


def build_demand_profile(df: pd.DataFrame, product: Product, aggregate_forecast_daily_units: float) -> DemandProfile:
    matched, match_type = _matched_history(df, product)
    if matched.empty:
        return DemandProfile(
            status="insufficient_data",
            match_type=None,
            historical_days=0,
            average_daily_demand=0.0,
            recent_daily_demand=0.0,
            demand_stddev=0.0,
            forecast_daily_demand=0.0,
        )

    daily = _daily_units(matched, df)
    average_daily = float(daily["units"].mean()) if len(daily) else 0.0
    recent_daily = float(daily["units"].tail(RECENT_WINDOW_DAYS).mean()) if len(daily) else 0.0
    stddev = float(daily["units"].std(ddof=0)) if len(daily) else 0.0
    total_units = float(df["Units"].sum()) if "Units" in df.columns else 0.0
    matched_units = float(matched["Units"].sum())
    product_share = matched_units / total_units if total_units > 0 else 0.0
    forecast_daily = max(0.0, aggregate_forecast_daily_units * product_share)
    return DemandProfile(
        status="ok",
        match_type=match_type,
        historical_days=int(len(daily)),
        average_daily_demand=max(0.0, average_daily),
        recent_daily_demand=max(0.0, recent_daily),
        demand_stddev=max(0.0, stddev),
        forecast_daily_demand=forecast_daily,
    )


def calculate_inventory_policy(
    current_stock: int,
    expected_daily_demand: float,
    demand_stddev: float,
    lead_time_days: int,
    status: str = "ok",
) -> InventoryPolicyResult:
    """Explainable policy:

    lead_time_demand = expected_daily_demand * lead_time_days
    safety_stock = ceil(daily demand stddev * sqrt(lead_time_days))
    reorder_point = ceil(lead_time_demand + safety_stock)
    target_stock = ceil(expected_daily_demand * (lead_time_days + 7-day review cycle) + safety_stock)

    Risk thresholds are deterministic:
    HIGH when stock cannot cover lead-time demand.
    MEDIUM when stock is at/below reorder point or covers no more than lead time + 2 days.
    LOW when stock is comfortably above those thresholds.
    """
    current_stock = max(0, int(current_stock))
    lead_time_days = max(0, int(lead_time_days))
    expected_daily_demand = max(0.0, float(expected_daily_demand))
    demand_stddev = max(0.0, float(demand_stddev))

    if status == "insufficient_data":
        reason = "Insufficient historical demand data is available for this product or category, so no reorder is recommended yet."
        return InventoryPolicyResult(None, 0, 0, 0, "LOW", False, reason)

    if expected_daily_demand <= 0:
        reason = "Expected daily demand is 0.0 units, so stock coverage is effectively unlimited and no reorder is currently required."
        return InventoryPolicyResult(None, 0, 0, 0, "LOW", False, reason)

    lead_time_demand = expected_daily_demand * lead_time_days
    safety_stock = int(math.ceil(demand_stddev * math.sqrt(max(lead_time_days, 1))))
    reorder_point = int(math.ceil(lead_time_demand + safety_stock))
    stock_coverage_days = current_stock / expected_daily_demand
    target_stock = int(math.ceil(expected_daily_demand * (lead_time_days + REVIEW_CYCLE_DAYS) + safety_stock))
    requires_reorder = current_stock <= reorder_point
    recommended_order_quantity = max(0, target_stock - current_stock) if requires_reorder else 0

    if current_stock < lead_time_demand:
        risk_level = "HIGH"
        reason = (
            f"Current stock covers approximately {stock_coverage_days:.1f} days of demand, "
            f"below the {lead_time_days}-day supplier lead time."
        )
    elif current_stock <= reorder_point or stock_coverage_days <= lead_time_days + 2:
        risk_level = "MEDIUM"
        reason = (
            f"Current stock covers approximately {stock_coverage_days:.1f} days of demand and is near "
            f"the reorder point of {reorder_point} units."
        )
    else:
        risk_level = "LOW"
        reason = (
            f"Stock is healthy: current stock covers approximately {stock_coverage_days:.1f} days of demand, "
            f"above the reorder point of {reorder_point} units."
        )

    return InventoryPolicyResult(
        stock_coverage_days=stock_coverage_days,
        safety_stock=safety_stock,
        reorder_point=reorder_point,
        recommended_order_quantity=recommended_order_quantity,
        risk_level=risk_level,
        requires_reorder=requires_reorder,
        reason=reason,
    )


def formula_assumptions() -> dict[str, Any]:
    return {
        "lead_time_demand": "expected_daily_demand * lead_time_days",
        "safety_stock": "ceil(daily_demand_stddev * sqrt(lead_time_days))",
        "reorder_point": "ceil(lead_time_demand + safety_stock)",
        "target_stock": f"ceil(expected_daily_demand * (lead_time_days + {REVIEW_CYCLE_DAYS}) + safety_stock)",
        "risk_thresholds": {
            "HIGH": "current_stock < expected_daily_demand * lead_time_days",
            "MEDIUM": "current_stock <= reorder_point or stock_coverage_days <= lead_time_days + 2",
            "LOW": "stock above reorder point with more than lead_time_days + 2 days of coverage",
        },
    }


def normalize_risk_filter(risk: str | None) -> str | None:
    normalized_risk = risk.upper() if risk else None
    if normalized_risk and normalized_risk not in VALID_RISK_LEVELS:
        raise ValueError("risk must be one of: HIGH, MEDIUM, LOW")
    return normalized_risk


def _matched_history(df: pd.DataFrame, product: Product) -> tuple[pd.DataFrame, str | None]:
    product_name = _normalize(str(product.name))
    category = _normalize(str(product.category))

    if "Brand" in df.columns:
        brand_mask = df["Brand"].fillna("").map(lambda value: _brand_matches(product_name, _normalize(str(value))))
        if brand_mask.any():
            return df.loc[brand_mask].copy(), "brand"

    if "Category" in df.columns:
        category_mask = df["Category"].fillna("").map(lambda value: _category_matches(category, _normalize(str(value))))
        if category_mask.any():
            return df.loc[category_mask].copy(), "category"

    return df.iloc[0:0].copy(), None


def _daily_units(matched: pd.DataFrame, full_df: pd.DataFrame) -> pd.DataFrame:
    start = full_df["Invoice_Date"].min().normalize()
    end = full_df["Invoice_Date"].max().normalize()
    index = pd.date_range(start=start, end=end, freq="D")
    daily = matched.set_index("Invoice_Date").resample("D").agg(units=("Units", "sum")).reindex(index, fill_value=0)
    return daily.reset_index(names="date")


def _brand_matches(product_name: str, brand: str) -> bool:
    if not product_name or not brand:
        return False
    return brand in product_name or any(token and token in brand for token in product_name.split())


def _category_matches(product_category: str, csv_category: str) -> bool:
    if not product_category or not csv_category:
        return False
    aliases = {
        "beverages": {"beverage", "beverages", "drinks"},
        "biscuits": {"biscuits", "snacks"},
        "groceries": {"grocery", "groceries"},
        "bakery": {"bakery", "grocery"},
    }
    product_values = aliases.get(product_category, {product_category.rstrip("s"), product_category})
    csv_values = aliases.get(csv_category, {csv_category.rstrip("s"), csv_category})
    return not product_values.isdisjoint(csv_values)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().replace("-", " ").replace("_", " ").split())
