from __future__ import annotations

from dataclasses import dataclass
from unittest import TestCase, main

from fastapi.testclient import TestClient

from app.main import app, get_business_ai_service, get_sarvam_client
from app.services.voice_ai_service import (
    BusinessAIService,
    BusinessIntent,
    SarvamClient,
    SarvamProviderError,
    detect_intent,
    normalize_language,
    validate_audio,
)


@dataclass(frozen=True)
class StubDataService:
    def summary(self) -> dict:
        return {"totalSales": 1000, "latestDaySales": 150, "sevenDayTrendPct": 5.5}

    def business_health(self) -> dict:
        return {"score": 82, "label": "Healthy", "drivers": [{"detail": "Sales momentum is positive"}]}


@dataclass(frozen=True)
class StubForecastingService:
    def forecast(self, horizon: int = 7) -> dict:
        return {
            "summary": {"expected_revenue": 2100, "expected_units": 300},
            "category_forecast": [{"category": "Dairy", "forecast_demand": 90}],
            "forecast": [],
        }


@dataclass(frozen=True)
class StubInventoryService:
    def recommendations(self) -> dict:
        return {
            "items": [
                {
                    "product": "Milk 500ml",
                    "current_stock": 8,
                    "stock_coverage_days": 1.2,
                    "recommended_order_quantity": 40,
                }
            ],
            "count": 1,
        }


@dataclass(frozen=True)
class StubCustomerService:
    def summary(self) -> dict:
        return {"high_value_customers": 3, "at_risk_customers": 2}

    def recommendations(self, limit: int = 5) -> dict:
        return {"items": [{"customer_id": "C1", "priority": "HIGH"}]}


class FakeSarvamClient:
    def __init__(self, text: str = "What should I restock?", fail: bool = False) -> None:
        self.text = text
        self.fail = fail

    def health(self) -> dict:
        return {"sarvam_configured": True, "transcription_available": True, "tts_available": True}

    def transcribe(self, audio, language=None) -> dict:
        if self.fail:
            raise SarvamProviderError("Sarvam request failed. Please retry later.")
        return {"text": self.text, "language": language or "en", "confidence": None}

    def synthesize(self, text: str, language: str = "en") -> tuple[bytes, str]:
        if self.fail:
            raise SarvamProviderError("Sarvam request failed. Please retry later.")
        return b"RIFFfake", "audio/wav"


def business_ai() -> BusinessAIService:
    return BusinessAIService(StubDataService(), StubForecastingService(), StubInventoryService(), StubCustomerService())


class VoiceAIServiceTests(TestCase):
    def tearDown(self) -> None:
        app.dependency_overrides.clear()

    def test_missing_api_key_health_and_transcribe_error_do_not_leak_key(self) -> None:
        client = TestClient(app)
        app.dependency_overrides[get_sarvam_client] = lambda: SarvamClient(None)

        health = client.get("/api/voice/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(
            health.json(),
            {"sarvam_configured": False, "transcription_available": False, "tts_available": False},
        )

        response = client.post(
            "/api/voice/transcribe",
            files={"file": ("question.wav", b"audio-bytes", "audio/wav")},
        )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SARVAM_API_KEY=", response.text)

    def test_valid_configuration_health(self) -> None:
        self.assertEqual(
            SarvamClient("test-key").health(),
            {"sarvam_configured": True, "transcription_available": True, "tts_available": True},
        )

    def test_audio_validation_rejects_invalid_empty_and_oversized_audio(self) -> None:
        with self.assertRaisesRegex(Exception, "Unsupported audio type"):
            validate_audio("notes.txt", "text/plain", b"hello")
        with self.assertRaisesRegex(Exception, "empty"):
            validate_audio("voice.wav", "audio/wav", b"")
        with self.assertRaisesRegex(Exception, "too large"):
            validate_audio("voice.wav", "audio/wav", b"0" * (10 * 1024 * 1024 + 1))

    def test_language_handling(self) -> None:
        self.assertEqual(normalize_language("en"), "en-IN")
        self.assertEqual(normalize_language("Hindi"), "hi-IN")
        self.assertEqual(normalize_language("te"), "te-IN")
        with self.assertRaisesRegex(Exception, "Unsupported language"):
            normalize_language("fr")

    def test_intent_detection(self) -> None:
        self.assertEqual(detect_intent("How are my sales?"), BusinessIntent.SALES_ANALYTICS)
        self.assertEqual(detect_intent("What should I restock?"), BusinessIntent.INVENTORY)
        self.assertEqual(detect_intent("What will sell this weekend?"), BusinessIntent.FORECAST)
        self.assertEqual(detect_intent("Who are my best customers?"), BusinessIntent.CUSTOMERS)
        self.assertEqual(detect_intent("How is my business doing?"), BusinessIntent.BUSINESS_RECOMMENDATION)
        self.assertEqual(detect_intent("Tell me something random"), BusinessIntent.UNKNOWN)

    def test_business_chat_routes_inventory_forecasting_customer_and_analytics(self) -> None:
        service = business_ai()

        self.assertEqual(service.chat("What should I restock?")["intent"], "INVENTORY")
        self.assertIn("Milk 500ml", service.chat("What should I restock?")["answer"])
        self.assertEqual(service.chat("What will sell this weekend?")["intent"], "FORECAST")
        self.assertEqual(service.chat("Who are my best customers?")["intent"], "CUSTOMERS")
        self.assertEqual(service.chat("How are my sales?")["intent"], "SALES_ANALYTICS")
        self.assertEqual(service.chat("How is my business doing?")["intent"], "BUSINESS_RECOMMENDATION")

    def test_unknown_query_returns_safe_response(self) -> None:
        result = business_ai().chat("Can you predict lottery numbers?")

        self.assertEqual(result["intent"], "UNKNOWN")
        self.assertEqual(result["supporting_data"], {})
        self.assertIn("could not match", result["answer"])

    def test_voice_transcription_and_query_endpoints_use_mocked_sarvam(self) -> None:
        app.dependency_overrides[get_sarvam_client] = lambda: FakeSarvamClient()
        app.dependency_overrides[get_business_ai_service] = business_ai
        client = TestClient(app)

        transcribe = client.post(
            "/api/voice/transcribe",
            files={"file": ("question.wav", b"audio-bytes", "audio/wav")},
        )
        self.assertEqual(transcribe.status_code, 200)
        self.assertEqual(transcribe.json()["text"], "What should I restock?")

        query = client.post(
            "/api/voice/query",
            files={"file": ("question.wav", b"audio-bytes", "audio/wav")},
        )
        self.assertEqual(query.status_code, 200)
        self.assertEqual(query.json()["intent"], "INVENTORY")

    def test_ai_chat_endpoint(self) -> None:
        app.dependency_overrides[get_business_ai_service] = business_ai
        client = TestClient(app)

        response = client.post("/api/ai/chat", json={"message": "What will sell this weekend?", "language": "en"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["intent"], "FORECAST")
        self.assertIn("answer", response.json())
        self.assertIn("supporting_data", response.json())

    def test_synthesize_endpoint_returns_audio_or_clean_error(self) -> None:
        app.dependency_overrides[get_sarvam_client] = lambda: FakeSarvamClient()
        client = TestClient(app)

        response = client.post("/api/voice/synthesize", json={"text": "Hello", "language": "en"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/wav")

        app.dependency_overrides[get_sarvam_client] = lambda: FakeSarvamClient(fail=True)
        failed = client.post("/api/voice/synthesize", json={"text": "Hello", "language": "en"})
        self.assertEqual(failed.status_code, 502)
        self.assertIn("detail", failed.json())

    def test_sarvam_failure_returns_clean_json(self) -> None:
        app.dependency_overrides[get_sarvam_client] = lambda: FakeSarvamClient(fail=True)
        client = TestClient(app)

        response = client.post(
            "/api/voice/transcribe",
            files={"file": ("question.wav", b"audio-bytes", "audio/wav")},
        )
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["detail"], "Sarvam request failed. Please retry later.")


if __name__ == "__main__":
    main()
