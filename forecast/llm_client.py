import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from sentry_sdk import capture_exception, set_context, add_breadcrumb, start_span

from .llm_context_builder import LLMContextBuilder

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Minimal OpenAI-compatible Chat Completions client using requests.

    Reads configuration (base_url, api_key, model, timeout) passed in constructor.
    Base URL defaults should be provided by Django settings (e.g., http://localhost:8000).

    Includes automatic retry logic for transient API failures.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        model: str = "ibm/granite4:tiny-h",
        timeout: float = 8.0,
        extra_payload: Optional[Dict[str, Any]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self.extra_payload = extra_payload or {}

        # Configure retry strategy for LLM API calls
        # Retry on connection errors, timeouts, and specific HTTP status codes
        retry_strategy = Retry(
            total=3,  # Total number of retries
            backoff_factor=2,  # Wait 2s, 4s, 8s between retries (longer than weather API)
            status_forcelist=[404, 429, 500, 502, 503, 504],  # Retry on these HTTP status codes
            allowed_methods=["POST"],  # Only retry POST requests (chat completions)
            raise_on_status=False,  # Don't raise exception on retry exhaustion (we handle it)
            respect_retry_after_header=True,  # Honor Retry-After header if present
        )

        # Create HTTP adapter with retry strategy
        adapter = HTTPAdapter(max_retries=retry_strategy)

        # Create session and mount adapter
        self._session = requests.Session()
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

        logger.info(f"LLMClient initialized for {self.base_url} with retry strategy: 3 retries, exponential backoff")

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat_complete(self, messages: list, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
        }
        # Merge extra_payload first, then kwargs (kwargs override extra_payload)
        payload.update(self.extra_payload)
        payload.update(kwargs)

        # Add breadcrumb for LLM call
        add_breadcrumb(
            category="llm",
            message="Calling LLM chat completion",
            level="info",
            data={
                "model": self.model,
                "base_url": self.base_url,
                "timeout": self.timeout,
                "message_count": len(messages),
            },
        )

        try:
            with start_span(op="llm.chat", description=f"LLM chat completion ({self.model})"):
                start_time = time.perf_counter()
                resp = self._session.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
                inference_time = time.perf_counter() - start_time
                resp.raise_for_status()

                add_breadcrumb(
                    category="llm",
                    message="LLM response received",
                    level="info",
                    data={"status_code": resp.status_code, "inference_time": inference_time},
                )

                result = resp.json()
                result["_inference_time"] = inference_time
                return result

        except requests.exceptions.Timeout as e:
            set_context(
                "llm_timeout", {"model": self.model, "base_url": self.base_url, "timeout": self.timeout, "url": url}
            )
            capture_exception(e)
            logger.error(f"LLM request timeout after retries: {e}")
            raise

        except requests.exceptions.HTTPError as e:
            set_context(
                "llm_http_error",
                {
                    "model": self.model,
                    "base_url": self.base_url,
                    "status_code": e.response.status_code if e.response else None,
                    "response_text": e.response.text if e.response else None,
                    "url": url,
                },
            )
            capture_exception(e)
            logger.error(f"LLM HTTP error after retries: {e}")
            raise

        except ValueError as e:
            # JSON decode error - response body is empty or not valid JSON
            set_context(
                "llm_json_error",
                {
                    "model": self.model,
                    "base_url": self.base_url,
                    "error": str(e),
                    "response_status": resp.status_code if "resp" in locals() else None,
                    "response_text": resp.text[:500] if "resp" in locals() else None,
                    "url": url,
                },
            )
            capture_exception(e)
            logger.error(f"LLM response is not valid JSON: {e}")
            raise

        except Exception as e:
            set_context(
                "llm_error",
                {"model": self.model, "base_url": self.base_url, "error_type": type(e).__name__, "url": url},
            )
            capture_exception(e)
            logger.error(f"LLM request error after retries: {e}")
            raise

    @staticmethod
    def _extract_json(content: str) -> Optional[Dict[str, Any]]:
        """Try to extract JSON from a content string, allowing for fenced code blocks."""
        text = content.strip()
        # Try direct JSON first
        try:
            return json.loads(text)
        except Exception:
            pass
        # Try to find a JSON code block
        if "```" in text:
            parts = text.split("```")
            for i in range(1, len(parts), 2):
                block = parts[i]
                # remove possible language hint like ```json
                block = block.split("\n", 1)[-1] if "\n" in block else block
                try:
                    return json.loads(block)
                except Exception:
                    continue
        return None

    def predict_probability(
        self,
        scores: Dict[str, float],
        location_label: str,
        user_profile: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        forecasts: Optional[List[Any]] = None,
        previous_forecasts: Optional[List[Any]] = None,
        location: Optional[Any] = None,
        high_token_budget: bool = False,
        outlook_forecasts: Optional[List[Any]] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Ask the LLM to output a JSON with keys:
          - probability_level: one of LOW, MEDIUM, HIGH
          - confidence: float 0-1
          - rationale: short string
        Returns (probability_level, raw_payload) or (None, raw_payload) on failure.

        Args:
            scores: Normalized weather scores (kept for fallback, not sent to LLM)
            location_label: Human-readable location string
            user_profile: User health profile with sensitivities
            context: Legacy context dict (deprecated, use forecasts instead)
            forecasts: List of WeatherForecast objects for prediction window
            previous_forecasts: List of WeatherForecast objects from previous period (24h ago)
            location: Location model instance
            high_token_budget: Whether to use detailed context (default: False)
            outlook_forecasts: List of WeatherForecast objects for the next 24 hours
        """
        # Determine user's preferred language
        user_language = None
        if user_profile and "language" in user_profile:
            user_language = user_profile["language"]

        # Build language instruction for LLM
        language_instruction = ""
        if user_language == "el":
            language_instruction = (
                "\nReply in Greek (Ελληνικά) for all text fields (rationale, analysis_text, prevention_tips)."
            )
        elif user_language and user_language != "en":
            language_instruction = f"\nReply in the user's language ({user_language}) for all text fields."

        # Simplified system prompt - let the model use its own medical/scientific reasoning
        sys_prompt = (
            "You are a migraine risk assessor. Analyze the weather data provided and assess "
            "migraine risk for the forecast window.\n\n"
            "Consider known migraine triggers including:\n"
            "- Rapid barometric pressure changes (especially drops)\n"
            "- Significant temperature swings beyond normal diurnal variation\n"
            "- Humidity extremes (very high or very low)\n"
            "- Approaching weather fronts and storm systems\n\n"
            "Use the user's sensitivity profile and recent weather trends as context for your assessment.\n"
            f"{language_instruction}\n"
            "Output ONLY valid JSON matching the schema below.\n"
            "<schema>\n"
            "{\n"
            '  "probability_level": "LOW" | "MEDIUM" | "HIGH",\n'
            '  "confidence": <float between 0 and 1>,\n'
            '  "rationale": "<brief 3 sentence explanation of your reasoning>",\n'
            '  "analysis_text": "<concise 3 sentence user-facing explanation>",\n'
            '  "prevention_tips": ["<tip1>", "<tip2>", ...]\n'
            "}\n"
            "</schema>"
        )

        # Build user prompt using the new context builder if forecasts are provided
        if forecasts and location:
            context_builder = LLMContextBuilder(high_token_budget=high_token_budget)
            user_prompt_str = context_builder.build_migraine_context(
                forecasts=forecasts,
                previous_forecasts=previous_forecasts or [],
                location=location,
                user_profile=user_profile,
                outlook_forecasts=outlook_forecasts or [],
            )
        else:
            # Fallback to legacy context building (for backwards compatibility)
            user_prompt_str = self._build_legacy_migraine_prompt(
                scores=scores,
                location_label=location_label,
                user_profile=user_profile,
                context=context,
            )

        # Build the actual request payload that will be sent to the LLM
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt_str},
        ]
        request_payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        # Merge extra_payload to get the actual payload that will be sent
        request_payload.update(self.extra_payload)

        # Log the full request for debugging
        logger.info(f"LLM Request for {location_label}:")
        logger.info(f"User prompt: {user_prompt_str}")
        logger.info(f"Request payload: {request_payload}")

        try:
            result = self.chat_complete(
                messages=messages,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning("LLM chat request failed: %s", e)
            return None, {"error": str(e), "request_payload": request_payload}

        try:
            inference_time = result.pop("_inference_time", None)
            choices = result.get("choices", [])
            content = (choices[0]["message"]["content"] if choices else "").strip()
            parsed = self._extract_json(content) if content else None
            if not parsed:
                logger.warning("LLM response not JSON parsable: %s", content[:200])
                return None, {"raw": result, "request_payload": request_payload, "inference_time": inference_time}
            level = parsed.get("probability_level")

            # Log the LLM response for debugging
            logger.info(f"LLM Response for {location_label}: {parsed}")

            if isinstance(level, str):
                level_up = level.strip().upper()
                if level_up in {"LOW", "MEDIUM", "HIGH"}:
                    logger.info(f"LLM classified as {level_up} for {location_label}")
                    return level_up, {"raw": parsed, "api_raw": result, "request_payload": request_payload, "inference_time": inference_time}  # noqa
            logger.warning("LLM response missing/invalid probability_level: %s", parsed)
            return None, {"raw": parsed, "api_raw": result, "request_payload": request_payload, "inference_time": inference_time}  # noqa
        except Exception:
            logger.exception("Failed to process LLM response")
            return None, {"raw": result, "request_payload": request_payload}

    def _build_legacy_migraine_prompt(
        self,
        scores: Dict[str, float],
        location_label: str,
        user_profile: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
    ) -> str:
        """Build user prompt using legacy context format (for backwards compatibility)."""
        user_prompt_parts = [f"Location: {location_label}"]

        # Add temporal context if available (compact format)
        if context and "temporal_context" in context:
            temporal = context["temporal_context"]
            time_parts = []

            if temporal.get("current_time"):
                time_parts.append(f"Now: {temporal['current_time']}")
            if temporal.get("day_of_week"):
                day_info = temporal["day_of_week"]
                if temporal.get("is_weekend"):
                    day_info += " (weekend)"
                time_parts.append(day_info)
            if temporal.get("season"):
                time_parts.append(f"{temporal['season']}")

            if temporal.get("window_start_time") and temporal.get("window_end_time"):
                time_parts.append(f"Window: {temporal['window_start_time']} to {temporal['window_end_time']}")
            elif temporal.get("window_duration_hours"):
                time_parts.append(f"Window: {temporal['window_duration_hours']:.1f}h ahead")

            if time_parts:
                user_prompt_parts.append(f"Timing: {' | '.join(time_parts)}")

        # Add key weather changes from context if available
        if context and "aggregates" in context:
            agg = context["aggregates"]
            changes = context.get("changes", {})
            weather_summary = []

            if agg.get("avg_forecast_temperature") is not None:
                temp_info = f"temp avg {agg['avg_forecast_temperature']:.1f}°C"
                if agg.get("temperature_range") is not None and agg["temperature_range"] > 0:
                    temp_info += f" (range {agg['temperature_range']:.1f}°C)"
                weather_summary.append(temp_info)

            if agg.get("avg_forecast_pressure") is not None:
                pressure_info = f"pressure avg {agg['avg_forecast_pressure']:.1f}hPa"
                if agg.get("pressure_range") is not None and agg["pressure_range"] > 0:
                    pressure_info += f" (range {agg['pressure_range']:.1f}hPa)"
                weather_summary.append(pressure_info)

            if changes.get("pressure_change"):
                weather_summary.append(f"pressure Δ{changes['pressure_change']:.1f}hPa")

            if agg.get("avg_forecast_humidity"):
                weather_summary.append(f"humidity {agg['avg_forecast_humidity']:.0f}%")

            if weather_summary:
                user_prompt_parts.append(f"Weather: {', '.join(weather_summary)}")

        # Add user sensitivity if available
        if user_profile:
            sensitivity = user_profile.get("sensitivity_overall", 1.0)
            if sensitivity != 1.0:
                user_prompt_parts.append(f"User sensitivity: {sensitivity:.1f}x")

        return "\n".join(user_prompt_parts)

    def predict_sinusitis_probability(
        self,
        scores: Dict[str, float],
        location_label: str,
        user_profile: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        forecasts: Optional[List[Any]] = None,
        previous_forecasts: Optional[List[Any]] = None,
        location: Optional[Any] = None,
        high_token_budget: bool = False,
        outlook_forecasts: Optional[List[Any]] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Ask the LLM to output a JSON with keys for sinusitis risk assessment:
          - probability_level: one of LOW, MEDIUM, HIGH
          - confidence: float 0-1
          - rationale: short string
        Returns (probability_level, raw_payload) or (None, raw_payload) on failure.

        Args:
            scores: Normalized weather scores (kept for fallback, not sent to LLM)
            location_label: Human-readable location string
            user_profile: User health profile with sensitivities
            context: Legacy context dict (deprecated, use forecasts instead)
            forecasts: List of WeatherForecast objects for prediction window
            previous_forecasts: List of WeatherForecast objects from previous period (24h ago)
            location: Location model instance
            high_token_budget: Whether to use detailed context (default: False)
            outlook_forecasts: List of WeatherForecast objects for the next 24 hours
        """
        # Determine user's preferred language
        user_language = None
        if user_profile and "language" in user_profile:
            user_language = user_profile["language"]

        # Build language instruction for LLM
        language_instruction = ""
        if user_language == "el":
            language_instruction = (
                "\nReply in Greek (Ελληνικά) for all text fields (rationale, analysis_text, prevention_tips)."
            )
        elif user_language and user_language != "en":
            language_instruction = f"\nReply in the user's language ({user_language}) for all text fields."

        # Simplified system prompt - let the model use its own medical/scientific reasoning
        sys_prompt = (
            "You are a sinusitis risk assessor. Analyze the weather data provided and assess "
            "sinusitis flare-up risk for the forecast window.\n\n"
            "Consider known sinusitis triggers including:\n"
            "- Rapid temperature changes (especially beyond normal diurnal variation)\n"
            "- Humidity extremes (high promotes mold/allergens, low dries sinuses)\n"
            "- Barometric pressure changes\n"
            "- Precipitation (increases allergens)\n"
            "- Seasonal factors (pollen season, indoor heating drying air)\n\n"
            "Use the user's sensitivity profile and recent weather trends as context for your assessment.\n"
            f"{language_instruction}\n"
            "Output ONLY valid JSON matching the schema below.\n"
            "<schema>\n"
            "{\n"
            '  "probability_level": "LOW" | "MEDIUM" | "HIGH",\n'
            '  "confidence": <float between 0 and 1>,\n'
            '  "rationale": "<brief 3 sentence explanation of your reasoning>",\n'
            '  "analysis_text": "<concise 3 sentence user-facing explanation>",\n'
            '  "prevention_tips": ["<tip1>", "<tip2>", ...]\n'
            "}\n"
            "</schema>"
        )

        # Build user prompt using the new context builder if forecasts are provided
        if forecasts and location:
            context_builder = LLMContextBuilder(high_token_budget=high_token_budget)
            user_prompt_str = context_builder.build_sinusitis_context(
                forecasts=forecasts,
                previous_forecasts=previous_forecasts or [],
                location=location,
                user_profile=user_profile,
                outlook_forecasts=outlook_forecasts or [],
            )
        else:
            # Fallback to legacy context building (for backwards compatibility)
            user_prompt_str = self._build_legacy_sinusitis_prompt(
                scores=scores,
                location_label=location_label,
                user_profile=user_profile,
                context=context,
            )

        # Build the actual request payload that will be sent to the LLM
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt_str},
        ]
        request_payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
        }
        # Merge extra_payload to get the actual payload that will be sent
        request_payload.update(self.extra_payload)

        try:
            result = self.chat_complete(
                messages=messages,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning("LLM chat request failed for sinusitis: %s", e)
            return None, {"error": str(e), "request_payload": request_payload}

        try:
            inference_time = result.pop("_inference_time", None)
            choices = result.get("choices", [])
            content = (choices[0]["message"]["content"] if choices else "").strip()
            parsed = self._extract_json(content) if content else None
            if not parsed:
                logger.warning("LLM sinusitis response not JSON parsable: %s", content[:200])
                return None, {"raw": result, "request_payload": request_payload, "inference_time": inference_time}
            level = parsed.get("probability_level")
            if isinstance(level, str):
                level_up = level.strip().upper()
                if level_up in {"LOW", "MEDIUM", "HIGH"}:
                    return level_up, {"raw": parsed, "api_raw": result, "request_payload": request_payload, "inference_time": inference_time}  # noqa
            logger.warning("LLM sinusitis response missing/invalid probability_level: %s", parsed)
            return None, {"raw": parsed, "api_raw": result, "request_payload": request_payload, "inference_time": inference_time}  # noqa
        except Exception:
            logger.exception("Failed to process LLM sinusitis response")
            return None, {"raw": result, "request_payload": request_payload}

    def _build_legacy_sinusitis_prompt(
        self,
        scores: Dict[str, float],
        location_label: str,
        user_profile: Optional[Dict[str, Any]],
        context: Optional[Dict[str, Any]],
    ) -> str:
        """Build user prompt using legacy context format (for backwards compatibility)."""
        user_prompt_parts = [f"Location: {location_label}"]

        # Add temporal context if available (compact format)
        if context and "temporal_context" in context:
            temporal = context["temporal_context"]
            time_parts = []

            if temporal.get("current_time"):
                time_parts.append(f"Now: {temporal['current_time']}")
            if temporal.get("day_of_week"):
                day_info = temporal["day_of_week"]
                if temporal.get("is_weekend"):
                    day_info += " (weekend)"
                time_parts.append(day_info)
            if temporal.get("season"):
                time_parts.append(f"{temporal['season']}")

            if temporal.get("window_start_time") and temporal.get("window_end_time"):
                time_parts.append(f"Window: {temporal['window_start_time']} to {temporal['window_end_time']}")
            elif temporal.get("window_duration_hours"):
                time_parts.append(f"Window: {temporal['window_duration_hours']:.1f}h ahead")

            if time_parts:
                user_prompt_parts.append(f"Timing: {' | '.join(time_parts)}")

        # Add key weather changes from context if available
        if context and "aggregates" in context:
            agg = context["aggregates"]
            changes = context.get("changes", {})
            weather_summary = []

            if agg.get("avg_forecast_temp") is not None:
                temp_info = f"temp avg {agg['avg_forecast_temp']:.1f}°C"
                if agg.get("temperature_range") is not None and agg["temperature_range"] > 0:
                    temp_info += f" (range {agg['temperature_range']:.1f}°C)"
                weather_summary.append(temp_info)

            if agg.get("avg_forecast_pressure") is not None:
                pressure_info = f"pressure avg {agg['avg_forecast_pressure']:.1f}hPa"
                if agg.get("pressure_range") is not None and agg["pressure_range"] > 0:
                    pressure_info += f" (range {agg['pressure_range']:.1f}hPa)"
                weather_summary.append(pressure_info)

            if changes.get("pressure_change"):
                weather_summary.append(f"pressure Δ{changes['pressure_change']:.1f}hPa")

            if agg.get("avg_forecast_humidity"):
                weather_summary.append(f"humidity {agg['avg_forecast_humidity']:.0f}%")

            if weather_summary:
                user_prompt_parts.append(f"Weather: {', '.join(weather_summary)}")

        # Add user sensitivity if available
        if user_profile:
            sensitivity = user_profile.get("sensitivity_overall", 1.0)
            if sensitivity != 1.0:
                user_prompt_parts.append(f"User sensitivity: {sensitivity:.1f}x")

        return "\n".join(user_prompt_parts)
