from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

from forecast.models import (
    Location,
    WeatherForecast,
    SinusitisPrediction,
    UserHealthProfile,
    LLMConfiguration,
)


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
        LLMConfiguration.objects.create(name="Config 1", model="model-1", is_active=False)
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
        LLMConfiguration.objects.create(name="Config 2", model="model-2", is_active=False)

        active_config = LLMConfiguration.get_config()

        # Should activate the first one
        self.assertEqual(active_config.id, config1.id)
        self.assertTrue(active_config.is_active)

    def test_high_token_budget_default(self):
        """Test that high_token_budget defaults to False"""
        config = LLMConfiguration.objects.create(name="Test Config", model="test-model", is_active=True)
        self.assertFalse(config.high_token_budget)

    def test_high_token_budget_can_be_set(self):
        """Test that high_token_budget can be set to True"""
        config = LLMConfiguration.objects.create(
            name="High Token Config", model="test-model", is_active=True, high_token_budget=True
        )
        self.assertTrue(config.high_token_budget)

    def test_extra_payload_default_empty(self):
        """Test that extra_payload defaults to empty dict"""
        config = LLMConfiguration.objects.create(name="Test Config", model="test-model", is_active=True)
        self.assertEqual(config.extra_payload, {})

    def test_extra_payload_can_be_set(self):
        """Test that extra_payload can be set with custom values"""
        extra_payload = {"temperature": 0.5, "top_p": 0.9, "max_tokens": 2000}
        config = LLMConfiguration.objects.create(
            name="Config with Payload", model="test-model", is_active=True, extra_payload=extra_payload
        )
        self.assertEqual(config.extra_payload, extra_payload)
        self.assertEqual(config.extra_payload["temperature"], 0.5)
        self.assertEqual(config.extra_payload["top_p"], 0.9)
        self.assertEqual(config.extra_payload["max_tokens"], 2000)

    def test_extra_payload_persists_in_database(self):
        """Test that extra_payload is correctly persisted and retrieved from database"""
        extra_payload = {"temperature": 0.3, "frequency_penalty": 0.5}
        LLMConfiguration.objects.create(
            name="Persistent Payload Config", model="test-model", is_active=True, extra_payload=extra_payload
        )

        # Retrieve from database
        retrieved_config = LLMConfiguration.objects.get(name="Persistent Payload Config")
        self.assertEqual(retrieved_config.extra_payload, extra_payload)


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
            sensitivity_preset="HIGH",
            email_notifications_enabled=True,
            migraine_predictions_enabled=True,
            sinusitis_predictions_enabled=False,
        )

        self.assertEqual(profile.user, self.user)
        self.assertEqual(profile.age, 30)
        self.assertEqual(profile.sensitivity_preset, "HIGH")
        self.assertTrue(profile.email_notifications_enabled)
        self.assertTrue(profile.migraine_predictions_enabled)
        self.assertFalse(profile.sinusitis_predictions_enabled)

    def test_user_health_profile_defaults(self):
        """Test default values for user health profile"""
        profile = UserHealthProfile.objects.create(user=self.user)

        self.assertEqual(profile.sensitivity_preset, "NORMAL")
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
