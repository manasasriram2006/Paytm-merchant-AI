from __future__ import annotations

from dataclasses import dataclass
from unittest import TestCase, main

import pandas as pd

from app.services.smart_inventory_service import (
    VALID_RISK_LEVELS,
    ProductNotFoundError,
    SmartInventoryService,
    build_demand_profile,
    calculate_inventory_policy,
    normalize_risk_filter,
)


@dataclass(frozen=True)
class ProductStub:
    id: int = 1
    name: str = "Amul Milk"
    category: str = "dairy"
    current_stock: int = 10
    supplier_lead_time_days: int = 3


def sales_frame(units: list[int], category: str = "Dairy", brand: str = "Amul") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Invoice_Date": pd.date_range("2024-01-01", periods=len(units), freq="D"),
            "Category": [category] * len(units),
            "Brand": [brand] * len(units),
            "Units": units,
        }
    )


class MissingProductDb:
    def get(self, model, product_id):
        return None


class SmartInventoryPolicyTests(TestCase):
    def test_normal_inventory_recommendation_calculation_is_deterministic(self) -> None:
        first = calculate_inventory_policy(20, 5, 1.2, 3)
        second = calculate_inventory_policy(20, 5, 1.2, 3)

        self.assertEqual(first, second)
        self.assertIn(first.risk_level, VALID_RISK_LEVELS)
        self.assertEqual(first.reorder_point, 18)
        self.assertEqual(first.recommended_order_quantity, 0)

    def test_low_stock_is_medium_when_near_reorder_point(self) -> None:
        result = calculate_inventory_policy(17, 5, 1, 3)

        self.assertEqual(result.risk_level, "MEDIUM")
        self.assertTrue(result.requires_reorder)
        self.assertEqual(result.recommended_order_quantity, 35)

    def test_high_risk_stock_cannot_cover_lead_time(self) -> None:
        result = calculate_inventory_policy(8, 5, 1, 3)

        self.assertEqual(result.risk_level, "HIGH")
        self.assertTrue(result.requires_reorder)
        self.assertIn("below the 3-day supplier lead time", result.reason)

    def test_sufficient_stock_is_low_risk(self) -> None:
        result = calculate_inventory_policy(90, 5, 1, 3)

        self.assertEqual(result.risk_level, "LOW")
        self.assertFalse(result.requires_reorder)
        self.assertEqual(result.recommended_order_quantity, 0)

    def test_zero_stock_does_not_divide_by_zero(self) -> None:
        result = calculate_inventory_policy(0, 4, 0, 2)

        self.assertEqual(result.stock_coverage_days, 0)
        self.assertEqual(result.risk_level, "HIGH")
        self.assertGreater(result.recommended_order_quantity, 0)

    def test_zero_demand_returns_unlimited_coverage_without_reorder(self) -> None:
        result = calculate_inventory_policy(0, 0, 0, 2)

        self.assertIsNone(result.stock_coverage_days)
        self.assertEqual(result.risk_level, "LOW")
        self.assertEqual(result.recommended_order_quantity, 0)

    def test_high_demand_increases_recommended_order_quantity(self) -> None:
        low_demand = calculate_inventory_policy(10, 2, 0, 2)
        high_demand = calculate_inventory_policy(10, 20, 0, 2)

        self.assertGreater(high_demand.recommended_order_quantity, low_demand.recommended_order_quantity)
        self.assertEqual(high_demand.risk_level, "HIGH")

    def test_long_supplier_lead_time_raises_reorder_point(self) -> None:
        short_lead = calculate_inventory_policy(50, 5, 1, 1)
        long_lead = calculate_inventory_policy(50, 5, 1, 10)

        self.assertGreater(long_lead.reorder_point, short_lead.reorder_point)

    def test_missing_historical_data_returns_insufficient_data(self) -> None:
        profile = build_demand_profile(sales_frame([1, 2, 3], category="Snacks", brand="Lays"), ProductStub(category="hardware"), 10)

        self.assertEqual(profile.status, "insufficient_data")
        policy = calculate_inventory_policy(10, profile.forecast_daily_demand, profile.demand_stddev, 3, profile.status)
        self.assertEqual(policy.recommended_order_quantity, 0)

    def test_invalid_product_id_returns_not_found_error_contract(self) -> None:
        service = SmartInventoryService(MissingProductDb(), None, None)

        with self.assertRaises(ProductNotFoundError):
            service.product_detail(999)

    def test_invalid_risk_filter_is_rejected_by_contract(self) -> None:
        with self.assertRaises(ValueError):
            normalize_risk_filter("URGENT")

    def test_recommendation_calculation_uses_history_and_existing_aggregate_forecast_share(self) -> None:
        df = sales_frame([2, 4, 6, 8])
        profile = build_demand_profile(df, ProductStub(), aggregate_forecast_daily_units=20)

        self.assertEqual(profile.status, "ok")
        self.assertEqual(profile.match_type, "brand")
        self.assertEqual(profile.average_daily_demand, 5)
        self.assertEqual(profile.forecast_daily_demand, 20)


if __name__ == "__main__":
    main()
