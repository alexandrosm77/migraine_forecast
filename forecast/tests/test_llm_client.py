import json

from django.test import TestCase
from unittest.mock import patch, MagicMock

from forecast.llm_client import LLMClient


class LLMClientTest(TestCase):
    """Test cases for LLMClient"""

    def setUp(self):
        self.client = LLMClient(base_url="http://localhost:8000", api_key="test_key", model="test_model", timeout=10.0)

    def test_initialization(self):
        """Test LLMClient initialization"""
        self.assertEqual(self.client.base_url, "http://localhost:8000")
        self.assertEqual(self.client.api_key, "test_key")
        self.assertEqual(self.client.model, "test_model")
        self.assertEqual(self.client.timeout, 10.0)

    def test_initialization_strips_trailing_slash(self):
        """Test that base_url trailing slash is removed"""
        client = LLMClient(base_url="http://localhost:8000/")
        self.assertEqual(client.base_url, "http://localhost:8000")

    def test_headers_with_api_key(self):
        """Test headers include authorization when api_key is provided"""
        headers = self.client._headers()
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(headers["Authorization"], "Bearer test_key")

    def test_headers_without_api_key(self):
        """Test headers without api_key"""
        client = LLMClient(base_url="http://localhost:8000", api_key="")
        headers = client._headers()
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertNotIn("Authorization", headers)

    @patch("forecast.llm_client.requests.Session.post")
    def test_chat_complete_success(self, mock_post):
        """Test successful chat completion"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "test response"}}]}
        mock_post.return_value = mock_response

        messages = [{"role": "user", "content": "test"}]
        result = self.client.chat_complete(messages)

        self.assertIn("choices", result)
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["model"], "test_model")
        self.assertEqual(call_kwargs["json"]["messages"], messages)

    @patch("forecast.llm_client.requests.Session.post")
    def test_chat_complete_with_kwargs(self, mock_post):
        """Test chat completion with additional kwargs"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}
        mock_post.return_value = mock_response

        messages = [{"role": "user", "content": "test"}]
        self.client.chat_complete(messages, temperature=0.5, max_tokens=100)

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["temperature"], 0.5)
        self.assertEqual(call_kwargs["json"]["max_tokens"], 100)

    def test_extract_json_direct(self):
        """Test extracting JSON from direct JSON string"""
        json_str = '{"key": "value", "number": 42}'
        result = LLMClient._extract_json(json_str)
        self.assertEqual(result, {"key": "value", "number": 42})

    def test_extract_json_with_code_block(self):
        """Test extracting JSON from markdown code block"""
        json_str = '```json\n{"key": "value"}\n```'
        result = LLMClient._extract_json(json_str)
        self.assertEqual(result, {"key": "value"})

    def test_extract_json_with_code_block_no_language(self):
        """Test extracting JSON from code block without language hint"""
        json_str = '```\n{"key": "value"}\n```'
        result = LLMClient._extract_json(json_str)
        self.assertEqual(result, {"key": "value"})

    def test_extract_json_invalid(self):
        """Test extracting JSON from invalid string"""
        result = LLMClient._extract_json("not json at all")
        self.assertIsNone(result)

    @patch("forecast.llm_client.requests.Session.post")
    def test_predict_probability_success(self, mock_post):
        """Test successful probability prediction"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "probability_level": "HIGH",
                                "confidence": 0.85,
                                "rationale": "High risk factors",
                                "analysis_text": "Weather conditions are risky",
                                "prevention_tips": ["Stay hydrated", "Rest"],
                            }
                        )
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        scores = {"temperature_change": 0.8, "pressure_change": 0.7}
        level, payload = self.client.predict_probability(scores, "New York, USA")

        self.assertEqual(level, "HIGH")
        self.assertIsNotNone(payload)
        self.assertIn("raw", payload)
        self.assertEqual(payload["raw"]["probability_level"], "HIGH")

    @patch("forecast.llm_client.requests.Session.post")
    def test_predict_probability_with_context(self, mock_post):
        """Test probability prediction with full context including temporal and weather variations"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": '{"probability_level": "MEDIUM", "confidence": 0.6, "rationale": "test"}'}}
            ]
        }
        mock_post.return_value = mock_response

        scores = {"temperature_change": 0.5}
        user_profile = {"sensitivity_preset": "HIGH"}
        context = {
            "temporal_context": {
                "current_time": "2025-11-03 14:30",
                "current_hour": 14,
                "current_period": "afternoon",
                "day_of_week": "Sunday",
                "is_weekend": True,
                "season": "fall",
                "window_start_time": "2025-11-03 17:00",
                "window_end_time": "2025-11-03 20:00",
                "window_start_period": "evening",
                "window_duration_hours": 3.0,
            },
            "aggregates": {
                "avg_forecast_temperature": 18.5,
                "min_forecast_temperature": 15.0,
                "max_forecast_temperature": 22.0,
                "temperature_range": 7.0,
                "avg_forecast_pressure": 1010.5,
                "min_forecast_pressure": 1008.0,
                "max_forecast_pressure": 1013.0,
                "pressure_range": 5.0,
                "avg_forecast_humidity": 65.0,
            },
            "changes": {"temperature_change": 5.0, "pressure_change": 3.0},
        }

        level, payload = self.client.predict_probability(scores, "Boston, USA", user_profile, context)

        self.assertEqual(level, "MEDIUM")
        # Verify request was made with context
        call_kwargs = mock_post.call_args[1]
        user_content = call_kwargs["json"]["messages"][1]["content"]
        self.assertIn("Boston, USA", user_content)
        self.assertIn("sensitivity", user_content.lower())
        # Verify temporal context is included
        self.assertIn("Sunday", user_content)
        self.assertIn("weekend", user_content)
        self.assertIn("fall", user_content)
        # Verify temperature range is included
        self.assertIn("range", user_content)

    @patch("forecast.llm_client.requests.Session.post")
    def test_predict_probability_network_error(self, mock_post):
        """Test probability prediction with network error"""
        mock_post.side_effect = Exception("Network error")

        scores = {"temperature_change": 0.8}
        level, payload = self.client.predict_probability(scores, "Test City")

        self.assertIsNone(level)
        self.assertIn("error", payload)
        self.assertEqual(payload["error"], "Network error")

    @patch("forecast.llm_client.requests.Session.post")
    def test_predict_probability_invalid_response(self, mock_post):
        """Test probability prediction with invalid JSON response"""
        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": [{"message": {"content": "not valid json"}}]}
        mock_post.return_value = mock_response

        scores = {"temperature_change": 0.8}
        level, payload = self.client.predict_probability(scores, "Test City")

        self.assertIsNone(level)
        self.assertIn("raw", payload)

    @patch("forecast.llm_client.requests.Session.post")
    def test_predict_sinusitis_probability_success(self, mock_post):
        """Test successful sinusitis probability prediction"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "probability_level": "LOW",
                                "confidence": 0.9,
                                "rationale": "Low risk",
                                "analysis_text": "Conditions are favorable",
                                "prevention_tips": ["Keep sinuses moist"],
                            }
                        )
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        scores = {"humidity_change": 0.3}
        level, payload = self.client.predict_sinusitis_probability(scores, "Seattle, USA")

        self.assertEqual(level, "LOW")
        self.assertIsNotNone(payload)
        self.assertIn("raw", payload)

    def test_initialization_with_extra_payload(self):
        """Test LLMClient initialization with extra_payload"""
        extra_payload = {"temperature": 0.5, "top_p": 0.9}
        client = LLMClient(
            base_url="http://localhost:8000",
            api_key="test_key",
            model="test_model",
            timeout=10.0,
            extra_payload=extra_payload,
        )
        self.assertEqual(client.extra_payload, extra_payload)

    def test_initialization_extra_payload_defaults_to_empty(self):
        """Test that extra_payload defaults to empty dict when not provided"""
        client = LLMClient(base_url="http://localhost:8000")
        self.assertEqual(client.extra_payload, {})

    @patch("forecast.llm_client.requests.Session.post")
    def test_chat_complete_merges_extra_payload(self, mock_post):
        """Test that chat_complete merges extra_payload with request"""
        extra_payload = {"temperature": 0.5, "top_p": 0.9}
        client = LLMClient(
            base_url="http://localhost:8000",
            api_key="test_key",
            model="test_model",
            timeout=10.0,
            extra_payload=extra_payload,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}
        mock_post.return_value = mock_response

        messages = [{"role": "user", "content": "test"}]
        client.chat_complete(messages)

        call_kwargs = mock_post.call_args[1]
        # Check that extra_payload values are in the request
        self.assertEqual(call_kwargs["json"]["temperature"], 0.5)
        self.assertEqual(call_kwargs["json"]["top_p"], 0.9)

    @patch("forecast.llm_client.requests.Session.post")
    def test_chat_complete_kwargs_override_extra_payload(self, mock_post):
        """Test that kwargs override extra_payload values"""
        extra_payload = {"temperature": 0.5, "top_p": 0.9}
        client = LLMClient(
            base_url="http://localhost:8000",
            api_key="test_key",
            model="test_model",
            timeout=10.0,
            extra_payload=extra_payload,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}
        mock_post.return_value = mock_response

        messages = [{"role": "user", "content": "test"}]
        # Override temperature from extra_payload
        client.chat_complete(messages, temperature=0.8)

        call_kwargs = mock_post.call_args[1]
        # temperature should be overridden to 0.8
        self.assertEqual(call_kwargs["json"]["temperature"], 0.8)
        # top_p should still be from extra_payload
        self.assertEqual(call_kwargs["json"]["top_p"], 0.9)

    @patch("forecast.llm_client.requests.Session.post")
    def test_predict_probability_request_payload_includes_extra_payload(self, mock_post):
        """Test that request_payload stored in response includes extra_payload"""
        extra_payload = {"temperature": 0.5, "top_p": 0.9, "max_tokens": 2000}
        client = LLMClient(
            base_url="http://localhost:8000",
            api_key="test_key",
            model="test_model",
            timeout=10.0,
            extra_payload=extra_payload,
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "probability_level": "HIGH",
                                "confidence": 0.85,
                                "rationale": "High risk",
                                "analysis_text": "Risky conditions",
                                "prevention_tips": ["Stay hydrated"],
                            }
                        )
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        level, detail = client.predict_probability(
            scores={},
            location_label="Test City",
        )

        # Verify the request_payload in the returned detail includes extra_payload
        request_payload = detail.get("request_payload", {})
        self.assertEqual(request_payload.get("temperature"), 0.5)
        self.assertEqual(request_payload.get("top_p"), 0.9)
        self.assertEqual(request_payload.get("max_tokens"), 2000)
