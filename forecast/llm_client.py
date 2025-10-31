import json
import logging
from typing import Any, Dict, Optional, Tuple

import requests

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Minimal OpenAI-compatible Chat Completions client using requests.

    Reads configuration (base_url, api_key, model, timeout) passed in constructor.
    Base URL defaults should be provided by Django settings (e.g., http://localhost:8000).
    """

    def __init__(self, base_url: str, api_key: str = "", model: str = "ibm/granite4:tiny-h", timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.model = model
        self.timeout = timeout
        self._session = requests.Session()

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
        payload.update(kwargs)
        resp = self._session.post(url, headers=self._headers(), json=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

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
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Ask the LLM to output a JSON with keys:
          - probability_level: one of LOW, MEDIUM, HIGH
          - confidence: float 0-1
          - rationale: short string
        Returns (probability_level, raw_payload) or (None, raw_payload) on failure.
        """
        # System prompt with explicit JSON output instruction and schema
        sys_prompt = (
            "You are a migraine risk assessor. Analyze weather risk factors (0-1 scale, higher=riskier) "
            "and output ONLY valid JSON matching the schema below. Do not include any text before or after the JSON.\n\n"
            "<schema>\n"
            "{\n"
            '  "probability_level": "LOW" | "MEDIUM" | "HIGH",\n'
            '  "confidence": <float between 0 and 1>,\n'
            '  "rationale": "<brief explanation>",\n'
            '  "analysis_text": "<concise user explanation>",\n'
            '  "prevention_tips": ["<tip1>", "<tip2>", ...]\n'
            "}\n"
            "</schema>"
        )

        # Build minimal user prompt with only essential data
        user_prompt_parts = [
            f"Location: {location_label}",
            f"Risk scores: {json.dumps(scores)}",
        ]

        # Add temporal context if available (compact format)
        if context and 'forecast_time' in context:
            forecast_info = context['forecast_time']
            user_prompt_parts.append(
                f"Time: {forecast_info.get('day_period', '')} {forecast_info.get('hours_ahead', '')}h ahead"
            )

        # Add user sensitivity if available
        if user_profile:
            sensitivity = user_profile.get('sensitivity_overall', 1.0)
            if sensitivity != 1.0:
                user_prompt_parts.append(f"User sensitivity: {sensitivity:.1f}x")

        # Add key weather changes from context if available
        if context and 'aggregates' in context:
            agg = context['aggregates']
            changes = context.get('changes', {})
            weather_summary = []
            if changes.get('temperature_change'):
                weather_summary.append(f"temp Δ{changes['temperature_change']:.1f}°C")
            if changes.get('pressure_change'):
                weather_summary.append(f"pressure Δ{changes['pressure_change']:.1f}hPa")
            if agg.get('avg_forecast_humidity'):
                weather_summary.append(f"humidity {agg['avg_forecast_humidity']:.0f}%")
            if weather_summary:
                user_prompt_parts.append(f"Weather: {', '.join(weather_summary)}")

        # Add summarized previous predictions history if available
        if context and 'previous_predictions' in context:
            prev_summary = context['previous_predictions']
            if prev_summary.get('count', 0) > 0:
                # Compact summary: just counts by level in last 24h
                summary_parts = []
                if prev_summary.get('high_count', 0) > 0:
                    summary_parts.append(f"{prev_summary['high_count']}H")
                if prev_summary.get('medium_count', 0) > 0:
                    summary_parts.append(f"{prev_summary['medium_count']}M")
                if prev_summary.get('low_count', 0) > 0:
                    summary_parts.append(f"{prev_summary['low_count']}L")
                if summary_parts:
                    user_prompt_parts.append(f"Last 24h predictions: {'/'.join(summary_parts)}")

        # Add weather trend information if available
        if context and 'weather_trend' in context:
            trend = context['weather_trend']
            trend_parts = []
            temp_trend = trend.get('temp_trend', 0)
            pressure_trend = trend.get('pressure_trend', 0)

            if temp_trend != 0:
                direction = "rising" if temp_trend > 0 else "falling"
                trend_parts.append(f"temp {direction} {abs(temp_trend):.1f}°C")
            if pressure_trend != 0:
                direction = "rising" if pressure_trend > 0 else "falling"
                trend_parts.append(f"pressure {direction} {abs(pressure_trend):.1f}hPa")

            if trend_parts:
                user_prompt_parts.append(f"24h trend: {', '.join(trend_parts)}")

        user_prompt_str = "\n".join(user_prompt_parts)

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

        try:
            result = self.chat_complete(
                messages=messages,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning("LLM chat request failed: %s", e)
            return None, {"error": str(e), "request_payload": request_payload}

        try:
            choices = result.get("choices", [])
            content = (choices[0]["message"]["content"] if choices else "").strip()
            parsed = self._extract_json(content) if content else None
            if not parsed:
                logger.warning("LLM response not JSON parsable: %s", content[:200])
                return None, {"raw": result, "request_payload": request_payload}
            level = parsed.get("probability_level")
            if isinstance(level, str):
                level_up = level.strip().upper()
                if level_up in {"LOW", "MEDIUM", "HIGH"}:
                    return level_up, {"raw": parsed, "api_raw": result, "request_payload": request_payload}
            logger.warning("LLM response missing/invalid probability_level: %s", parsed)
            return None, {"raw": parsed, "api_raw": result, "request_payload": request_payload}
        except Exception:
            logger.exception("Failed to process LLM response")
            return None, {"raw": result, "request_payload": request_payload}

    def predict_sinusitis_probability(
        self,
        scores: Dict[str, float],
        location_label: str,
        user_profile: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """
        Ask the LLM to output a JSON with keys for sinusitis risk assessment:
          - probability_level: one of LOW, MEDIUM, HIGH
          - confidence: float 0-1
          - rationale: short string
        Returns (probability_level, raw_payload) or (None, raw_payload) on failure.
        """
        # System prompt for sinusitis with explicit JSON output instruction and schema
        sys_prompt = (
            "You are a sinusitis risk assessor. Analyze weather risk factors (0-1 scale, higher=riskier) "
            "and output ONLY valid JSON matching the schema below. Do not include any text before or after the JSON. "
            "Focus on sinusitis triggers: rapid temperature changes, humidity extremes (high promotes allergens/mold, "
            "low dries sinuses), barometric pressure changes, and precipitation (increases allergens).\n\n"
            "<schema>\n"
            "{\n"
            '  "probability_level": "LOW" | "MEDIUM" | "HIGH",\n'
            '  "confidence": <float between 0 and 1>,\n'
            '  "rationale": "<brief explanation>",\n'
            '  "analysis_text": "<concise user explanation>",\n'
            '  "prevention_tips": ["<tip1>", "<tip2>", ...]\n'
            "}\n"
            "</schema>"
        )

        # Build minimal user prompt with only essential data
        user_prompt_parts = [
            f"Location: {location_label}",
            f"Risk scores: {json.dumps(scores)}",
        ]

        # Add temporal context if available (compact format)
        if context and 'forecast_time' in context:
            forecast_info = context['forecast_time']
            user_prompt_parts.append(
                f"Time: {forecast_info.get('day_period', '')} {forecast_info.get('hours_ahead', '')}h ahead"
            )

        # Add user sensitivity if available
        if user_profile:
            sensitivity = user_profile.get('sensitivity_overall', 1.0)
            if sensitivity != 1.0:
                user_prompt_parts.append(f"User sensitivity: {sensitivity:.1f}x")

        # Add key weather changes from context if available
        if context and 'aggregates' in context:
            agg = context['aggregates']
            changes = context.get('changes', {})
            weather_summary = []
            if changes.get('temperature_change'):
                weather_summary.append(f"temp Δ{changes['temperature_change']:.1f}°C")
            if changes.get('pressure_change'):
                weather_summary.append(f"pressure Δ{changes['pressure_change']:.1f}hPa")
            if agg.get('avg_forecast_humidity'):
                weather_summary.append(f"humidity {agg['avg_forecast_humidity']:.0f}%")
            if weather_summary:
                user_prompt_parts.append(f"Weather: {', '.join(weather_summary)}")

        # Add summarized previous predictions history if available
        if context and 'previous_predictions' in context:
            prev_summary = context['previous_predictions']
            if prev_summary.get('count', 0) > 0:
                # Compact summary: just counts by level in last 24h
                summary_parts = []
                if prev_summary.get('high_count', 0) > 0:
                    summary_parts.append(f"{prev_summary['high_count']}H")
                if prev_summary.get('medium_count', 0) > 0:
                    summary_parts.append(f"{prev_summary['medium_count']}M")
                if prev_summary.get('low_count', 0) > 0:
                    summary_parts.append(f"{prev_summary['low_count']}L")
                if summary_parts:
                    user_prompt_parts.append(f"Last 24h predictions: {'/'.join(summary_parts)}")

        # Add weather trend information if available
        if context and 'weather_trend' in context:
            trend = context['weather_trend']
            trend_parts = []
            temp_trend = trend.get('temp_trend', 0)
            pressure_trend = trend.get('pressure_trend', 0)

            if temp_trend != 0:
                direction = "rising" if temp_trend > 0 else "falling"
                trend_parts.append(f"temp {direction} {abs(temp_trend):.1f}°C")
            if pressure_trend != 0:
                direction = "rising" if pressure_trend > 0 else "falling"
                trend_parts.append(f"pressure {direction} {abs(pressure_trend):.1f}hPa")

            if trend_parts:
                user_prompt_parts.append(f"24h trend: {', '.join(trend_parts)}")

        user_prompt_str = "\n".join(user_prompt_parts)

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

        try:
            result = self.chat_complete(
                messages=messages,
                temperature=0.2,
            )
        except Exception as e:
            logger.warning("LLM chat request failed for sinusitis: %s", e)
            return None, {"error": str(e), "request_payload": request_payload}

        try:
            choices = result.get("choices", [])
            content = (choices[0]["message"]["content"] if choices else "").strip()
            parsed = self._extract_json(content) if content else None
            if not parsed:
                logger.warning("LLM sinusitis response not JSON parsable: %s", content[:200])
                return None, {"raw": result, "request_payload": request_payload}
            level = parsed.get("probability_level")
            if isinstance(level, str):
                level_up = level.strip().upper()
                if level_up in {"LOW", "MEDIUM", "HIGH"}:
                    return level_up, {"raw": parsed, "api_raw": result, "request_payload": request_payload}
            logger.warning("LLM sinusitis response missing/invalid probability_level: %s", parsed)
            return None, {"raw": parsed, "api_raw": result, "request_payload": request_payload}
        except Exception:
            logger.exception("Failed to process LLM sinusitis response")
            return None, {"raw": result, "request_payload": request_payload}
