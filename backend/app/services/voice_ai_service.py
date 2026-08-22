from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .ai_provider import AIProvider, DeterministicAIProvider
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
    INVENTORY = "INVENTORY"
    FORECAST = "FORECAST"
    CUSTOMERS = "CUSTOMERS"
    BUSINESS_RECOMMENDATION = "BUSINESS_RECOMMENDATION"
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


@dataclass
class BusinessAIService:
    data_service: DataService
    forecasting_service: ForecastingService
    inventory_service: SmartInventoryService
    customer_service: CustomerIntelligenceService
    ai_provider: AIProvider = field(default_factory=DeterministicAIProvider)
    _last_context: dict[str, Any] | None = field(default=None, init=False, repr=False)

    def chat(self, message: str, language: str | None = "en", conversation_id: str | None = None) -> dict[str, Any]:
        clean_message = message.strip()
        if not clean_message:
            raise ValueError("message must not be empty")
        response_language = short_language(normalize_language(language))
        intents = detect_intents(clean_message, self._last_context)
        data, sources = self._route_many(intents)
        answer = self._respond_many(intents, data, sources, response_language)
        primary_intent = intents[0] if intents else BusinessIntent.UNKNOWN
        recommendations = self._recommendations_many(intents, data)
        result = {
            "answer": answer,
            "intent": primary_intent.value,
            "supporting_data": data,
            "recommendations": recommendations,
            "conversation_id": conversation_id,
            "provider_status": self._ai_provider_status(),
            "sources": sources,
            "suggested_followups": suggested_followups(intents),
        }
        self._last_context = {"message": clean_message, "intents": intents, "data": data, "sources": sources}
        return result

    def voice_query(self, transcript: str, language: str | None = "en") -> dict[str, Any]:
        result = self.chat(transcript, language)
        return {
            "transcript": transcript,
            "language": short_language(normalize_language(language)),
            "intent": result["intent"],
            "response": result["answer"],
            "data": result["supporting_data"],
            "sources": result["sources"],
        }

    def _route_many(self, intents: list[BusinessIntent]) -> tuple[dict[str, Any], list[str]]:
        data: dict[str, Any] = {}
        sources: list[str] = []
        for intent in intents:
            routed_data, routed_sources = self._route(intent)
            if intent == BusinessIntent.UNKNOWN:
                continue
            data[intent.value] = routed_data
            for source in routed_sources:
                if source not in sources:
                    sources.append(source)
        if len(intents) == 1 and intents[0] != BusinessIntent.UNKNOWN:
            return data[intents[0].value], sources
        return data, sources

    def _route(self, intent: BusinessIntent) -> tuple[dict[str, Any], list[str]]:
        if intent == BusinessIntent.SALES_ANALYTICS:
            return self.data_service.summary(), ["sales_analytics", "transaction_analytics"]
        if intent == BusinessIntent.INVENTORY:
            return {
                "inventory": self.inventory_service.recommendations(),
                "forecast": self.forecasting_service.forecast(7),
            }, ["smart_inventory", "forecasting"]
        if intent == BusinessIntent.FORECAST:
            return self.forecasting_service.forecast(7), ["forecasting"]
        if intent == BusinessIntent.CUSTOMERS:
            return {
                "summary": self.customer_service.summary(),
                "recommendations": self.customer_service.recommendations(5),
            }, ["customer_intelligence"]
        if intent == BusinessIntent.BUSINESS_RECOMMENDATION:
            inventory_summary = (
                self.inventory_service.summary()
                if hasattr(self.inventory_service, "summary")
                else {"products_requiring_reorder": 0}
            )
            low_stock_count = inventory_summary.get("products_requiring_reorder", 0)
            try:
                health = self.data_service.business_health(low_stock_count)
            except TypeError:
                health = self.data_service.business_health()
            return {
                "health": health,
                "inventory_summary": inventory_summary,
                "inventory_recommendations": self.inventory_service.recommendations(),
                "forecast": self.forecasting_service.forecast(7),
                "customer_summary": self.customer_service.summary(),
                "customer_recommendations": self.customer_service.recommendations(5),
            }, ["sales_analytics", "smart_inventory", "forecasting", "customer_intelligence"]
        return {}, []

    def _respond(self, intent: BusinessIntent, data: dict[str, Any]) -> str:
        if intent == BusinessIntent.SALES_ANALYTICS:
            total = data.get("totalSales")
            latest = data.get("latestDaySales")
            trend = data.get("sevenDayTrendPct")
            if None in {total, latest, trend}:
                return not_enough_data_response()
            return sectioned_response(
                f"Your total sales are Rs {total}, and the latest day recorded Rs {latest}.",
                f"The sales summary shows a {trend}% seven-day trend.",
                "Plan stock and offers around categories that are already moving well.",
            )
        if intent == BusinessIntent.INVENTORY:
            inventory = data.get("inventory") or data
            items = inventory.get("items", [])
            if not items:
                return sectioned_response(
                    "I do not see any products requiring reorder right now.",
                    "Smart Inventory did not return reorder recommendations.",
                    "Keep monitoring stock coverage and update inventory after purchases or invoice scans.",
                )
            top = items[0]
            product = top.get("product")
            current_stock = top.get("current_stock")
            coverage = top.get("stock_coverage_days")
            order_qty = top.get("recommended_order_quantity")
            if None in {product, current_stock, order_qty}:
                return not_enough_data_response()
            why = f"Smart Inventory shows {current_stock} units in stock"
            if coverage is not None:
                why += f" with about {coverage} days of coverage"
            if data.get("forecast"):
                why += ", and the forecast service was checked for demand context"
            return sectioned_response(
                f"Restock {product} first.",
                f"{why}.",
                f"Consider ordering approximately {order_qty} units.",
            )
        if intent == BusinessIntent.FORECAST:
            summary = data.get("summary") or data.get("historical_summary") or {}
            category = (data.get("category_forecast") or [{}])[0]
            expected_revenue = summary.get("expected_revenue")
            expected_units = summary.get("expected_units")
            category_name = category.get("category")
            category_demand = category.get("forecast_demand") or category.get("predicted_units") or category.get("expected_units")
            if expected_revenue is None and expected_units is None and not category_name:
                return not_enough_data_response()
            answer_parts = []
            if expected_revenue is not None:
                answer_parts.append(f"Rs {expected_revenue} in sales")
            if expected_units is not None:
                answer_parts.append(f"{expected_units} units")
            answer = "The next 7 days forecast expects " + " and ".join(answer_parts) + "." if answer_parts else f"{category_name} is the strongest forecast category."
            why = "This comes from the existing demand forecast."
            action = f"Prepare extra stock for {category_name}." if category_name and category_demand is None else f"Prepare for about {category_demand} units in {category_name}." if category_name else "Use the forecast to plan purchases before demand peaks."
            return sectioned_response(answer, why, action)
        if intent == BusinessIntent.CUSTOMERS:
            summary = data.get("summary") or {}
            high_value = summary.get("high_value_customers")
            at_risk = summary.get("at_risk_customers")
            if high_value is None and at_risk is None:
                return not_enough_data_response()
            return sectioned_response(
                f"You have {high_value} high-value customers and {at_risk} at-risk customers.",
                "Customer Intelligence segmented customers using purchase history.",
                "Retain high-value buyers and follow up with inactive repeat customers.",
            )
        if intent == BusinessIntent.BUSINESS_RECOMMENDATION:
            health = data.get("health") or data
            drivers = health.get("drivers") or []
            driver = drivers[0]["detail"] if drivers else "review sales, stock, and repeat customers"
            score = health.get("score")
            label = health.get("label")
            if score is None or label is None:
                return not_enough_data_response()
            return sectioned_response(
                f"Your business health is {label} with a score of {score}.",
                f"Main signal: {driver}.",
                "Focus first on the weakest driver across sales, stock, or repeat customers.",
            )
        return sectioned_response(
            "I don't have enough business data to answer that yet.",
            "I could not match the question to sales, inventory, forecast, customer, or business recommendation workflows.",
            "Ask about sales, stock, demand forecast, customers, or what to focus on today.",
        )

    def _respond_many(
        self,
        intents: list[BusinessIntent],
        data: dict[str, Any],
        sources: list[str],
        language: str,
    ) -> str:
        if not intents or intents == [BusinessIntent.UNKNOWN]:
            return self._respond(BusinessIntent.UNKNOWN, {})
        if len(intents) == 1:
            return self._respond(intents[0], data)
        answers = []
        why = f"Used: {', '.join(sources)}." if sources else "Used available backend intelligence."
        actions = []
        for intent in intents:
            intent_data = data.get(intent.value, {})
            summary = self._compact_answer(intent, intent_data)
            if summary:
                answers.append(summary["answer"])
                actions.append(summary["action"])
        if not answers:
            return not_enough_data_response()
        return sectioned_response(" ".join(answers), why, " ".join(actions))

    def _compact_answer(self, intent: BusinessIntent, data: dict[str, Any]) -> dict[str, str] | None:
        if intent == BusinessIntent.INVENTORY:
            inventory = data.get("inventory") or data
            items = inventory.get("items") or []
            if not items:
                return {"answer": "No reorder item is currently recommended.", "action": "Keep inventory updated after purchases."}
            top = items[0]
            product = top.get("product")
            quantity = top.get("recommended_order_quantity")
            if product is None or quantity is None:
                return None
            return {"answer": f"Restock {product}.", "action": f"Order approximately {quantity} units of {product}."}
        if intent == BusinessIntent.FORECAST:
            category = (data.get("category_forecast") or [{}])[0]
            if category.get("category"):
                return {"answer": f"{category['category']} is important in the forecast.", "action": f"Prepare stock for {category['category']}."}
            return None
        if intent == BusinessIntent.CUSTOMERS:
            summary = data.get("summary") or {}
            at_risk = summary.get("at_risk_customers")
            high_value = summary.get("high_value_customers")
            if at_risk is None or high_value is None:
                return None
            return {"answer": f"{high_value} high-value customers and {at_risk} at-risk customers need attention.", "action": "Target high-value and inactive repeat customers."}
        if intent == BusinessIntent.SALES_ANALYTICS:
            total = data.get("totalSales")
            if total is None:
                return None
            return {"answer": f"Total sales are Rs {total}.", "action": "Use recent sales movement to choose offers and stock."}
        if intent == BusinessIntent.BUSINESS_RECOMMENDATION:
            health = data.get("health") or data
            if health.get("score") is None:
                return None
            return {"answer": f"Business health score is {health['score']}.", "action": "Work on the weakest health driver first."}
        return None

    def _ai_provider_status(self) -> dict[str, Any]:
        return {
            "provider": self.ai_provider.name,
            "configured": self.ai_provider.configured,
            "used": False,
            "fallback": "deterministic_template",
            "message": (
                "AI provider is configured but deterministic data-grounded responses are currently used."
                if self.ai_provider.configured
                else "SARVAM_API_KEY is not configured; deterministic data-grounded responses are being used."
            ),
        }

    def _recommendations_many(self, intents: list[BusinessIntent], data: dict[str, Any]) -> list[dict[str, str]]:
        if not intents or intents == [BusinessIntent.UNKNOWN]:
            return []
        if len(intents) == 1:
            return self._recommendations(intents[0], data)
        recommendations: list[dict[str, str]] = []
        for intent in intents:
            recommendations.extend(self._recommendations(intent, data.get(intent.value, {})))
        return recommendations[:8]

    def _recommendations(self, intent: BusinessIntent, data: dict[str, Any]) -> list[dict[str, str]]:
        if intent == BusinessIntent.INVENTORY:
            inventory = data.get("inventory") or data
            items = inventory.get("items") or []
            recommendations = []
            for item in items[:5]:
                product = str(item.get("product") or "Product")
                risk = str(item.get("risk_level") or "HIGH")
                quantity = item.get("recommended_order_quantity")
                action = f"Review the recommended reorder quantity of {quantity} units." if quantity is not None else "Review stock and reorder policy."
                recommendations.append(
                    {
                        "priority": risk if risk in {"HIGH", "MEDIUM", "LOW"} else "HIGH",
                        "category": "INVENTORY",
                        "title": f"Restock {product}",
                        "reason": str(item.get("reason") or "Projected demand is higher than available stock."),
                        "action": action,
                    }
                )
            return recommendations
        if intent == BusinessIntent.FORECAST:
            categories = data.get("category_forecast") or []
            if not categories:
                return []
            top = categories[0]
            category = str(top.get("category") or "top category")
            demand = top.get("forecast_demand")
            reason = f"Forecast demand is {demand} units for {category}." if demand is not None else f"{category} leads the forecast."
            return [
                {
                    "priority": "MEDIUM",
                    "category": "FORECAST",
                    "title": f"Prepare for {category} demand",
                    "reason": reason,
                    "action": "Use the forecast before finalizing purchases and staffing.",
                }
            ]
        if intent == BusinessIntent.CUSTOMERS:
            items = (data.get("recommendations") or {}).get("items") or []
            return [
                {
                    "priority": str(item.get("priority") or "MEDIUM"),
                    "category": "CUSTOMERS",
                    "title": f"Follow up with {item.get('customer_id', 'customer')}",
                    "reason": str(item.get("reason") or "Customer Intelligence identified an action opportunity."),
                    "action": str(item.get("recommended_action") or "Review this customer before sending an offer."),
                }
                for item in items[:5]
            ]
        if intent == BusinessIntent.BUSINESS_RECOMMENDATION:
            recommendations = []
            recommendations.extend(self._recommendations(BusinessIntent.INVENTORY, {"inventory": data.get("inventory_recommendations", {})})[:2])
            recommendations.extend(self._recommendations(BusinessIntent.FORECAST, data.get("forecast", {}))[:1])
            recommendations.extend(
                self._recommendations(
                    BusinessIntent.CUSTOMERS,
                    {"recommendations": data.get("customer_recommendations", {})},
                )[:2]
            )
            if not recommendations:
                recommendations.append(
                    {
                        "priority": "MEDIUM",
                        "category": "BUSINESS_RECOMMENDATION",
                        "title": "Review business health drivers",
                        "reason": "Business health combines sales, stock, forecast, and customer signals.",
                        "action": "Focus first on the lowest scoring driver.",
                    }
                )
            return recommendations
        if intent == BusinessIntent.SALES_ANALYTICS:
            trend = data.get("sevenDayTrendPct")
            return [
                {
                    "priority": "MEDIUM",
                    "category": "SALES_ANALYTICS",
                    "title": "Review recent sales movement",
                    "reason": f"Seven-day sales trend is {trend}%." if trend is not None else "Sales analytics are available for review.",
                    "action": "Compare fast-selling categories with stock before placing purchase orders.",
                }
            ]
        return []


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
    return detect_intents(message)[0]


def detect_intents(message: str, previous_context: dict[str, Any] | None = None) -> list[BusinessIntent]:
    text = message.casefold()
    if any(
        term in text
        for term in [
            "what should i do today",
            "what should i focus on",
            "focus on today",
            "how can i increase",
            "how can i improve",
            "how can i grow",
            "reduce wastage",
            "improve my store",
        ]
    ):
        return [BusinessIntent.BUSINESS_RECOMMENDATION]
    intents: list[BusinessIntent] = []
    keyword_groups = [
        (
            BusinessIntent.INVENTORY,
            ["restock", "running low", "low stock", "inventory", "reorder", "stock", "overstock"],
        ),
        (
            BusinessIntent.FORECAST,
            ["forecast", "will sell", "demand", "weekend", "tomorrow", "next week", "prepare"],
        ),
        (
            BusinessIntent.CUSTOMERS,
            ["best customer", "customers", "inactive", "loyal", "high value", "at risk", "target", "focus on"],
        ),
        (
            BusinessIntent.BUSINESS_RECOMMENDATION,
            ["health", "business doing", "improving", "performance", "score", "focus on"],
        ),
        (
            BusinessIntent.SALES_ANALYTICS,
            ["sales", "sell recently", "sold", "revenue", "income", "transaction", "category is selling"],
        ),
    ]
    for intent, keywords in keyword_groups:
        if any(term in text for term in keywords):
            intents.append(intent)
    if intents:
        return _dedupe_intents(intents)
    if _is_followup_quantity_question(text, previous_context):
        prior_intents = previous_context.get("intents") or []
        if prior_intents:
            return list(prior_intents)
    if any(term in text for term in ["advice", "suggest", "help", "grow", "improve", "reduce wastage"]):
        return [BusinessIntent.BUSINESS_RECOMMENDATION]
    return [BusinessIntent.UNKNOWN]


def sectioned_response(answer: str, why: str, action: str) -> str:
    return f"ANSWER:\n{answer}\n\nWHY:\n{why}\n\nACTION:\n{action}"


def not_enough_data_response() -> str:
    return sectioned_response(
        "I don't have enough business data to answer that yet.",
        "The connected service did not return the required fields.",
        "Try asking about sales, stock, demand forecast, customers, or business health after data is available.",
    )


def suggested_followups(intents: list[BusinessIntent]) -> list[str]:
    if BusinessIntent.INVENTORY in intents:
        return ["Why is this product recommended?", "Show me my inventory risks.", "What will sell this weekend?"]
    if BusinessIntent.FORECAST in intents:
        return ["Which category has the highest demand?", "What should I restock?", "How are my sales?"]
    if BusinessIntent.CUSTOMERS in intents:
        return ["Who are my at-risk customers?", "Who are my best customers?", "What action should I take next?"]
    if BusinessIntent.SALES_ANALYTICS in intents:
        return ["Which category is selling the most?", "How is my business doing?", "What should I restock?"]
    if BusinessIntent.BUSINESS_RECOMMENDATION in intents:
        return ["What should I focus on first?", "Show me inventory risks.", "Which customers should I target?"]
    return ["How are my sales?", "What should I restock?", "Who are my best customers?"]


def _is_followup_quantity_question(text: str, previous_context: dict[str, Any] | None) -> bool:
    if not previous_context:
        return False
    compact = text.strip(" ?.!").casefold()
    return compact in {"how much", "how many", "quantity", "how much should i order", "how many should i order"}


def _dedupe_intents(intents: list[BusinessIntent]) -> list[BusinessIntent]:
    deduped: list[BusinessIntent] = []
    for intent in intents:
        if intent not in deduped:
            deduped.append(intent)
    return deduped


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
