from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, Mock
import json

from .models import (
    Location,
    WeatherForecast,
    ActualWeather,
    MigrainePrediction,
    SinusitisPrediction,
    UserHealthProfile,
    LLMResponse,
    LLMConfiguration,
)
from .weather_api import OpenMeteoClient
from .weather_service import WeatherService
from .prediction_service import MigrainePredictionService
from .prediction_service_sinusitis import SinusitisPredictionService
from .llm_client import LLMClient
from .notification_service import NotificationService
from .forms import UserHealthProfileForm
from .tools import ensure_timezone_aware


class LocationModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")

    def test_location_creation(self):
        location = Location.objects.create(
            user=self.user, city="New York", country="USA", latitude=40.7128, longitude=-74.0060
        )
        self.assertEqual(location.city, "New York")
        self.assertEqual(location.country, "USA")
        self.assertEqual(location.latitude, 40.7128)
        self.assertEqual(location.longitude, -74.0060)
        self.assertEqual(location.user, self.user)

    def test_location_string_representation(self):
        location = Location.objects.create(
            user=self.user, city="New York", country="USA", latitude=40.7128, longitude=-74.0060
        )
        self.assertEqual(str(location), "New York, USA")


class WeatherForecastModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="New York", country="USA", latitude=40.7128, longitude=-74.0060
        )

    def test_weather_forecast_creation(self):
        forecast_time = timezone.now()
        target_time = forecast_time + timedelta(hours=3)

        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=forecast_time,
            target_time=target_time,
            temperature=25.5,
            humidity=65.0,
            pressure=1013.2,
            wind_speed=10.5,
            precipitation=0.0,
            cloud_cover=30.0,
        )

        self.assertEqual(forecast.location, self.location)
        self.assertEqual(forecast.temperature, 25.5)
        self.assertEqual(forecast.humidity, 65.0)
        self.assertEqual(forecast.pressure, 1013.2)

    def test_weather_forecast_string_representation(self):
        forecast_time = timezone.now()
        target_time = forecast_time + timedelta(hours=3)

        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=forecast_time,
            target_time=target_time,
            temperature=25.5,
            humidity=65.0,
            pressure=1013.2,
            wind_speed=10.5,
            precipitation=0.0,
            cloud_cover=30.0,
        )

        expected_str = f"Forecast for {self.location} at {target_time}"
        self.assertEqual(str(forecast), expected_str)


class OpenMeteoClientTest(TestCase):
    @patch("forecast.weather_api.requests.get")
    def test_get_forecast(self, mock_get):
        # Mock the API response
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "hourly": {
                "time": ["2025-03-31T12:00:00Z", "2025-03-31T13:00:00Z"],
                "temperature_2m": [25.5, 26.0],
                "relative_humidity_2m": [65.0, 64.0],
                "precipitation_probability": [10, 5],
                "precipitation": [0.0, 0.0],
                "surface_pressure": [1013.2, 1013.0],
                "cloud_cover": [30.0, 25.0],
                "visibility": [20000, 20000],
                "wind_speed_10m": [10.5, 11.0],
            }
        }
        mock_get.return_value = mock_response

        client = OpenMeteoClient()
        result = client.get_forecast(40.7128, -74.0060)

        # Verify the API was called with correct parameters
        mock_get.assert_called_once()
        call_args = mock_get.call_args[1]
        self.assertEqual(call_args["params"]["latitude"], 40.7128)
        self.assertEqual(call_args["params"]["longitude"], -74.0060)

        # Verify the result
        self.assertIn("hourly", result)
        self.assertEqual(len(result["hourly"]["time"]), 2)


class MigrainePredictionServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="New York", country="USA", latitude=40.7128, longitude=-74.0060
        )

        # Create forecasts for testing
        now = timezone.now()

        # Previous forecasts (for comparison)
        for i in range(6):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now - timedelta(hours=12),
                target_time=now - timedelta(hours=6 - i),
                temperature=25.0,
                humidity=65.0,
                pressure=1013.0,
                wind_speed=10.0,
                precipitation=0.0,
                cloud_cover=30.0,
            )

        # Forecasts for the prediction window (3-6 hours ahead)
        for i in range(4):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=3 + i),
                temperature=30.0,  # Significant temperature change
                humidity=75.0,  # High humidity
                pressure=1000.0,  # Low pressure
                wind_speed=15.0,
                precipitation=5.0,  # Heavy precipitation
                cloud_cover=90.0,  # Heavy cloud cover
            )

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_migraine_probability_high(self, mock_get_config):
        """Test migraine prediction with high risk factors (LLM disabled)"""
        # Mock LLM configuration as inactive
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        service = MigrainePredictionService()
        probability, prediction = service.predict_migraine_probability(self.location, self.user)

        self.assertEqual(probability, "HIGH")
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.user, self.user)
        self.assertEqual(prediction.location, self.location)
        self.assertEqual(prediction.probability, "HIGH")

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_migraine_probability_with_llm(self, mock_get_config):
        """Test migraine prediction with LLM enabled"""
        # Mock LLM configuration as active
        mock_config = MagicMock()
        mock_config.is_active = True
        mock_config.base_url = "http://test.com"
        mock_config.api_key = "test_key"
        mock_config.model = "test_model"
        mock_config.timeout = 10.0
        mock_get_config.return_value = mock_config

        # Mock LLM client response
        with patch("forecast.prediction_service.LLMClient") as mock_llm_class:
            mock_llm_instance = MagicMock()
            mock_llm_instance.predict_probability.return_value = (
                "HIGH",
                {
                    "raw": {
                        "probability_level": "HIGH",
                        "confidence": 0.9,
                        "rationale": "High risk conditions",
                        "analysis_text": "Weather is risky",
                        "prevention_tips": ["Stay hydrated"],
                    }
                },
            )
            mock_llm_class.return_value = mock_llm_instance

            service = MigrainePredictionService()
            probability, prediction = service.predict_migraine_probability(self.location, self.user)

            self.assertEqual(probability, "HIGH")
            self.assertIsNotNone(prediction)

            # Verify LLM was called
            mock_llm_instance.predict_probability.assert_called_once()

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_migraine_probability_no_forecasts(self, mock_get_config):
        """Test migraine prediction with no forecasts available"""
        # Mock LLM configuration as inactive
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        # Create a new location with no forecasts
        new_location = Location.objects.create(
            user=self.user, city="Test City", country="USA", latitude=40.0, longitude=-100.0
        )

        service = MigrainePredictionService()
        probability, prediction = service.predict_migraine_probability(new_location, self.user)

        self.assertIsNone(probability)
        self.assertIsNone(prediction)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_migraine_probability_custom_time_window(self, mock_get_config):
        """Test migraine prediction with custom time window"""
        # Mock LLM configuration as inactive
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        # Create user profile with custom time window
        UserHealthProfile.objects.create(
            user=self.user,
            prediction_window_start_hours=2,
            prediction_window_end_hours=8,
        )

        service = MigrainePredictionService()
        probability, prediction = service.predict_migraine_probability(self.location, self.user)

        # Should use custom window from user profile
        self.assertIsNotNone(prediction)
        # Verify the prediction uses the custom time window
        time_diff_start = (prediction.target_time_start - timezone.now()).total_seconds() / 3600
        time_diff_end = (prediction.target_time_end - timezone.now()).total_seconds() / 3600
        self.assertAlmostEqual(time_diff_start, 2, delta=0.1)
        self.assertAlmostEqual(time_diff_end, 8, delta=0.1)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_migraine_probability_explicit_time_window(self, mock_get_config):
        """Test migraine prediction with explicitly provided time window"""
        # Mock LLM configuration as inactive
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        service = MigrainePredictionService()
        probability, prediction = service.predict_migraine_probability(
            self.location, self.user, window_start_hours=1, window_end_hours=4
        )

        # Should use explicitly provided window
        self.assertIsNotNone(prediction)
        time_diff_start = (prediction.target_time_start - timezone.now()).total_seconds() / 3600
        time_diff_end = (prediction.target_time_end - timezone.now()).total_seconds() / 3600
        self.assertAlmostEqual(time_diff_start, 1, delta=0.1)
        self.assertAlmostEqual(time_diff_end, 4, delta=0.1)


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
        """Test probability prediction with full context"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {"message": {"content": '{"probability_level": "MEDIUM", "confidence": 0.6, "rationale": "test"}'}}
            ]
        }
        mock_post.return_value = mock_response

        scores = {"temperature_change": 0.5}
        user_profile = {"sensitivity_overall": 1.5}
        context = {
            "forecast_time": {"day_period": "morning", "hours_ahead": 3},
            "aggregates": {"avg_forecast_humidity": 65.0},
            "changes": {"temperature_change": 5.0, "pressure_change": 3.0},
        }

        level, payload = self.client.predict_probability(scores, "Boston, USA", user_profile, context)

        self.assertEqual(level, "MEDIUM")
        # Verify request was made with context
        call_kwargs = mock_post.call_args[1]
        user_content = call_kwargs["json"]["messages"][1]["content"]
        self.assertIn("Boston, USA", user_content)
        self.assertIn("sensitivity", user_content.lower())

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


class LLMConfigurationTest(TestCase):
    """Test cases for LLMConfiguration model"""

    def test_llm_configuration_creation(self):
        """Test creating an LLM configuration"""
        config = LLMConfiguration.objects.create(
            name="Test Config",
            base_url="http://test.com",
            model="test-model",
            api_key="test-key",
            timeout=30.0,
            is_active=True,
        )
        self.assertEqual(config.name, "Test Config")
        self.assertEqual(config.base_url, "http://test.com")
        self.assertEqual(config.model, "test-model")
        self.assertTrue(config.is_active)

    def test_llm_configuration_string_representation(self):
        """Test string representation of LLM configuration"""
        config = LLMConfiguration.objects.create(name="Test Config", model="test-model", is_active=True)
        self.assertIn("Test Config", str(config))
        self.assertIn("test-model", str(config))
        self.assertIn("ACTIVE", str(config))

    def test_only_one_active_configuration(self):
        """Test that only one configuration can be active at a time"""
        config1 = LLMConfiguration.objects.create(name="Config 1", model="model-1", is_active=True)
        config2 = LLMConfiguration.objects.create(name="Config 2", model="model-2", is_active=True)

        # Refresh config1 from database
        config1.refresh_from_db()

        # config1 should now be inactive
        self.assertFalse(config1.is_active)
        self.assertTrue(config2.is_active)

    def test_get_config_returns_active(self):
        """Test get_config returns the active configuration"""
        config1 = LLMConfiguration.objects.create(name="Config 1", model="model-1", is_active=False)
        config2 = LLMConfiguration.objects.create(name="Config 2", model="model-2", is_active=True)

        active_config = LLMConfiguration.get_config()
        self.assertEqual(active_config.id, config2.id)

    def test_get_config_creates_default_if_none_exists(self):
        """Test get_config creates a default configuration if none exists"""
        # Ensure no configs exist
        LLMConfiguration.objects.all().delete()

        config = LLMConfiguration.get_config()

        self.assertIsNotNone(config)
        self.assertEqual(config.name, "Default")
        self.assertTrue(config.is_active)

    def test_get_config_activates_first_if_none_active(self):
        """Test get_config activates first config if none are active"""
        config1 = LLMConfiguration.objects.create(name="Config 1", model="model-1", is_active=False)
        config2 = LLMConfiguration.objects.create(name="Config 2", model="model-2", is_active=False)

        active_config = LLMConfiguration.get_config()

        # Should activate the first one
        self.assertEqual(active_config.id, config1.id)
        self.assertTrue(active_config.is_active)


class UserHealthProfileTest(TestCase):
    """Test cases for UserHealthProfile model"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")

    def test_user_health_profile_creation(self):
        """Test creating a user health profile"""
        profile = UserHealthProfile.objects.create(
            user=self.user,
            age=30,
            prior_conditions="Aura, hypertension",
            sensitivity_overall=1.5,
            sensitivity_temperature=2.0,
            email_notifications_enabled=True,
            migraine_predictions_enabled=True,
            sinusitis_predictions_enabled=False,
        )

        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.age, 30)
        self.assertEqual(profile.sensitivity_overall, 1.5)
        self.assertTrue(profile.email_notifications_enabled)
        self.assertTrue(profile.migraine_predictions_enabled)
        self.assertFalse(profile.sinusitis_predictions_enabled)

    def test_user_health_profile_defaults(self):
        """Test default values for user health profile"""
        profile = UserHealthProfile.objects.create(user=self.user)

        self.assertEqual(profile.sensitivity_overall, 1.0)
        self.assertEqual(profile.sensitivity_temperature, 1.0)
        self.assertEqual(profile.sensitivity_humidity, 1.0)
        self.assertEqual(profile.sensitivity_pressure, 1.0)
        self.assertTrue(profile.email_notifications_enabled)
        self.assertTrue(profile.migraine_predictions_enabled)
        self.assertTrue(profile.sinusitis_predictions_enabled)
        # Test new notification preference defaults
        self.assertEqual(profile.notification_frequency_hours, 3)
        self.assertEqual(profile.prediction_window_start_hours, 3)
        self.assertEqual(profile.prediction_window_end_hours, 6)

    def test_user_health_profile_string_representation(self):
        """Test string representation of user health profile"""
        profile = UserHealthProfile.objects.create(user=self.user)
        self.assertIn(self.user.username, str(profile))

    def test_user_health_profile_one_to_one_relationship(self):
        """Test one-to-one relationship with User"""
        profile = UserHealthProfile.objects.create(user=self.user)

        # Access profile through user
        self.assertEqual(self.user.health_profile, profile)

    def test_user_health_profile_custom_notification_preferences(self):
        """Test creating profile with custom notification preferences"""
        profile = UserHealthProfile.objects.create(
            user=self.user,
            notification_frequency_hours=6,
            prediction_window_start_hours=2,
            prediction_window_end_hours=12,
        )

        self.assertEqual(profile.notification_frequency_hours, 6)
        self.assertEqual(profile.prediction_window_start_hours, 2)
        self.assertEqual(profile.prediction_window_end_hours, 12)


class SinusitisPredictionTest(TestCase):
    """Test cases for SinusitisPrediction model"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="Seattle", country="USA", latitude=47.6062, longitude=-122.3321
        )
        self.forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=timezone.now(),
            target_time=timezone.now() + timedelta(hours=3),
            temperature=15.0,
            humidity=80.0,
            pressure=1010.0,
            wind_speed=10.0,
            precipitation=2.0,
            cloud_cover=70.0,
        )

    def test_sinusitis_prediction_creation(self):
        """Test creating a sinusitis prediction"""
        now = timezone.now()
        prediction = SinusitisPrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=self.forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="MEDIUM",
            weather_factors={"humidity_score": 0.6},
        )

        self.assertEqual(prediction.user, self.user)
        self.assertEqual(prediction.location, self.location)
        self.assertEqual(prediction.probability, "MEDIUM")
        self.assertFalse(prediction.notification_sent)

    def test_sinusitis_prediction_string_representation(self):
        """Test string representation of sinusitis prediction"""
        now = timezone.now()
        prediction = SinusitisPrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=self.forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
        )

        str_repr = str(prediction)
        self.assertIn(self.user.username, str_repr)
        self.assertIn("HIGH", str_repr)
        self.assertIn(self.location.city, str_repr)


class SinusitisPredictionServiceTest(TestCase):
    """Test cases for SinusitisPredictionService"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="Portland", country="USA", latitude=45.5152, longitude=-122.6784
        )

        # Create forecasts for testing
        now = timezone.now()

        # Previous forecasts (for comparison)
        for i in range(6):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now - timedelta(hours=12),
                target_time=now - timedelta(hours=6 - i),
                temperature=20.0,
                humidity=60.0,
                pressure=1015.0,
                wind_speed=8.0,
                precipitation=0.0,
                cloud_cover=40.0,
            )

        # Forecasts for the prediction window (3-6 hours ahead)
        # High humidity and temperature changes trigger sinusitis
        for i in range(4):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=3 + i),
                temperature=10.0,  # Significant temperature drop
                humidity=85.0,  # High humidity
                pressure=1005.0,  # Low pressure
                wind_speed=12.0,
                precipitation=3.0,
                cloud_cover=80.0,
            )

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_sinusitis_probability_high(self, mock_get_config):
        """Test sinusitis prediction with high risk factors (LLM disabled)"""
        # Mock LLM configuration as inactive
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        service = SinusitisPredictionService()
        probability, prediction = service.predict_sinusitis_probability(self.location, self.user)

        self.assertIn(probability, ["LOW", "MEDIUM", "HIGH"])
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.user, self.user)
        self.assertEqual(prediction.location, self.location)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_sinusitis_probability_with_llm(self, mock_get_config):
        """Test sinusitis prediction with LLM enabled"""
        # Mock LLM configuration as active
        mock_config = MagicMock()
        mock_config.is_active = True
        mock_config.base_url = "http://test.com"
        mock_config.api_key = "test_key"
        mock_config.model = "test_model"
        mock_config.timeout = 10.0
        mock_get_config.return_value = mock_config

        # Mock LLM client response
        with patch("forecast.prediction_service_sinusitis.LLMClient") as mock_llm_class:
            mock_llm_instance = MagicMock()
            mock_llm_instance.predict_sinusitis_probability.return_value = (
                "MEDIUM",
                {
                    "raw": {
                        "probability_level": "MEDIUM",
                        "confidence": 0.75,
                        "rationale": "Moderate risk conditions",
                        "analysis_text": "Some risk factors present",
                        "prevention_tips": ["Use humidifier"],
                    }
                },
            )
            mock_llm_class.return_value = mock_llm_instance

            service = SinusitisPredictionService()
            probability, prediction = service.predict_sinusitis_probability(self.location, self.user)

            self.assertEqual(probability, "MEDIUM")
            self.assertIsNotNone(prediction)

            # Verify LLM was called
            mock_llm_instance.predict_sinusitis_probability.assert_called_once()

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_sinusitis_probability_no_forecasts(self, mock_get_config):
        """Test sinusitis prediction with no forecasts available"""
        # Mock LLM configuration as inactive
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        # Create a new location with no forecasts
        new_location = Location.objects.create(
            user=self.user, city="Test City", country="USA", latitude=40.0, longitude=-100.0
        )

        service = SinusitisPredictionService()
        probability, prediction = service.predict_sinusitis_probability(new_location, self.user)

        self.assertIsNone(probability)
        self.assertIsNone(prediction)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_sinusitis_probability_custom_time_window(self, mock_get_config):
        """Test sinusitis prediction with custom time window"""
        # Mock LLM configuration as inactive
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        # Create user profile with custom time window
        UserHealthProfile.objects.create(
            user=self.user,
            prediction_window_start_hours=2,
            prediction_window_end_hours=10,
        )

        service = SinusitisPredictionService()
        probability, prediction = service.predict_sinusitis_probability(self.location, self.user)

        # Should use custom window from user profile
        self.assertIsNotNone(prediction)
        time_diff_start = (prediction.target_time_start - timezone.now()).total_seconds() / 3600
        time_diff_end = (prediction.target_time_end - timezone.now()).total_seconds() / 3600
        self.assertAlmostEqual(time_diff_start, 2, delta=0.1)
        self.assertAlmostEqual(time_diff_end, 10, delta=0.1)


class UserHealthProfileFormTest(TestCase):
    """Test cases for UserHealthProfileForm"""

    def test_form_valid_data(self):
        """Test form with valid data"""
        form_data = {
            "age": 30,
            "prior_conditions": "Aura, hypertension",
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 2,
            "daily_migraine_notification_limit": 1,
            "daily_sinusitis_notification_limit": 1,
            "notification_frequency_hours": 4,
            "quiet_hours_enabled": False,
            "prediction_window_start_hours": 2,
            "prediction_window_end_hours": 8,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": False,
            "sensitivity_overall": 1.5,
            "sensitivity_temperature": 1.2,
            "sensitivity_humidity": 1.0,
            "sensitivity_pressure": 1.3,
            "sensitivity_cloud_cover": 1.0,
            "sensitivity_precipitation": 1.1,
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_form_clamps_sensitivity_values(self):
        """Test that form clamps sensitivity values to valid range"""
        form_data = {
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "daily_migraine_notification_limit": 1,
            "daily_sinusitis_notification_limit": 1,
            "notification_frequency_hours": 3,
            "quiet_hours_enabled": False,
            "prediction_window_start_hours": 3,
            "prediction_window_end_hours": 6,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "sensitivity_overall": 5.0,  # Too high
            "sensitivity_temperature": -1.0,  # Too low
            "sensitivity_humidity": 1.5,  # Valid
            "sensitivity_pressure": 1.0,
            "sensitivity_cloud_cover": 1.0,
            "sensitivity_precipitation": 1.0,
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

        cleaned = form.cleaned_data
        self.assertEqual(cleaned["sensitivity_overall"], 3.0)  # Clamped to max
        self.assertEqual(cleaned["sensitivity_temperature"], 0.0)  # Clamped to min
        self.assertEqual(cleaned["sensitivity_humidity"], 1.5)  # Unchanged

    def test_form_optional_fields(self):
        """Test that optional fields can be omitted"""
        form_data = {
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "daily_migraine_notification_limit": 1,
            "daily_sinusitis_notification_limit": 1,
            "notification_frequency_hours": 3,
            "quiet_hours_enabled": False,
            "prediction_window_start_hours": 3,
            "prediction_window_end_hours": 6,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "sensitivity_overall": 1.0,
            "sensitivity_temperature": 1.0,
            "sensitivity_humidity": 1.0,
            "sensitivity_pressure": 1.0,
            "sensitivity_cloud_cover": 1.0,
            "sensitivity_precipitation": 1.0,
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_form_notification_frequency_validation(self):
        """Test notification frequency validation"""
        # Test too low
        form_data = {
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "daily_migraine_notification_limit": 1,
            "daily_sinusitis_notification_limit": 1,
            "notification_frequency_hours": 0,  # Too low
            "quiet_hours_enabled": False,
            "prediction_window_start_hours": 3,
            "prediction_window_end_hours": 6,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "sensitivity_overall": 1.0,
            "sensitivity_temperature": 1.0,
            "sensitivity_humidity": 1.0,
            "sensitivity_pressure": 1.0,
            "sensitivity_cloud_cover": 1.0,
            "sensitivity_precipitation": 1.0,
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Notification frequency must be at least 1 hour", str(form.errors))

        # Test too high
        form_data["notification_frequency_hours"] = 25  # Too high
        form = UserHealthProfileForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Notification frequency cannot exceed 24 hours", str(form.errors))

    def test_form_prediction_window_validation(self):
        """Test prediction window validation"""
        # Test window start too low
        form_data = {
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "daily_migraine_notification_limit": 1,
            "daily_sinusitis_notification_limit": 1,
            "notification_frequency_hours": 3,
            "quiet_hours_enabled": False,
            "prediction_window_start_hours": 0,  # Too low
            "prediction_window_end_hours": 6,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "sensitivity_overall": 1.0,
            "sensitivity_temperature": 1.0,
            "sensitivity_humidity": 1.0,
            "sensitivity_pressure": 1.0,
            "sensitivity_cloud_cover": 1.0,
            "sensitivity_precipitation": 1.0,
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Prediction window start must be at least 1 hour ahead", str(form.errors))

        # Test window end too high
        form_data["prediction_window_start_hours"] = 3
        form_data["prediction_window_end_hours"] = 80  # Too high
        form = UserHealthProfileForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Prediction window end cannot exceed 72 hours ahead", str(form.errors))

        # Test start >= end
        form_data["prediction_window_start_hours"] = 6
        form_data["prediction_window_end_hours"] = 6  # Same as start
        form = UserHealthProfileForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("Prediction window start must be before window end", str(form.errors))

        # Test window too narrow
        form_data["prediction_window_start_hours"] = 5
        form_data["prediction_window_end_hours"] = 5  # Less than 1 hour wide
        form = UserHealthProfileForm(data=form_data)
        self.assertFalse(form.is_valid())


class ToolsTest(TestCase):
    """Test cases for utility functions in tools.py"""

    def test_ensure_timezone_aware_with_naive_datetime(self):
        """Test making a naive datetime timezone-aware"""
        naive_dt = datetime(2025, 1, 1, 12, 0, 0)
        aware_dt = ensure_timezone_aware(naive_dt)

        self.assertFalse(timezone.is_naive(aware_dt))
        self.assertTrue(timezone.is_aware(aware_dt))

    def test_ensure_timezone_aware_with_aware_datetime(self):
        """Test that an already aware datetime is returned unchanged"""
        aware_dt = timezone.now()
        result_dt = ensure_timezone_aware(aware_dt)

        self.assertEqual(aware_dt, result_dt)
        self.assertTrue(timezone.is_aware(result_dt))


class WeatherServiceTest(TestCase):
    """Test cases for WeatherService"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="Denver", country="USA", latitude=39.7392, longitude=-104.9903
        )
        self.service = WeatherService()

    @patch("forecast.weather_api.OpenMeteoClient.get_forecast")
    @patch("forecast.weather_api.OpenMeteoClient.parse_forecast_data")
    def test_update_forecast_for_location(self, mock_parse, mock_get):
        """Test updating forecast for a location"""
        # Mock API response
        mock_get.return_value = {"hourly": {"time": [], "temperature_2m": []}}

        # Mock parsed data
        now = timezone.now()
        mock_parse.return_value = [
            {
                "location": self.location,
                "forecast_time": now,
                "target_time": now + timedelta(hours=1),
                "temperature": 20.0,
                "humidity": 50.0,
                "pressure": 1013.0,
                "wind_speed": 10.0,
                "precipitation": 0.0,
                "cloud_cover": 30.0,
            }
        ]

        forecasts = self.service.update_forecast_for_location(self.location)

        self.assertEqual(len(forecasts), 1)
        self.assertEqual(forecasts[0].location, self.location)
        mock_get.assert_called_once()

    @patch("forecast.weather_api.OpenMeteoClient.get_forecast")
    def test_update_forecast_for_location_api_failure(self, mock_get):
        """Test handling API failure when updating forecast"""
        mock_get.return_value = None

        forecasts = self.service.update_forecast_for_location(self.location)

        self.assertEqual(len(forecasts), 0)

    def test_get_latest_forecast(self):
        """Test getting the latest forecast for a location"""
        now = timezone.now()

        # Create multiple forecasts
        forecast1 = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now - timedelta(hours=2),
            target_time=now + timedelta(hours=1),
            temperature=20.0,
            humidity=50.0,
            pressure=1013.0,
            wind_speed=10.0,
            precipitation=0.0,
            cloud_cover=30.0,
        )

        forecast2 = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=1),
            temperature=21.0,
            humidity=51.0,
            pressure=1014.0,
            wind_speed=11.0,
            precipitation=0.0,
            cloud_cover=31.0,
        )

        latest = self.service.get_latest_forecast(self.location)

        self.assertEqual(latest.id, forecast2.id)

    def test_get_forecasts_for_timeframe(self):
        """Test getting forecasts for a specific timeframe"""
        now = timezone.now()
        start_time = now + timedelta(hours=1)
        end_time = now + timedelta(hours=5)

        # Create forecasts within and outside the timeframe
        forecast_in = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=20.0,
            humidity=50.0,
            pressure=1013.0,
            wind_speed=10.0,
            precipitation=0.0,
            cloud_cover=30.0,
        )

        forecast_out = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=10),
            temperature=22.0,
            humidity=52.0,
            pressure=1015.0,
            wind_speed=12.0,
            precipitation=0.0,
            cloud_cover=32.0,
        )

        forecasts = self.service.get_forecasts_for_timeframe(self.location, start_time, end_time)

        self.assertEqual(forecasts.count(), 1)
        self.assertEqual(forecasts.first().id, forecast_in.id)


class NotificationServiceTest(TestCase):
    """Test cases for NotificationService"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="Austin", country="USA", latitude=30.2672, longitude=-97.7431
        )
        self.service = NotificationService()

    def test_notification_service_initialization(self):
        """Test NotificationService initializes correctly"""
        self.assertIsNotNone(self.service.prediction_service)
        self.assertIsNotNone(self.service.sinusitis_prediction_service)
        self.assertIsNotNone(self.service.weather_service)

    @patch("forecast.notification_service.send_mail")
    def test_send_migraine_alert_email(self, mock_send_mail):
        """Test sending migraine alert email"""
        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=25.0,
            humidity=70.0,
            pressure=1010.0,
            wind_speed=15.0,
            precipitation=2.0,
            cloud_cover=80.0,
        )

        prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8},
        )

        # Call the public method
        result = self.service.send_migraine_alert(prediction)

        # Verify email was sent
        self.assertTrue(result)
        mock_send_mail.assert_called_once()

    def test_get_detailed_weather_factors(
        self,
    ):
        """Test getting detailed weather factors for a prediction"""
        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=30.0,
            humidity=75.0,
            pressure=1005.0,
            wind_speed=15.0,
            precipitation=5.0,
            cloud_cover=90.0,
        )

        prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8, "humidity_score": 0.7, "pressure_score": 0.9},
        )

        detailed = self.service._get_detailed_weather_factors(prediction)

        self.assertIsNotNone(detailed)
        self.assertIn("factors", detailed)

    @patch("forecast.notification_service.send_mail")
    def test_notification_frequency_respected(self, mock_send_mail):
        """Test that notification frequency preference is respected"""
        # Create user profile with 4-hour notification frequency
        UserHealthProfile.objects.create(
            user=self.user,
            notification_frequency_hours=4,
            email_notifications_enabled=True,
        )

        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=25.0,
            humidity=70.0,
            pressure=1010.0,
            wind_speed=15.0,
            precipitation=2.0,
            cloud_cover=80.0,
        )

        # Create a prediction that was sent 2 hours ago (within 4-hour window)
        old_prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now - timedelta(hours=2) + timedelta(hours=3),
            target_time_end=now - timedelta(hours=2) + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8},
            notification_sent=True,
        )
        # Manually set prediction_time to 2 hours ago
        old_prediction.prediction_time = now - timedelta(hours=2)
        old_prediction.save()

        # Create a new HIGH prediction
        new_prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.9},
            notification_sent=False,
        )

        # Try to send notifications
        migraine_predictions = {
            self.location.id: {
                "probability": "HIGH",
                "prediction": new_prediction,
            }
        }
        sinusitis_predictions = {}

        result = self.service.check_and_send_combined_notifications(
            migraine_predictions, sinusitis_predictions
        )

        # Should NOT send because last notification was only 2 hours ago (< 4 hour minimum)
        self.assertEqual(result, 0)
        mock_send_mail.assert_not_called()

    @patch("forecast.notification_service.send_mail")
    def test_notification_sent_after_frequency_window(self, mock_send_mail):
        """Test that notification is sent after frequency window has passed"""
        # Create user profile with 3-hour notification frequency
        UserHealthProfile.objects.create(
            user=self.user,
            notification_frequency_hours=3,
            email_notifications_enabled=True,
            daily_notification_limit=5,  # Allow multiple notifications
        )

        now = timezone.now()

        # Create forecasts for the prediction window
        for i in range(3, 7):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=i),
                temperature=25.0,
                humidity=70.0,
                pressure=1010.0,
                wind_speed=15.0,
                precipitation=2.0,
                cloud_cover=80.0,
            )

        forecast = WeatherForecast.objects.filter(location=self.location).first()

        # Create a prediction that was sent 4 hours ago (outside 3-hour window)
        old_prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now - timedelta(hours=4) + timedelta(hours=3),
            target_time_end=now - timedelta(hours=4) + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8, "total_score": 0.8},
            notification_sent=True,
        )
        # Manually set prediction_time to 4 hours ago
        old_prediction.prediction_time = now - timedelta(hours=4)
        old_prediction.save()

        # Create a new HIGH prediction
        new_prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.9, "total_score": 0.9},
            notification_sent=False,
        )

        # Try to send notifications
        migraine_predictions = {
            self.location.id: {
                "probability": "HIGH",
                "prediction": new_prediction,
            }
        }
        sinusitis_predictions = {}

        result = self.service.check_and_send_combined_notifications(
            migraine_predictions, sinusitis_predictions
        )

        # Should send because last notification was 4 hours ago (> 3 hour minimum)
        self.assertEqual(result, 1)
        mock_send_mail.assert_called_once()
