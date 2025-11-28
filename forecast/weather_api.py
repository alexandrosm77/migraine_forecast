import requests
import logging
from datetime import datetime
from django.utils import timezone
from sentry_sdk import capture_exception, set_context, add_breadcrumb, start_span

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

        # Add breadcrumb for API call
        add_breadcrumb(
            category="weather_api",
            message="Fetching weather forecast from Open-Meteo",
            level="info",
            data={"latitude": latitude, "longitude": longitude, "days": days, "api_url": self.BASE_URL},
        )

        try:
            with start_span(op="http.client", description="Open-Meteo API request"):
                response = requests.get(self.BASE_URL, params=params, timeout=30)
                response.raise_for_status()

                add_breadcrumb(
                    category="weather_api",
                    message="Weather forecast fetched successfully",
                    level="info",
                    data={"status_code": response.status_code},
                )

                return response.json()

        except requests.exceptions.Timeout as e:
            set_context(
                "weather_api_timeout",
                {"latitude": latitude, "longitude": longitude, "days": days, "api_url": self.BASE_URL, "timeout": 30},
            )
            capture_exception(e)
            logger.error(f"Timeout fetching weather forecast: {e}")
            return None

        except requests.exceptions.HTTPError as e:
            set_context(
                "weather_api_http_error",
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "days": days,
                    "api_url": self.BASE_URL,
                    "status_code": e.response.status_code if e.response else None,
                    "response_text": e.response.text if e.response else None,
                },
            )
            capture_exception(e)
            logger.error(f"HTTP error fetching weather forecast: {e}")
            return None

        except requests.exceptions.RequestException as e:
            set_context(
                "weather_api_error",
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "days": days,
                    "api_url": self.BASE_URL,
                    "error_type": type(e).__name__,
                },
            )
            capture_exception(e)
            logger.error(f"Error fetching weather forecast: {e}")
            return None

    def get_forecast_batch(self, locations, days=3):
        """
        Get weather forecast for multiple locations in a single API call.
        Open-Meteo supports batch requests with comma-separated coordinates.

        Args:
            locations (list): List of Location model instances (max 50)
            days (int): Number of forecast days (default: 3)

        Returns:
            list: List of dicts with weather forecast data for each location.
                  Each dict has 'location' key and 'data' key (API response or None on error).
        """
        if not locations:
            logger.warning("get_forecast_batch called with empty locations list")
            return []

        if len(locations) > 50:
            logger.error(f"Batch size {len(locations)} exceeds maximum of 50 locations")
            raise ValueError("Batch size cannot exceed 50 locations")

        # Build comma-separated latitude and longitude strings
        latitudes = ",".join(str(loc.latitude) for loc in locations)
        longitudes = ",".join(str(loc.longitude) for loc in locations)

        params = {
            "latitude": latitudes,
            "longitude": longitudes,
            "hourly": ",".join(self.WEATHER_PARAMS),
            "forecast_days": days,
            "timezone": "UTC",
        }

        # Add breadcrumb for batch API call
        location_details = [{"id": loc.id, "city": loc.city, "country": loc.country} for loc in locations]
        add_breadcrumb(
            category="weather_api",
            message=f"Fetching batch weather forecast from Open-Meteo for {len(locations)} locations",
            level="info",
            data={
                "location_count": len(locations),
                "locations": location_details,
                "days": days,
                "api_url": self.BASE_URL,
            },
        )

        try:
            with start_span(op="http.client", description=f"Open-Meteo batch API request ({len(locations)} locations)"):
                response = requests.get(self.BASE_URL, params=params, timeout=60)
                response.raise_for_status()

                add_breadcrumb(
                    category="weather_api",
                    message=f"Batch weather forecast fetched successfully for {len(locations)} locations",
                    level="info",
                    data={"status_code": response.status_code, "location_count": len(locations)},
                )

                # Parse the batch response
                batch_data = response.json()

                # The batch API returns an array of forecast objects
                # Each element corresponds to a location in the same order as the request
                results = []
                if isinstance(batch_data, list):
                    # Response is a list of forecast objects
                    for i, location in enumerate(locations):
                        if i < len(batch_data):
                            results.append({"location": location, "data": batch_data[i]})
                        else:
                            logger.error(f"Missing data for location {location} at index {i}")
                            results.append({"location": location, "data": None})
                else:
                    # Single location response (shouldn't happen with batch, but handle it)
                    logger.warning("Batch API returned single object instead of array")
                    if locations:
                        results.append({"location": locations[0], "data": batch_data})

                return results

        except requests.exceptions.Timeout as e:
            set_context(
                "weather_api_batch_timeout",
                {
                    "location_count": len(locations),
                    "locations": location_details,
                    "days": days,
                    "api_url": self.BASE_URL,
                    "timeout": 60,
                },
            )
            capture_exception(e)
            logger.error(f"Timeout fetching batch weather forecast for {len(locations)} locations: {e}")
            return None

        except requests.exceptions.HTTPError as e:
            set_context(
                "weather_api_batch_http_error",
                {
                    "location_count": len(locations),
                    "locations": location_details,
                    "days": days,
                    "api_url": self.BASE_URL,
                    "status_code": e.response.status_code if e.response else None,
                    "response_text": e.response.text if e.response else None,
                },
            )
            capture_exception(e)
            logger.error(f"HTTP error fetching batch weather forecast for {len(locations)} locations: {e}")
            return None

        except requests.exceptions.RequestException as e:
            set_context(
                "weather_api_batch_error",
                {
                    "location_count": len(locations),
                    "locations": location_details,
                    "days": days,
                    "api_url": self.BASE_URL,
                    "error_type": type(e).__name__,
                },
            )
            capture_exception(e)
            logger.error(f"Error fetching batch weather forecast for {len(locations)} locations: {e}")
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

            # Store all future forecasts (up to 72 hours based on API days=3 parameter)
            # This allows users to configure custom prediction windows (e.g., 0-23 hours)
            # The prediction service will filter based on user preferences
            hours_ahead = (target_time - forecast_time).total_seconds() / 3600
            if hours_ahead < 0:  # Skip past forecasts
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

    def parse_forecast_data_batch(self, batch_results):
        """
        Parse batch forecast data from Open-Meteo API.

        Args:
            batch_results (list): List of dicts with 'location' and 'data' keys
                                  from get_forecast_batch()

        Returns:
            dict: Dictionary mapping location objects to lists of parsed forecast data.
                  Format: {location: [forecast_entry1, forecast_entry2, ...], ...}
        """
        if not batch_results:
            logger.warning("parse_forecast_data_batch called with empty batch_results")
            return {}

        parsed_batch = {}

        for result in batch_results:
            location = result.get("location")
            forecast_data = result.get("data")

            if not location:
                logger.error("Batch result missing location")
                continue

            if not forecast_data:
                logger.warning(f"No forecast data for location {location}")
                parsed_batch[location] = []
                continue

            # Use the existing parse_forecast_data method for each location
            parsed_data = self.parse_forecast_data(forecast_data, location)
            parsed_batch[location] = parsed_data

        return parsed_batch
