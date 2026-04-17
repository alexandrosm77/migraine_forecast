from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock

from forecast.models import (
    AirQualityForecast,
    LLMResponse,
    Location,
    WeatherForecast,
    UserHealthProfile,
)
from forecast.prediction_service import MigrainePredictionService
from forecast.prediction_service_sinusitis import SinusitisPredictionService
from forecast.prediction_service_hayfever import HayFeverPredictionService


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

        # Forecasts for the prediction window (3-6 hours ahead). Pack them
        # inside the window with a margin so the first row does not leak into
        # previous_forecasts under small timezone.now() drift.
        for i in range(4):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=3.5 + i * 0.5),
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

    def _create_window_aq_rows(self, pm2_5):
        """Create AirQualityForecast rows aligned with the setUp window forecasts."""
        now = timezone.now()
        window_fcs = WeatherForecast.objects.filter(
            location=self.location, target_time__gt=now,
        ).order_by("target_time")
        for fc in window_fcs:
            AirQualityForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=fc.target_time,
                pm2_5=pm2_5,
            )
        return list(window_fcs)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_high_pm2_5_raises_air_quality_score(self, mock_get_config):
        """High PM2.5 should produce a non-zero air_quality score stored on the prediction."""
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        self._create_window_aq_rows(pm2_5=60.0)  # well above 25.0 µg/m³ threshold

        service = MigrainePredictionService()
        _, prediction = service.predict_migraine_probability(self.location, self.user)

        self.assertIsNotNone(prediction)
        factors = prediction.weather_factors or {}
        self.assertIn("air_quality", factors)
        self.assertGreater(factors["air_quality"], 0.0)
        # 60 / 25 clamped to 1.0
        self.assertEqual(factors["air_quality"], 1.0)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_air_quality_score_zero_without_aq_data(self, mock_get_config):
        """Without AQ rows the air_quality score stays 0.0 (graceful degradation)."""
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        service = MigrainePredictionService()
        _, prediction = service.predict_migraine_probability(self.location, self.user)

        self.assertIsNotNone(prediction)
        factors = prediction.weather_factors or {}
        self.assertEqual(factors.get("air_quality"), 0.0)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_llm_call_receives_air_quality_forecasts(self, mock_get_config):
        """_call_llm_predict should forward AQ rows as air_quality_forecasts kwarg."""
        mock_config = MagicMock()
        mock_config.is_active = True
        mock_config.base_url = "http://test.com"
        mock_config.api_key = "k"
        mock_config.model = "m"
        mock_config.timeout = 5.0
        mock_config.high_token_budget = False
        mock_config.confidence_threshold = 0.7
        mock_config.extra_payload = {}
        mock_get_config.return_value = mock_config

        window_fcs = self._create_window_aq_rows(pm2_5=40.0)

        with patch("forecast.prediction_service_base.LLMClient") as mock_llm_class:
            mock_llm_instance = MagicMock()
            mock_llm_instance.predict_probability.return_value = (
                "HIGH",
                {"raw": {"probability_level": "HIGH", "confidence": 0.9}},
            )
            mock_llm_class.return_value = mock_llm_instance

            service = MigrainePredictionService()
            service.predict_migraine_probability(self.location, self.user)

            call_kwargs = mock_llm_instance.predict_probability.call_args.kwargs
            self.assertIn("air_quality_forecasts", call_kwargs)
            self.assertEqual(len(call_kwargs["air_quality_forecasts"]), len(window_fcs))
            self.assertGreaterEqual(len(call_kwargs["air_quality_forecasts"]), 1)


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

    def _create_aq_rows(self, pm10=None, dust=None):
        now = timezone.now()
        window_fcs = WeatherForecast.objects.filter(
            location=self.location, target_time__gt=now,
        ).order_by("target_time")
        for fc in window_fcs:
            AirQualityForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=fc.target_time,
                pm10=pm10,
                dust=dust,
            )

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(SinusitisPredictionService.WEIGHTS.values()), 1.0, places=6)
        self.assertIn("air_quality", SinusitisPredictionService.WEIGHTS)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_air_quality_score_zero_without_aq_data(self, mock_get_config):
        """With no AirQualityForecast rows the air_quality score stays at 0.0."""
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        service = SinusitisPredictionService()
        _, prediction = service.predict_sinusitis_probability(self.location, self.user)
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.weather_factors.get("air_quality"), 0.0)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_high_pm10_and_dust_raise_air_quality_score(self, mock_get_config):
        """High PM10 + dust push air_quality to ~1.0 and raise the total score vs no-AQ baseline."""
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        service = SinusitisPredictionService()
        _, baseline = service.predict_sinusitis_probability(self.location, self.user)
        baseline_total = baseline.weather_factors["total_score"]
        self.assertEqual(baseline.weather_factors.get("air_quality"), 0.0)

        # Add AQ rows well above thresholds (PM10=100 > 50, dust=200 > 100 → both cap at 1.0)
        self._create_aq_rows(pm10=100.0, dust=200.0)
        _, enhanced = service.predict_sinusitis_probability(self.location, self.user)
        self.assertAlmostEqual(enhanced.weather_factors.get("air_quality"), 1.0, places=2)
        self.assertGreater(enhanced.weather_factors["total_score"], baseline_total)

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_llm_call_receives_air_quality_forecasts(self, mock_get_config):
        """_call_llm_predict attaches air_quality_forecasts kwarg from DB."""
        mock_config = MagicMock()
        mock_config.is_active = True
        mock_config.base_url = "http://test.com"
        mock_config.api_key = "k"
        mock_config.model = "m"
        mock_config.timeout = 5.0
        mock_config.high_token_budget = False
        mock_config.confidence_threshold = 0.7
        mock_config.extra_payload = {}
        mock_get_config.return_value = mock_config

        self._create_aq_rows(pm10=40.0, dust=50.0)

        with patch("forecast.prediction_service_base.LLMClient") as mock_llm_class:
            mock_llm_instance = MagicMock()
            mock_llm_instance.predict_sinusitis_probability.return_value = (
                "MEDIUM",
                {"raw": {"probability_level": "MEDIUM", "confidence": 0.9, "rationale": "ok"}},
            )
            mock_llm_class.return_value = mock_llm_instance

            service = SinusitisPredictionService()
            service.predict_sinusitis_probability(self.location, self.user)

            call_kwargs = mock_llm_instance.predict_sinusitis_probability.call_args.kwargs
            self.assertIn("air_quality_forecasts", call_kwargs)
            self.assertGreaterEqual(len(call_kwargs["air_quality_forecasts"]), 1)


class HayFeverPredictionServiceTest(TestCase):
    """Test cases for HayFeverPredictionService (EU + non-EU fallback)."""

    def setUp(self):
        self.user = User.objects.create_user(username="hfuser", email="hf@example.com", password="pw")
        self.location = Location.objects.create(
            user=self.user, city="Athens", country="Greece", latitude=37.9838, longitude=23.7275
        )
        now = timezone.now()

        # Previous 24h forecasts
        for i in range(6):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now - timedelta(hours=12),
                target_time=now - timedelta(hours=6 - i),
                temperature=22.0, humidity=55.0, pressure=1015.0,
                wind_speed=6.0, precipitation=0.0, cloud_cover=20.0,
            )

        # Window forecasts (3-6h ahead) — warm, dry, breezy
        self.window_forecasts = []
        for i in range(4):
            fc = WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=3 + i),
                temperature=26.0, humidity=40.0, pressure=1013.0,
                wind_speed=9.0, precipitation=0.0, cloud_cover=25.0,
            )
            self.window_forecasts.append(fc)

    def _create_aq_rows(self, with_pollen=True):
        now = timezone.now()
        for i, fc in enumerate(self.window_forecasts):
            AirQualityForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=fc.target_time,
                grass_pollen=120.0 if with_pollen else None,
                birch_pollen=40.0 if with_pollen else None,
                alder_pollen=10.0 if with_pollen else None,
                mugwort_pollen=5.0 if with_pollen else None,
                olive_pollen=80.0 if with_pollen else None,
                ragweed_pollen=0.0 if with_pollen else None,
                pm2_5=15.0, pm10=35.0, ozone=110.0,
                nitrogen_dioxide=20.0, european_aqi=60.0,
            )

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_high_with_peak_pollen(self, mock_get_config):
        """Peak grass/olive pollen + wind + warm-dry should push manual score to HIGH."""
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        self._create_aq_rows(with_pollen=True)
        service = HayFeverPredictionService()
        probability, prediction = service.predict_hayfever_probability(self.location, self.user)

        self.assertEqual(probability, "HIGH")
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.probability, "HIGH")
        self.assertTrue(prediction.weather_factors.get("pollen_available"))
        self.assertEqual(prediction.weather_factors.get("weights_used"), "default")

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_non_eu_fallback_without_pollen(self, mock_get_config):
        """No pollen data -> still produces a prediction with pollen_available=False."""
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        self._create_aq_rows(with_pollen=False)
        service = HayFeverPredictionService()
        probability, prediction = service.predict_hayfever_probability(self.location, self.user)

        self.assertIn(probability, ["LOW", "MEDIUM", "HIGH"])
        self.assertIsNotNone(prediction)
        self.assertFalse(prediction.weather_factors.get("pollen_available"))
        self.assertEqual(prediction.weather_factors.get("weights_used"), "no_pollen")

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_with_llm_records_llmresponse(self, mock_get_config):
        """LLM-backed prediction creates a linked LLMResponse row."""
        mock_config = MagicMock()
        mock_config.is_active = True
        mock_config.base_url = "http://test.com"
        mock_config.api_key = "k"
        mock_config.model = "m"
        mock_config.timeout = 5.0
        mock_config.high_token_budget = False
        mock_config.confidence_threshold = 0.7
        mock_config.extra_payload = {}
        mock_get_config.return_value = mock_config

        self._create_aq_rows(with_pollen=True)

        with patch("forecast.prediction_service_base.LLMClient") as mock_llm_class:
            mock_llm_instance = MagicMock()
            mock_llm_instance.predict_hayfever_probability.return_value = (
                "MEDIUM",
                {
                    "raw": {
                        "probability_level": "MEDIUM",
                        "confidence": 0.9,
                        "rationale": "moderate pollen",
                        "analysis_text": "Keep windows closed",
                        "prevention_tips": ["Close windows"],
                    },
                    "request_payload": {"model": "m"},
                    "api_raw": {"choices": []},
                    "inference_time": 0.1,
                },
            )
            mock_llm_class.return_value = mock_llm_instance

            service = HayFeverPredictionService()
            probability, prediction = service.predict_hayfever_probability(self.location, self.user)

            self.assertEqual(probability, "MEDIUM")
            mock_llm_instance.predict_hayfever_probability.assert_called_once()
            # air_quality_forecasts kwarg should be populated from DB
            call_kwargs = mock_llm_instance.predict_hayfever_probability.call_args.kwargs
            self.assertIn("air_quality_forecasts", call_kwargs)
            self.assertGreaterEqual(len(call_kwargs["air_quality_forecasts"]), 1)

            # LLMResponse created and linked
            llm_rows = LLMResponse.objects.filter(hayfever_prediction=prediction)
            self.assertEqual(llm_rows.count(), 1)
            self.assertEqual(llm_rows.first().prediction_type, "hayfever")

    @patch("forecast.models.LLMConfiguration.get_config")
    def test_predict_no_forecasts_returns_none(self, mock_get_config):
        mock_config = MagicMock()
        mock_config.is_active = False
        mock_get_config.return_value = mock_config

        other = Location.objects.create(
            user=self.user, city="Nowhere", country="X", latitude=0.0, longitude=0.0
        )
        service = HayFeverPredictionService()
        probability, prediction = service.predict_hayfever_probability(other, self.user)
        self.assertIsNone(probability)
        self.assertIsNone(prediction)


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
