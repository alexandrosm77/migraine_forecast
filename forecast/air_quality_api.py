import requests
import logging
from datetime import datetime
from django.utils import timezone
from sentry_sdk import capture_exception, set_context, add_breadcrumb, start_span
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class OpenMeteoAirQualityClient:
    """
    Client for the Open-Meteo Air Quality API.

    Fetches pollen and air-quality forecast data used for hay fever prediction.
    Mirrors the retry and Sentry-instrumentation patterns of OpenMeteoClient.
    """

    BASE_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

    # Pollen variables — only populated by the Open-Meteo pollen model
    # (CAMS Europe). For locations outside Europe these come back as null.
    POLLEN_PARAMS = [
        "alder_pollen",
        "birch_pollen",
        "grass_pollen",
        "mugwort_pollen",
        "olive_pollen",
        "ragweed_pollen",
    ]

    # Air-quality variables (global coverage via CAMS global)
    AIR_QUALITY_PARAMS = [
        "pm10",
        "pm2_5",
        "ozone",
        "nitrogen_dioxide",
        "dust",
        "uv_index",
        "european_aqi",
        "us_aqi",
    ]

    HOURLY_PARAMS = POLLEN_PARAMS + AIR_QUALITY_PARAMS

    # Pollen is only available up to 4 forecast days (API hard cap)
    DEFAULT_FORECAST_DAYS = 4

    def __init__(self):
        """Initialize the Open-Meteo air-quality client with retry logic."""
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            raise_on_status=False,
            respect_retry_after_header=True,
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)

        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        logger.info("OpenMeteoAirQualityClient initialized with retry strategy: 3 retries, exponential backoff")

    def get_forecast(self, latitude, longitude, days=DEFAULT_FORECAST_DAYS):
        """
        Get air-quality forecast for a specific location.

        Args:
            latitude (float): The latitude of the location
            longitude (float): The longitude of the location
            days (int): Number of forecast days (default: 4, pollen max)

        Returns:
            dict: Air-quality forecast data, or None on error
        """
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(self.HOURLY_PARAMS),
            "forecast_days": days,
            "timezone": "UTC",
        }

        add_breadcrumb(
            category="air_quality_api",
            message="Fetching air-quality forecast from Open-Meteo",
            level="info",
            data={"latitude": latitude, "longitude": longitude, "days": days, "api_url": self.BASE_URL},
        )

        try:
            with start_span(op="http.client", description="Open-Meteo air-quality API request"):
                response = self.session.get(self.BASE_URL, params=params, timeout=30)
                response.raise_for_status()

                add_breadcrumb(
                    category="air_quality_api",
                    message="Air-quality forecast fetched successfully",
                    level="info",
                    data={"status_code": response.status_code},
                )

                return response.json()

        except requests.exceptions.Timeout as e:
            set_context(
                "air_quality_api_timeout",
                {"latitude": latitude, "longitude": longitude, "days": days, "api_url": self.BASE_URL, "timeout": 30},
            )
            capture_exception(e)
            logger.error(f"Timeout fetching air-quality forecast after retries: {e}")
            return None

        except requests.exceptions.HTTPError as e:
            set_context(
                "air_quality_api_http_error",
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
            logger.error(f"HTTP error fetching air-quality forecast: {e}")
            return None

        except requests.exceptions.RequestException as e:
            set_context(
                "air_quality_api_error",
                {
                    "latitude": latitude,
                    "longitude": longitude,
                    "days": days,
                    "api_url": self.BASE_URL,
                    "error_type": type(e).__name__,
                },
            )
            capture_exception(e)
            logger.error(f"Error fetching air-quality forecast: {e}")
            return None

    def get_forecast_batch(self, locations, days=DEFAULT_FORECAST_DAYS):
        """
        Get air-quality forecast for multiple locations in a single API call.
        Open-Meteo supports batch requests with comma-separated coordinates.

        Args:
            locations (list): List of Location model instances (max 50)
            days (int): Number of forecast days (default: 4, pollen max)

        Returns:
            list: List of dicts with 'location' and 'data' keys (data may be None on error).
        """
        if not locations:
            logger.warning("get_forecast_batch called with empty locations list")
            return []

        if len(locations) > 50:
            logger.error(f"Batch size {len(locations)} exceeds maximum of 50 locations")
            raise ValueError("Batch size cannot exceed 50 locations")

        latitudes = ",".join(str(loc.latitude) for loc in locations)
        longitudes = ",".join(str(loc.longitude) for loc in locations)

        params = {
            "latitude": latitudes,
            "longitude": longitudes,
            "hourly": ",".join(self.HOURLY_PARAMS),
            "forecast_days": days,
            "timezone": "UTC",
        }

        location_details = [{"id": loc.id, "city": loc.city, "country": loc.country} for loc in locations]
        add_breadcrumb(
            category="air_quality_api",
            message=f"Fetching batch air-quality forecast from Open-Meteo for {len(locations)} locations",
            level="info",
            data={
                "location_count": len(locations),
                "locations": location_details,
                "days": days,
                "api_url": self.BASE_URL,
            },
        )

        try:
            with start_span(
                op="http.client",
                description=f"Open-Meteo air-quality batch API request ({len(locations)} locations)",
            ):
                response = self.session.get(self.BASE_URL, params=params, timeout=60)
                response.raise_for_status()

                add_breadcrumb(
                    category="air_quality_api",
                    message=f"Batch air-quality forecast fetched successfully for {len(locations)} locations",
                    level="info",
                    data={"status_code": response.status_code, "location_count": len(locations)},
                )

                batch_data = response.json()

                results = []
                if isinstance(batch_data, list):
                    for i, location in enumerate(locations):
                        if i < len(batch_data):
                            results.append({"location": location, "data": batch_data[i]})
                        else:
                            logger.error(f"Missing data for location {location} at index {i}")
                            results.append({"location": location, "data": None})
                else:
                    logger.warning("Batch API returned single object instead of array")
                    if locations:
                        results.append({"location": locations[0], "data": batch_data})

                return results

        except requests.exceptions.Timeout as e:
            set_context(
                "air_quality_api_batch_timeout",
                {
                    "location_count": len(locations),
                    "locations": location_details,
                    "days": days,
                    "api_url": self.BASE_URL,
                    "timeout": 60,
                },
            )
            capture_exception(e)
            logger.error(
                f"Timeout fetching batch air-quality forecast for {len(locations)} locations after retries: {e}"
            )
            return None

        except requests.exceptions.HTTPError as e:
            set_context(
                "air_quality_api_batch_http_error",
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
            logger.error(f"HTTP error fetching batch air-quality forecast for {len(locations)} locations: {e}")
            return None

        except requests.exceptions.RequestException as e:
            set_context(
                "air_quality_api_batch_error",
                {
                    "location_count": len(locations),
                    "locations": location_details,
                    "days": days,
                    "api_url": self.BASE_URL,
                    "error_type": type(e).__name__,
                },
            )
            capture_exception(e)
            logger.error(f"Error fetching batch air-quality forecast for {len(locations)} locations: {e}")
            return None

    def parse_forecast_data(self, forecast_data, location):
        """
        Parse the air-quality forecast data from Open-Meteo API for storage.

        Missing values (e.g. pollen variables for non-European locations) are
        stored as None, NOT zero — zero would be a valid measurement.

        Args:
            forecast_data (dict): The forecast data from the API
            location (Location): The location model instance

        Returns:
            list: List of dictionaries containing parsed forecast data
        """
        if not forecast_data or "hourly" not in forecast_data:
            logger.error("Invalid air-quality forecast data format")
            return []

        hourly_data = forecast_data["hourly"]
        timestamps = hourly_data.get("time", [])

        parsed_data = []

        for i, timestamp in enumerate(timestamps):
            forecast_time = timezone.now()

            target_time = datetime.fromisoformat(timestamp)
            if timezone.is_naive(target_time):
                target_time = timezone.make_aware(target_time)

            hours_ahead = (target_time - forecast_time).total_seconds() / 3600
            if hours_ahead < 0:
                continue

            entry = {
                "location": location,
                "forecast_time": forecast_time,
                "target_time": target_time,
            }

            # Populate each variable from the hourly arrays. Missing arrays
            # (variable not returned at all) and missing individual values
            # (API returned null for this hour) both map to None.
            for param in self.HOURLY_PARAMS:
                values = hourly_data.get(param)
                if values is None or i >= len(values):
                    entry[param] = None
                else:
                    entry[param] = values[i]

            parsed_data.append(entry)

        return parsed_data

    def parse_forecast_data_batch(self, batch_results):
        """
        Parse batch air-quality forecast data from Open-Meteo API.

        Args:
            batch_results (list): List of dicts with 'location' and 'data' keys
                                  from get_forecast_batch()

        Returns:
            dict: {location: [forecast_entry1, ...], ...}
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
                logger.warning(f"No air-quality forecast data for location {location}")
                parsed_batch[location] = []
                continue

            parsed_batch[location] = self.parse_forecast_data(forecast_data, location)

        return parsed_batch
