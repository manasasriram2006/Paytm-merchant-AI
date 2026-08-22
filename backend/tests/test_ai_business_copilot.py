from __future__ import annotations

from dataclasses import dataclass
from unittest import TestCase, main

from fastapi.testclient import TestClient

from app.main import app, get_business_ai_service
from app.services.ai_provider import DeterministicAIProvider, SarvamAIProvider
from app.services.voice_ai_service import BusinessAIService, BusinessIntent, detect_intents


@dataclass(frozen=True)
class StubDataService:
    empty: bool = False

    def summary(self, low_stock_count: int = 0) -> dict:
        if self.empty:
            return {}
        return {
            "totalSales": 12000,
            "latestDaySales": 1400,
            "sevenDayTrendPct": 8.5,
            "lowStockCount": low_stock_count,
        }

    def business_health(self, low_stock_count: int = 0) -> dict:
        if self.empty:
            return {}
        return {
            "score": 76,
            "label": "Healthy",
            "drivers": [{"name": "Sales momentum", "detail": "8.5% vs recent average"}],
        }


@dataclass(frozen=True)
class StubForecastingService:
    empty: bool = False

    def forecast(self, horizon: int = 7) -> dict:
        if self.empty:
            return {"forecast_method": "insufficient_data", "daily_forecast": [], "category_forecast": []}
        return {
            "summary": {"expected_revenue": 7000, "expected_units": 350},
            "category_forecast": [{"category": "Snacks", "forecast_demand": 90}],
            "forecast": [{"units": 50}],
        }


@dataclass(frozen=True)
class StubInventoryService:
    empty: bool = False

    def recommendations(self) -> dict:
        if self.empty:
            return {"items": [], "count": 0}
        return {
            "items": [
                {
                    "product": "Biscuits",
                    "current_stock": 12,
                    "stock_coverage_days": 1.5,
                    "recommended_order_quantity": 40,
                }
            ],
            "count": 1,
        }

    def summary(self) -> dict:
        return {"products_requiring_reorder": 1 if not self.empty else 0}


@dataclass(frozen=True)
class StubCustomerService:
    empty: bool = False

    def summary(self) -> dict:
        if self.empty:
            return {}
        return {"high_value_customers": 4, "at_risk_customers": 3}

    def recommendations(self, limit: int = 5) -> dict:
        if self.empty:
            return {"items": []}
        return {"items": [{"customer_id": "C101", "priority": "HIGH"}]}


def copilot(empty: bool = False, ai_provider: str | None = None, ai_api_key: str | None = None) -> BusinessAIService:
    provider = SarvamAIProvider(ai_api_key) if ai_provider == "sarvam" else DeterministicAIProvider()
    return BusinessAIService(
        StubDataService(empty),
        StubForecastingService(empty),
        StubInventoryService(empty),
        StubCustomerService(empty),
        ai_provider=provider,
    )


class AiBusinessCopilotTests(TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_sales_question_routing_and_sources(self) -> None:
        result = copilot().chat("How are my sales?")

        self.assertEqual(result["intent"], "SALES_ANALYTICS")
        self.assertEqual(result["sources"], ["sales_analytics", "transaction_analytics"])
        self.assertIn("Rs 12000", result["answer"])

    def test_inventory_question_routing_uses_smart_inventory_numbers(self) -> None:
        result = copilot().chat("What should I restock?")

        self.assertEqual(result["intent"], "INVENTORY")
        self.assertEqual(result["sources"], ["smart_inventory", "forecasting"])
        self.assertIn("Biscuits", result["answer"])
        self.assertIn("40 units", result["answer"])
        self.assertIn("inventory", result["supporting_data"])
        self.assertIn("forecast", result["supporting_data"])

    def test_forecasting_question_routing(self) -> None:
        result = copilot().chat("What will sell this weekend?")

        self.assertEqual(result["intent"], "FORECAST")
        self.assertEqual(result["sources"], ["forecasting"])
        self.assertIn("Rs 7000", result["answer"])
        self.assertIn("Snacks", result["answer"])

    def test_customer_question_routing(self) -> None:
        result = copilot().chat("Who are my best customers?")

        self.assertEqual(result["intent"], "CUSTOMERS")
        self.assertEqual(result["sources"], ["customer_intelligence"])
        self.assertIn("4 high-value customers", result["answer"])

    def test_business_health_combines_existing_services(self) -> None:
        result = copilot().chat("How is my business doing?")

        self.assertEqual(result["intent"], "BUSINESS_RECOMMENDATION")
        self.assertEqual(
            result["sources"],
            ["sales_analytics", "smart_inventory", "forecasting", "customer_intelligence"],
        )
        self.assertIn("Healthy", result["answer"])

    def test_general_business_question_is_clearly_general_advice(self) -> None:
        result = copilot().chat("How can I improve my store?")

        self.assertEqual(result["intent"], "BUSINESS_RECOMMENDATION")
        self.assertEqual(
            result["sources"],
            ["sales_analytics", "smart_inventory", "forecasting", "customer_intelligence"],
        )
        self.assertIn("business health", result["answer"])

    def test_unknown_question_returns_safe_unknown_without_sources(self) -> None:
        result = copilot().chat("Can you predict lottery numbers?")

        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertEqual(result["supporting_data"], {})
        self.assertEqual(result["sources"], [])
        self.assertIn("I don't have enough business data", result["answer"])

    def test_multi_service_question_calls_all_relevant_sources(self) -> None:
        result = copilot().chat("What should I stock this weekend and which customers should I target?")

        self.assertEqual(result["intent"], "INVENTORY")
        self.assertIn("INVENTORY", result["supporting_data"])
        self.assertIn("FORECAST", result["supporting_data"])
        self.assertIn("CUSTOMERS", result["supporting_data"])
        self.assertEqual(result["sources"], ["smart_inventory", "forecasting", "customer_intelligence"])

    def test_empty_message_is_invalid_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "message must not be empty"):
            copilot().chat("   ")

    def test_missing_business_data_returns_no_data_message(self) -> None:
        result = copilot(empty=True).chat("How are my sales?")

        self.assertEqual(result["intent"], "SALES_ANALYTICS")
        self.assertIn("I don't have enough business data", result["answer"])

    def test_ai_provider_unavailable_uses_deterministic_fallback(self) -> None:
        result = copilot(ai_provider="sarvam", ai_api_key=None).chat("How can I increase my sales?")

        self.assertFalse(result["provider_status"]["configured"])
        self.assertFalse(result["provider_status"]["used"])
        self.assertEqual(result["provider_status"]["fallback"], "deterministic_template")
        self.assertIn("ANSWER:", result["answer"])

    def test_response_structure_source_attribution_and_followups(self) -> None:
        result = copilot().chat("What should I restock?")

        self.assertIn("ANSWER:", result["answer"])
        self.assertIn("WHY:", result["answer"])
        self.assertIn("ACTION:", result["answer"])
        self.assertEqual(result["sources"], ["smart_inventory", "forecasting"])
        self.assertTrue(result["recommendations"])
        self.assertTrue(result["suggested_followups"])

    def test_no_hallucinated_numbers_when_data_missing(self) -> None:
        result = copilot(empty=True).chat("What will sell this weekend?")

        self.assertNotIn("7000", result["answer"])
        self.assertNotIn("350", result["answer"])
        self.assertIn("I don't have enough business data", result["answer"])

    def test_followup_question_reuses_previous_context(self) -> None:
        service = copilot()
        service.chat("What should I restock?")
        result = service.chat("How much?")

        self.assertEqual(result["intent"], "INVENTORY")
        self.assertIn("40 units", result["answer"])

    def test_detect_intents_is_explainable_and_multi_service(self) -> None:
        self.assertEqual(detect_intents("How are my sales?"), [BusinessIntent.SALES_ANALYTICS])
        self.assertEqual(
            detect_intents("What should I stock this weekend and which customers should I target?"),
            [
                BusinessIntent.INVENTORY,
                BusinessIntent.FORECAST,
                BusinessIntent.CUSTOMERS,
            ],
        )

    def test_api_chat_returns_sources(self) -> None:
        app.dependency_overrides[get_business_ai_service] = copilot
        client = TestClient(app)

        response = client.post("/api/ai/chat", json={"message": "What should I restock?", "language": "en"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "INVENTORY")
        self.assertEqual(response.json()["sources"], ["smart_inventory", "forecasting"])
        self.assertIn("answer", response.json())
        self.assertIn("supporting_data", response.json())
        self.assertIn("recommendations", response.json())


if __name__ == "__main__":
    main()
