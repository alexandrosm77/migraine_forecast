import requests
import logging
from datetime import datetime, timedelta
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class OpenMeteoClient:
    """
    Client for the Open-Meteo Weather API.

    This client fetches weather forecast data that can be used for migraine prediction.
    """

    BASE_URL = "https://api.open-meteo.com/v1/forecast"

    # Weather parameters relevant for migraine prediction
    WEATHER_PARAMS = [
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation_probability",
        "precipitation",
        "surface_pressure",
        "cloud_cover",
        "visibility",
        "wind_speed_10m",
    ]

    def __init__(self):
        """Initialize the Open-Meteo client."""
        pass

    def get_forecast(self, latitude, longitude, days=3):
        """
        Get weather forecast for a specific location.

        Args:
            latitude (float): The latitude of the location
            longitude (float): The longitude of the location
            days (int): Number of forecast days (default: 3)

        Returns:
            dict: Weather forecast data
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(self.WEATHER_PARAMS),
            "forecast_days": days,
            "timezone": "UTC",
        }

        try:
            response = requests.get(self.BASE_URL, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching weather forecast: {e}")
            return None

    def parse_forecast_data(self, forecast_data, location):
        """
        Parse the forecast data from Open-Meteo API and prepare it for storage.

        Args:
            forecast_data (dict): The forecast data from the API
            location (Location): The location model instance

        Returns:
            list: List of dictionaries containing parsed forecast data
        """
        if not forecast_data or "hourly" not in forecast_data:
            logger.error("Invalid forecast data format")
            return []

        hourly_data = forecast_data["hourly"]
        timestamps = hourly_data.get("time", [])

        parsed_data = []

        for i, timestamp in enumerate(timestamps):
            # Skip if we're missing any required data
            if any(param not in hourly_data for param in self.WEATHER_PARAMS):
                continue

            # Use timezone-aware datetime objects
            forecast_time = timezone.now()  # This is already timezone-aware

            # Make target_time timezone-aware
            target_time = datetime.fromisoformat(timestamp)
            if timezone.is_naive(target_time):
                target_time = timezone.make_aware(target_time)

            # Only process forecasts for the next 3-6 hours
            hours_ahead = (target_time - forecast_time).total_seconds() / 3600
            if not (3 <= hours_ahead <= 6):
                continue

            forecast_entry = {
                "location": location,
                "forecast_time": forecast_time,
                "target_time": target_time,
                "temperature": hourly_data["temperature_2m"][i],
                "humidity": hourly_data["relative_humidity_2m"][i],
                "pressure": hourly_data["surface_pressure"][i],
                "wind_speed": hourly_data["wind_speed_10m"][i],
                "precipitation": hourly_data["precipitation"][i],
                "cloud_cover": hourly_data["cloud_cover"][i],
            }

            parsed_data.append(forecast_entry)

        return parsed_data
