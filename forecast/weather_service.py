from .models import Location, WeatherForecast
from .weather_api import OpenMeteoClient
import logging
from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, start_transaction, set_tag

logger = logging.getLogger(__name__)


class WeatherService:
    """
    Service for fetching and storing weather forecast data.
    """

    def __init__(self):
        """Initialize the weather service with the Open-Meteo client."""
        self.api_client = OpenMeteoClient()

    def update_forecast_for_location(self, location):
        """
        Update weather forecast for a specific location.

        Args:
            location (Location): The location model instance

        Returns:
            list: List of created WeatherForecast instances
        """
        logger.info(f"Starting update_forecast_for_location for location: {location}")

        # Fetch forecast data from the API
        forecast_data = self.api_client.get_forecast(latitude=location.latitude, longitude=location.longitude, days=3)

        if not forecast_data:
            logger.error(f"Failed to fetch forecast data for location: {location}")
            return []

        # Parse the forecast data
        parsed_data = self.api_client.parse_forecast_data(forecast_data, location)

        # Store the forecast data in the database
        created_forecasts = []
        for entry in parsed_data:
            forecast = WeatherForecast.objects.create(**entry)
            created_forecasts.append(forecast)

        logger.info(f"Created {len(created_forecasts)} forecast entries for {location}")
        return created_forecasts

    def update_forecast_for_location_upsert(self, location):
        """
        Update weather forecast for a specific location using upsert pattern.
        This prevents duplicate forecasts by updating existing ones instead of always creating new.

        Args:
            location (Location): The location model instance

        Returns:
            tuple: (created_count, updated_count)
        """
        # Start transaction for performance monitoring
        with start_transaction(op="weather.update", name=f"update_forecast_{location.city}"):
            logger.info(f"Starting update_forecast_for_location_upsert for location: {location}")

            # Add breadcrumb for tracking
            add_breadcrumb(
                category="weather",
                message=f"Updating forecast for {location.city}, {location.country}",
                level="info",
                data={
                    "location_id": location.id,
                    "location_city": location.city,
                    "location_country": location.country,
                    "latitude": location.latitude,
                    "longitude": location.longitude
                }
            )

            set_tag("location", f"{location.city}, {location.country}")
            set_tag("operation", "weather_update")

            try:
                # Fetch forecast data from the API
                forecast_data = self.api_client.get_forecast(
                    latitude=location.latitude,
                    longitude=location.longitude,
                    days=3
                )

                if not forecast_data:
                    logger.error(f"Failed to fetch forecast data for location: {location}")

                    # Add context for debugging
                    set_context("weather_fetch_failure", {
                        "location": f"{location.city}, {location.country}",
                        "location_id": location.id,
                        "latitude": location.latitude,
                        "longitude": location.longitude,
                        "api_client": "OpenMeteo"
                    })

                    # Capture as a message (not exception since API returned None)
                    capture_message(
                        f"Weather API returned no data for {location.city}, {location.country}",
                        level="warning"
                    )

                    return 0, 0

                # Parse the forecast data
                parsed_data = self.api_client.parse_forecast_data(forecast_data, location)

                if not parsed_data:
                    logger.warning(f"No valid forecast data parsed for location: {location}")
                    capture_message(
                        f"No valid forecast data parsed for {location.city}, {location.country}",
                        level="warning"
                    )
                    return 0, 0

                # Store the forecast data in the database using update_or_create
                created_count = 0
                updated_count = 0

                for entry in parsed_data:
                    # Extract the unique key fields
                    location_obj = entry.pop('location')
                    target_time = entry.pop('target_time')

                    # Use update_or_create to avoid duplicates
                    forecast, created = WeatherForecast.objects.update_or_create(
                        location=location_obj,
                        target_time=target_time,
                        defaults=entry
                    )

                    if created:
                        created_count += 1
                    else:
                        updated_count += 1

                logger.info(f"Created {created_count} and updated {updated_count} forecast entries for {location}")

                add_breadcrumb(
                    category="weather",
                    message=f"Forecast update completed for {location.city}, {location.country}",
                    level="info",
                    data={
                        "created": created_count,
                        "updated": updated_count
                    }
                )

                return created_count, updated_count

            except Exception as e:
                # Capture unexpected exceptions
                set_context("weather_update_error", {
                    "location": f"{location.city}, {location.country}",
                    "location_id": location.id,
                    "operation": "update_forecast_for_location_upsert"
                })
                capture_exception(e)
                logger.error(f"Error updating forecast for {location}: {str(e)}")
                raise

    def update_all_forecasts(self):
        """
        Update weather forecasts for all locations in the database.

        Returns:
            dict: Dictionary mapping location IDs to lists of created forecasts
        """
        locations = Location.objects.all()
        results = {}

        for location in locations:
            forecasts = self.update_forecast_for_location(location)
            results[location.id] = forecasts

        return results

    def get_latest_forecast(self, location):
        """
        Get the latest weather forecast for a specific location.

        Args:
            location (Location): The location model instance

        Returns:
            WeatherForecast: The latest forecast for the location
        """
        return WeatherForecast.objects.filter(location=location).order_by("-forecast_time", "target_time").first()

    def get_forecasts_for_timeframe(self, location, start_time, end_time):
        """
        Get weather forecasts for a specific location and timeframe.

        Args:
            location (Location): The location model instance
            start_time (datetime): Start of the timeframe
            end_time (datetime): End of the timeframe

        Returns:
            QuerySet: WeatherForecast instances for the specified timeframe
        """
        return WeatherForecast.objects.filter(
            location=location, target_time__gte=start_time, target_time__lte=end_time
        ).order_by("target_time")
