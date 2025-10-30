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
        sys_prompt = (
            "You are a migraine risk assessor. You receive weather-derived risk factors (0-1, higher is riskier). "
            "Follow the output JSON schema exactly and output only a single JSON object, no extra text.\n"
            "<schema>{\n"
            "  \"type\": \"object\",\n"
            "  \"additionalProperties\": false,\n"
            "  \"properties\": {\n"
            "    \"probability_level\": {\n"
            "      \"type\": \"string\",\n"
            "      \"enum\": [\"LOW\", \"MEDIUM\", \"HIGH\"]\n"
            "    },\n"
            "    \"confidence\": {\n"
            "      \"type\": \"number\",\n"
            "      \"minimum\": 0,\n"
            "      \"maximum\": 1\n"
            "    },\n"
            "    \"rationale\": { \"type\": \"string\" },\n"
            "    \"analysis_text\": { \"type\": \"string\", \"description\": \"Concise analysis to show users why this prediction was made\" },\n"
            "    \"prevention_tips\": { \"type\": \"array\", \"items\": { \"type\": \"string\" }, \"minItems\": 2, \"maxItems\": 8 }\n"
            "  },\n"
            "  \"required\": [\"probability_level\", \"confidence\", \"rationale\", \"analysis_text\", \"prevention_tips\"]\n"
            "}</schema>"
        )
        user_prompt = {
            "location": location_label,
            "scores": scores,
            "user_profile": user_profile or {},
            "context": context or {},
        }
        try:
            result = self.chat_complete(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": json.dumps(user_prompt)},
                ],
                temperature=0.2,
            )
        except Exception as e:
            logger.warning("LLM chat request failed: %s", e)
            return None, {"error": str(e)}

        try:
            choices = result.get("choices", [])
            content = (choices[0]["message"]["content"] if choices else "").strip()
            parsed = self._extract_json(content) if content else None
            if not parsed:
                logger.warning("LLM response not JSON parsable: %s", content[:200])
                return None, {"raw": result}
            level = parsed.get("probability_level")
            if isinstance(level, str):
                level_up = level.strip().upper()
                if level_up in {"LOW", "MEDIUM", "HIGH"}:
                    return level_up, {"raw": parsed, "api_raw": result}
            logger.warning("LLM response missing/invalid probability_level: %s", parsed)
            return None, {"raw": parsed, "api_raw": result}
        except Exception:
            logger.exception("Failed to process LLM response")
            return None, {"raw": result}
