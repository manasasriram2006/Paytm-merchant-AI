from __future__ import annotations

from dataclasses import dataclass
from unittest import TestCase, main

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app, get_customer_intelligence_service
from app.services.customer_intelligence_service import (
    CustomerIntelligenceService,
    CustomerNotFoundError,
    _build_customer_intelligence,
)
from app.services.transaction_data_service import _load_clean_data


@dataclass(frozen=True)
class StubTransactionData:
    frame: pd.DataFrame

    def dataframe(self) -> pd.DataFrame:
        return self.frame.copy()


def row(customer_id: str, invoice_id: int, date: str, revenue: float, units: int, category: str = "Dairy") -> dict:
    return {
        "Invoice_ID": invoice_id,
        "Invoice_Date": date,
        "Revenue": revenue,
        "Units": units,
        "Cost": revenue * 0.7,
        "Margin": revenue * 0.3,
        "Customer_ID": customer_id,
        "Category": category,
        "Brand": "Amul" if category == "Dairy" else "Parle",
        "Customer_Age": 32,
        "Customer_Gender": "F",
        "Loyalty_Flag": 1,
    }


def sample_rows() -> list[dict]:
    return [
        row("C_HIGH", 1, "2024-01-10", 50, 1),
        row("C_HIGH", 2, "2024-03-25", 500, 5),
        row("C_HIGH", 13, "2024-03-28", 450, 4),
        row("C_LOYAL", 3, "2024-03-20", 40, 1),
        row("C_LOYAL", 4, "2024-03-21", 45, 1),
        row("C_LOYAL", 5, "2024-03-22", 50, 1),
        row("C_LOYAL", 6, "2024-03-23", 55, 1),
        row("C_LOYAL", 7, "2024-03-24", 60, 1),
        row("C_RISK", 8, "2024-01-01", 90, 2, "Snacks"),
        row("C_RISK", 9, "2024-01-05", 90, 2, "Snacks"),
        row("C_RISK", 10, "2024-01-09", 90, 2, "Snacks"),
        row("C_NEW", 11, "2024-03-31", 80, 1),
        row("C_OCC", 12, "2024-03-01", 30, 1),
    ]


class CustomerIntelligenceTests(TestCase):
    def setUp(self) -> None:
        _load_clean_data.cache_clear()
        _build_customer_intelligence.cache_clear()
        frame = pd.DataFrame(sample_rows())
        frame["Invoice_Date"] = pd.to_datetime(frame["Invoice_Date"])
        self.service = CustomerIntelligenceService(StubTransactionData(frame))

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        _load_clean_data.cache_clear()
        _build_customer_intelligence.cache_clear()

    def test_customer_aggregation_metrics(self) -> None:
        detail = self.service.customer_detail("C_HIGH")

        self.assertEqual(detail["total_orders"], 3)
        self.assertEqual(detail["total_spend"], 1000)
        self.assertEqual(detail["average_order_value"], 333.33)
        self.assertEqual(detail["total_quantity_purchased"], 10)
        self.assertEqual(detail["first_purchase_date"], "2024-01-10")
        self.assertEqual(detail["last_purchase_date"], "2024-03-28")
        self.assertEqual(detail["days_since_last_purchase"], 3)
        self.assertEqual(detail["favorite_category"], "Dairy")
        self.assertEqual(detail["favorite_product"], "Amul")

    def test_frequency_and_recency_are_calculated_from_dataset_reference_date(self) -> None:
        detail = self.service.customer_detail("C_LOYAL")

        self.assertEqual(detail["days_since_last_purchase"], 7)
        self.assertEqual(detail["purchase_frequency"], 12.5)

    def test_segmentation_classifies_required_segments(self) -> None:
        customers = {item["customer_id"]: item["segment"] for item in self.service.list_customers(limit=20)["items"]}

        self.assertEqual(customers["C_HIGH"], "HIGH_VALUE")
        self.assertEqual(customers["C_LOYAL"], "LOYAL")
        self.assertEqual(customers["C_RISK"], "AT_RISK")
        self.assertEqual(customers["C_NEW"], "NEW")
        self.assertEqual(customers["C_OCC"], "OCCASIONAL")

    def test_summary_and_segment_counts(self) -> None:
        summary = self.service.summary()
        segments = {item["segment"]: item["count"] for item in self.service.segments()["items"]}

        self.assertEqual(summary["total_customers"], 5)
        self.assertEqual(summary["high_value_customers"], 1)
        self.assertEqual(summary["loyal_customers"], 1)
        self.assertEqual(summary["at_risk_customers"], 1)
        self.assertEqual(summary["new_customers"], 1)
        self.assertEqual(segments["OCCASIONAL"], 1)
        self.assertIn("segment_rules", summary["methodology"])

    def test_recommendations_are_explainable_and_prioritized(self) -> None:
        recommendations = self.service.recommendations(limit=5)["items"]

        self.assertEqual(recommendations[0]["customer_id"], "C_RISK")
        self.assertEqual(recommendations[0]["priority"], "HIGH")
        self.assertIn("not purchased", recommendations[0]["reason"])
        self.assertIn("recommended_action", recommendations[0])

    def test_invalid_customer_id_raises_not_found(self) -> None:
        with self.assertRaises(CustomerNotFoundError):
            self.service.customer_detail("NOPE")

    def test_empty_dataset_returns_zero_counts(self) -> None:
        service = CustomerIntelligenceService(StubTransactionData(pd.DataFrame(columns=sample_rows()[0].keys())))

        self.assertEqual(service.summary()["total_customers"], 0)
        self.assertEqual(service.list_customers()["items"], [])

    def test_api_filtering_pagination_and_invalid_customer_id(self) -> None:
        app.dependency_overrides[get_customer_intelligence_service] = lambda: self.service
        client = TestClient(app)

        filtered = client.get("/api/customers", params={"segment": "LOYAL", "limit": 1, "offset": 0})
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.json()["total"], 1)
        self.assertEqual(filtered.json()["items"][0]["customer_id"], "C_LOYAL")

        searched = client.get("/api/customers", params={"search": "RISK"})
        self.assertEqual(searched.status_code, 200)
        self.assertEqual(searched.json()["items"][0]["customer_id"], "C_RISK")

        missing = client.get("/api/customers/NOPE")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    main()
