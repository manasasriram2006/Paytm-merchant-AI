from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .customer_intelligence_service import CustomerIntelligenceService
from .data_service import DataService
from .forecasting_service import ForecastingService
from .smart_inventory_service import SmartInventoryService


MAX_AUDIO_BYTES = 10 * 1024 * 1024
SUPPORTED_AUDIO_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/aac",
    "audio/ogg",
    "audio/opus",
    "audio/flac",
    "audio/mp4",
    "audio/m4a",
    "audio/amr",
    "audio/x-ms-wma",
    "audio/webm",
    "video/mp4",
    "video/webm",
}
LANGUAGE_CODES = {
    "en": "en-IN",
    "en-in": "en-IN",
    "english": "en-IN",
    "hi": "hi-IN",
    "hi-in": "hi-IN",
    "hindi": "hi-IN",
    "te": "te-IN",
    "te-in": "te-IN",
    "telugu": "te-IN",
}
SHORT_LANGUAGE_CODES = {"en-IN": "en", "hi-IN": "hi", "te-IN": "te"}


class VoiceAIError(RuntimeError):
    status_code = 500


class SarvamNotConfiguredError(VoiceAIError):
    status_code = 503


class SarvamProviderError(VoiceAIError):
    status_code = 502


class InvalidAudioError(VoiceAIError):
    status_code = 400


class UnsupportedLanguageError(VoiceAIError):
    status_code = 400


class EmptyTranscriptionError(VoiceAIError):
    status_code = 422


class BusinessIntent(StrEnum):
    SALES_ANALYTICS = "SALES_ANALYTICS"
    INVENTORY_RECOMMENDATION = "INVENTORY_RECOMMENDATION"
    DEMAND_FORECAST = "DEMAND_FORECAST"
    CUSTOMER_INSIGHTS = "CUSTOMER_INSIGHTS"
    BUSINESS_HEALTH = "BUSINESS_HEALTH"
    GENERAL_BUSINESS = "GENERAL_BUSINESS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AudioPayload:
    filename: str
    content_type: str
    content: bytes


@dataclass(frozen=True)
class SarvamClient:
    api_key: str | None
    base_url: str = "https://api.sarvam.ai"
    timeout_seconds: int = 30

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def health(self) -> dict[str, bool]:
        configured = self.configured
        return {
            "sarvam_configured": configured,
            "transcription_available": configured,
            "tts_available": configured,
        }

    def transcribe(self, audio: AudioPayload, language: str | None = None) -> dict[str, Any]:
        self._require_configured()
        language_code = normalize_language(language) if language else "unknown"
        body, content_type = _multipart_body(
            {
                "model": "saaras:v3",
                "mode": "transcribe",
                "language_code": language_code,
            },
            audio,
        )
        data = self._request_json("/speech-to-text", body, content_type)
        text = str(data.get("transcript") or "").strip()
        if not text:
            raise EmptyTranscriptionError("Sarvam returned an empty transcription.")
        provider_language = data.get("language_code") or language_code
        return {
            "text": text,
            "language": short_language(provider_language),
            "confidence": data.get("language_probability"),
        }

    def synthesize(self, text: str, language: str | None = None) -> tuple[bytes, str]:
        self._require_configured()
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text must not be empty")
        language_code = normalize_language(language)
        payload = {
            "text": clean_text,
            "language_code": language_code,
            "model": "bulbul:v3",
            "speaker": "shubh",
            "output_audio_codec": "wav",
        }
        body = json.dumps(payload).encode("utf-8")
        data = self._request_json("/text-to-speech", body, "application/json")
        audios = data.get("audios") or []
        if not audios:
            raise SarvamProviderError("Sarvam did not return synthesized audio.")
        try:
            return base64.b64decode("".join(audios)), "audio/wav"
        except (ValueError, TypeError) as exc:
            raise SarvamProviderError("Sarvam returned malformed synthesized audio.") from exc

    def _require_configured(self) -> None:
        if not self.configured:
            raise SarvamNotConfiguredError("SARVAM_API_KEY is not configured. Set it to enable voice transcription and TTS.")

    def _request_json(self, path: str, body: bytes, content_type: str) -> dict[str, Any]:
        url = urllib.parse.urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "api-subscription-key": self.api_key or "",
                "content-type": content_type,
                "accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SarvamProviderError(f"Sarvam request failed with status {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SarvamProviderError("Sarvam request failed. Please retry later.") from exc


@dataclass(frozen=True)
class BusinessAIService:
    data_service: DataService
    forecasting_service: ForecastingService
    inventory_service: SmartInventoryService
    customer_service: CustomerIntelligenceService

    def chat(self, message: str, language: str | None = "en") -> dict[str, Any]:
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("message must not be empty")
        normalize_language(language)
        intent = detect_intent(clean_message)
        data = self._route(intent)
        response = self._respond(intent, data)
        return {"response": response, "intent": intent.value, "data": data}

    def voice_query(self, transcript: str, language: str | None = "en") -> dict[str, Any]:
        result = self.chat(transcript, language)
        return {
            "transcript": transcript,
            "language": short_language(normalize_language(language)),
            "intent": result["intent"],
            "response": result["response"],
            "data": result["data"],
        }

    def _route(self, intent: BusinessIntent) -> dict[str, Any]:
        if intent == BusinessIntent.SALES_ANALYTICS:
            return self.data_service.summary()
        if intent == BusinessIntent.INVENTORY_RECOMMENDATION:
            return self.inventory_service.recommendations()
        if intent == BusinessIntent.DEMAND_FORECAST:
            return self.forecasting_service.forecast(7)
        if intent == BusinessIntent.CUSTOMER_INSIGHTS:
            return {
                "summary": self.customer_service.summary(),
                "recommendations": self.customer_service.recommendations(5),
            }
        if intent == BusinessIntent.BUSINESS_HEALTH:
            return self.data_service.business_health()
        if intent == BusinessIntent.GENERAL_BUSINESS:
            return {
                "guidance": [
                    "Track daily sales and compare them with recent averages.",
                    "Restock products before stock coverage falls below supplier lead time.",
                    "Follow up with high-value and at-risk customers.",
                ]
            }
        return {}

    def _respond(self, intent: BusinessIntent, data: dict[str, Any]) -> str:
        if intent == BusinessIntent.SALES_ANALYTICS:
            total = data.get("totalSales")
            latest = data.get("latestDaySales")
            trend = data.get("sevenDayTrendPct")
            return f"You have sold Rs {total} in total. The latest day was Rs {latest}, with a {trend}% recent trend. Watch this trend and plan stock around stronger sales days."
        if intent == BusinessIntent.INVENTORY_RECOMMENDATION:
            items = data.get("items", [])
            if not items:
                return "I do not see any products requiring reorder right now. Keep monitoring stock against demand."
            top = items[0]
            return (
                f"Restock {top.get('product')} first. It has {top.get('current_stock')} units, covers about "
                f"{top.get('stock_coverage_days')} days, and the suggested order is {top.get('recommended_order_quantity')} units."
            )
        if intent == BusinessIntent.DEMAND_FORECAST:
            summary = data.get("summary") or {}
            category = (data.get("category_forecast") or [{}])[0]
            category_text = f" {category.get('category')} has the highest category demand." if category.get("category") else ""
            return (
                f"The next 7 days are expected to bring about Rs {summary.get('expected_revenue')} in sales "
                f"and {summary.get('expected_units')} units.{category_text} Use this to prepare inventory."
            )
        if intent == BusinessIntent.CUSTOMER_INSIGHTS:
            summary = data.get("summary") or {}
            return (
                f"You have {summary.get('high_value_customers')} high-value customers and "
                f"{summary.get('at_risk_customers')} at-risk customers. Retain high-value buyers and follow up with inactive repeat customers."
            )
        if intent == BusinessIntent.BUSINESS_HEALTH:
            drivers = data.get("drivers") or []
            driver = drivers[0]["detail"] if drivers else "review sales, stock, and repeat customers"
            return f"Your business health is {data.get('label')} with a score of {data.get('score')}. Main signal: {driver}. Act on the weakest driver first."
        if intent == BusinessIntent.GENERAL_BUSINESS:
            return "Start with the basics: review sales momentum, reorder fast-moving items, and follow up with valuable customers who have gone quiet."
        return "I could not match this to a business data question. Ask about sales, stock, demand forecast, customers, or business health."


def validate_audio(filename: str | None, content_type: str | None, content: bytes) -> AudioPayload:
    if not filename:
        raise InvalidAudioError("An audio file is required.")
    if not content:
        raise InvalidAudioError("Uploaded audio is empty.")
    if len(content) > MAX_AUDIO_BYTES:
        raise InvalidAudioError(f"Audio file is too large. Maximum size is {MAX_AUDIO_BYTES // (1024 * 1024)} MB.")

    guessed_type = content_type or mimetypes.guess_type(filename)[0] or ""
    if guessed_type not in SUPPORTED_AUDIO_TYPES:
        raise InvalidAudioError("Unsupported audio type. Upload WAV, MP3, AAC, OGG, FLAC, MP4/M4A, AMR, WMA, or WebM audio.")
    return AudioPayload(filename=filename, content_type=guessed_type, content=content)


def normalize_language(language: str | None) -> str:
    key = (language or "en").strip().casefold()
    if key not in LANGUAGE_CODES:
        raise UnsupportedLanguageError("Unsupported language. Supported languages are English, Hindi, and Telugu.")
    return LANGUAGE_CODES[key]


def short_language(language_code: str | None) -> str:
    return SHORT_LANGUAGE_CODES.get(str(language_code or "").strip(), "en")


def detect_intent(message: str) -> BusinessIntent:
    text = message.casefold()
    if any(term in text for term in ["restock", "running low", "low stock", "inventory", "reorder", "stock"]):
        return BusinessIntent.INVENTORY_RECOMMENDATION
    if any(term in text for term in ["forecast", "will sell", "demand", "weekend", "tomorrow", "next week"]):
        return BusinessIntent.DEMAND_FORECAST
    if any(term in text for term in ["best customer", "customers", "inactive", "loyal", "high value", "at risk"]):
        return BusinessIntent.CUSTOMER_INSIGHTS
    if any(term in text for term in ["health", "business doing", "improving", "performance", "score"]):
        return BusinessIntent.BUSINESS_HEALTH
    if any(term in text for term in ["sales", "sell recently", "sold", "revenue", "income", "transaction"]):
        return BusinessIntent.SALES_ANALYTICS
    if any(term in text for term in ["advice", "suggest", "help", "grow", "improve"]):
        return BusinessIntent.GENERAL_BUSINESS
    return BusinessIntent.UNKNOWN


def _multipart_body(fields: dict[str, str], audio: AudioPayload) -> tuple[bytes, str]:
    boundary = "----paytm-business-ai-voice-boundary"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                f"{value}\r\n".encode("utf-8"),
            ]
        )
    parts.extend(
        [
            f"--{boundary}\r\n".encode("utf-8"),
            f'Content-Disposition: form-data; name="file"; filename="{audio.filename}"\r\n'.encode("utf-8"),
            f"Content-Type: {audio.content_type}\r\n\r\n".encode("utf-8"),
            audio.content,
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ]
    )
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"
