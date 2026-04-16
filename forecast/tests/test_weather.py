from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock

from forecast.models import Location, WeatherForecast
from forecast.weather_api import OpenMeteoClient
from forecast.weather_service import WeatherService


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
