from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock

from forecast.models import Location, WeatherForecast, AirQualityForecast
from forecast.weather_api import OpenMeteoClient
from forecast.weather_service import WeatherService
from forecast.air_quality_api import OpenMeteoAirQualityClient


class OpenMeteoClientTest(TestCase):
    @patch("forecast.weather_api.requests.Session.get")
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

        # Create multiple forecasts with different target times
        WeatherForecast.objects.create(
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
            target_time=now + timedelta(hours=2),
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

        WeatherForecast.objects.create(
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


class CollectWeatherDataAirQualityIntegrationTest(TestCase):
    """Integration test: collect_weather_data populates AirQualityForecast rows."""

    def setUp(self):
        self.user = User.objects.create_user(username="wdu", email="wdu@example.com", password="pw")
        self.location = Location.objects.create(
            user=self.user, city="Athens", country="Greece", latitude=37.98, longitude=23.72
        )

    @patch("forecast.weather_api.OpenMeteoClient.get_forecast_batch")
    @patch("forecast.air_quality_api.OpenMeteoAirQualityClient.get_forecast_batch")
    def test_collect_weather_data_populates_air_quality(self, mock_aq_batch, mock_wx_batch):
        future_iso = (timezone.now() + timedelta(hours=1)).replace(microsecond=0, tzinfo=None).isoformat()

        # Mock weather batch response
        mock_wx_batch.return_value = [
            {
                "location": self.location,
                "data": {
                    "hourly": {
                        "time": [future_iso],
                        "temperature_2m": [20.0],
                        "relative_humidity_2m": [50.0],
                        "precipitation_probability": [10],
                        "precipitation": [0.0],
                        "surface_pressure": [1013.0],
                        "cloud_cover": [20.0],
                        "visibility": [20000],
                        "wind_speed_10m": [5.0],
                    }
                },
            }
        ]

        # Mock air-quality batch response (non-EU values all populated here; test
        # ensures pollen NULL handling is exercised by a separate unit test).
        mock_aq_batch.return_value = [
            {
                "location": self.location,
                "data": {
                    "hourly": {
                        "time": [future_iso],
                        **{p: [1.23] for p in OpenMeteoAirQualityClient.POLLEN_PARAMS},
                        **{p: [4.56] for p in OpenMeteoAirQualityClient.AIR_QUALITY_PARAMS},
                    }
                },
            }
        ]

        from forecast.tasks import collect_weather_data

        result = collect_weather_data.apply().get()

        self.assertEqual(result["status"], "completed")
        self.assertGreaterEqual(result["forecasts_created"], 1)
        self.assertGreaterEqual(result["air_quality_created"], 1)

        self.assertEqual(WeatherForecast.objects.filter(location=self.location).count(), 1)
        self.assertEqual(AirQualityForecast.objects.filter(location=self.location).count(), 1)

        aq = AirQualityForecast.objects.get(location=self.location)
        self.assertEqual(aq.pm10, 4.56)
        self.assertEqual(aq.alder_pollen, 1.23)

    @patch("forecast.weather_api.OpenMeteoClient.get_forecast_batch")
    @patch("forecast.air_quality_api.OpenMeteoAirQualityClient.get_forecast_batch")
    def test_air_quality_failure_does_not_break_weather_collection(self, mock_aq_batch, mock_wx_batch):
        """If air-quality fetch raises, weather collection still completes."""
        future_iso = (timezone.now() + timedelta(hours=1)).replace(microsecond=0, tzinfo=None).isoformat()

        mock_wx_batch.return_value = [
            {
                "location": self.location,
                "data": {
                    "hourly": {
                        "time": [future_iso],
                        "temperature_2m": [20.0],
                        "relative_humidity_2m": [50.0],
                        "precipitation_probability": [10],
                        "precipitation": [0.0],
                        "surface_pressure": [1013.0],
                        "cloud_cover": [20.0],
                        "visibility": [20000],
                        "wind_speed_10m": [5.0],
                    }
                },
            }
        ]

        # Air-quality batch explodes
        mock_aq_batch.side_effect = RuntimeError("boom")

        from forecast.tasks import collect_weather_data

        result = collect_weather_data.apply().get()

        self.assertEqual(result["status"], "completed")
        self.assertEqual(WeatherForecast.objects.filter(location=self.location).count(), 1)
        self.assertEqual(AirQualityForecast.objects.filter(location=self.location).count(), 0)
        self.assertGreaterEqual(result["air_quality_errors"], 1)
