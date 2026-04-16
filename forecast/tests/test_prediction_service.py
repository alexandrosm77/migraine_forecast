from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock

from forecast.models import (
    Location,
    WeatherForecast,
    UserHealthProfile,
)
from forecast.prediction_service import MigrainePredictionService
from forecast.prediction_service_sinusitis import SinusitisPredictionService


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
        mock_config.high_token_budget = False
        mock_config.confidence_threshold = 0.8
        mock_get_config.return_value = mock_config

        # Mock LLM client response
        with patch("forecast.prediction_service_base.LLMClient") as mock_llm_class:
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
        mock_config.high_token_budget = False
        mock_config.confidence_threshold = 0.8
        mock_get_config.return_value = mock_config

        # Mock LLM client response
        with patch("forecast.prediction_service_base.LLMClient") as mock_llm_class:
            mock_llm_instance = MagicMock()
            mock_llm_instance.predict_sinusitis_probability.return_value = (
                "MEDIUM",
                {
                    "raw": {
                        "probability_level": "MEDIUM",
                        "confidence": 0.85,  # Above threshold (0.8) so no downgrade
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


class DigestPredictionWindowTest(TestCase):
    """Test that digest mode uses a fixed 0-24 hour prediction window"""

    def setUp(self):
        self.user = User.objects.create_user(username="digestuser", email="digest@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="Athens", country="Greece", latitude=37.9838, longitude=23.7275
        )

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_generate_digest_predictions_uses_24h_window(self, mock_get_config):
        """Test that generate_digest_predictions uses fixed 0-24 hour window"""
        # Mock LLM configuration as inactive
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        # Create profile with custom prediction window (should be ignored in digest mode)
        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
            prediction_window_start_hours=2,
            prediction_window_end_hours=8,
        )

        now = timezone.now()
        # Create forecasts covering 0-24 hours ahead
        for i in range(25):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=i),
                temperature=20.0 + i * 0.5,
                humidity=50.0,
                pressure=1013.0 - i * 0.3,
                wind_speed=10.0,
                precipitation=0.0,
                cloud_cover=30.0,
            )

        with patch("forecast.prediction_service.MigrainePredictionService.predict_migraine_probability") as mock_predict:  # noqa
            mock_prediction = MagicMock()
            mock_prediction.id = 1
            mock_predict.return_value = ("LOW", mock_prediction)

            from forecast.tasks import generate_digest_predictions

            # Call the underlying function (not as a Celery task)
            generate_digest_predictions(self.user.id, self.location.id, "migraine")

            # Verify predict was called with 0-24 hour window
            call_kwargs = mock_predict.call_args[1]
            self.assertEqual(call_kwargs["window_start_hours"], 0)
            self.assertEqual(call_kwargs["window_end_hours"], 24)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_generate_digest_predictions_ignores_custom_window(self, mock_get_config):
        """Test that digest predictions ignore user's custom prediction_window settings"""
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        # Create profile with very narrow custom window
        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
            prediction_window_start_hours=1,
            prediction_window_end_hours=2,
        )

        with patch("forecast.prediction_service_sinusitis.SinusitisPredictionService.predict_sinusitis_probability") as mock_predict:  # noqa
            mock_prediction = MagicMock()
            mock_prediction.id = 1
            mock_predict.return_value = ("LOW", mock_prediction)

            from forecast.tasks import generate_digest_predictions

            generate_digest_predictions(self.user.id, self.location.id, "sinusitis")

            # Should use 0-24, NOT the user's 1-2 hour window
            call_kwargs = mock_predict.call_args[1]
            self.assertEqual(call_kwargs["window_start_hours"], 0)
            self.assertEqual(call_kwargs["window_end_hours"], 24)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_generate_predictions_command_skips_digest_users(self, mock_get_config):
        """Test that the generate_predictions management command skips DIGEST mode users"""
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
        )

        now = timezone.now()
        # Create some forecasts
        for i in range(7):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=i + 3),
                temperature=25.0,
                humidity=70.0,
                pressure=1010.0,
                wind_speed=15.0,
                precipitation=2.0,
                cloud_cover=80.0,
            )

        from forecast.management.commands.generate_predictions import Command

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.style = cmd.stdout.style = MagicMock()
        # Mock style methods to return string
        cmd.style.SUCCESS = lambda x: x
        cmd.style.WARNING = lambda x: x
        cmd.style.ERROR = lambda x: x

        with patch.object(MigrainePredictionService, "predict_migraine_probability") as mock_predict:
            cmd.handle(skip_cleanup=True, location_id=None, cleanup_days=7)

            # Should NOT have been called because user is in DIGEST mode
            mock_predict.assert_not_called()
