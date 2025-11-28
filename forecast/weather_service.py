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
                    "longitude": location.longitude,
                },
            )

            set_tag("location", f"{location.city}, {location.country}")
            set_tag("operation", "weather_update")

            try:
                # Fetch forecast data from the API
                forecast_data = self.api_client.get_forecast(
                    latitude=location.latitude, longitude=location.longitude, days=3
                )

                if not forecast_data:
                    logger.error(f"Failed to fetch forecast data for location: {location}")

                    # Add context for debugging
                    set_context(
                        "weather_fetch_failure",
                        {
                            "location": f"{location.city}, {location.country}",
                            "location_id": location.id,
                            "latitude": location.latitude,
                            "longitude": location.longitude,
                            "api_client": "OpenMeteo",
                        },
                    )

                    # Capture as a message (not exception since API returned None)
                    capture_message(
                        f"Weather API returned no data for {location.city}, {location.country}", level="warning"
                    )

                    return 0, 0

                # Parse the forecast data
                parsed_data = self.api_client.parse_forecast_data(forecast_data, location)

                if not parsed_data:
                    logger.warning(f"No valid forecast data parsed for location: {location}")
                    capture_message(
                        f"No valid forecast data parsed for {location.city}, {location.country}", level="warning"
                    )
                    return 0, 0

                # Store the forecast data in the database using update_or_create
                created_count = 0
                updated_count = 0

                for entry in parsed_data:
                    # Extract the unique key fields
                    location_obj = entry.pop("location")
                    target_time = entry.pop("target_time")

                    # Use update_or_create to avoid duplicates
                    forecast, created = WeatherForecast.objects.update_or_create(
                        location=location_obj, target_time=target_time, defaults=entry
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
                    data={"created": created_count, "updated": updated_count},
                )

                return created_count, updated_count

            except Exception as e:
                # Capture unexpected exceptions
                set_context(
                    "weather_update_error",
                    {
                        "location": f"{location.city}, {location.country}",
                        "location_id": location.id,
                        "operation": "update_forecast_for_location_upsert",
                    },
                )
                capture_exception(e)
                logger.error(f"Error updating forecast for {location}: {str(e)}")
                raise

    def update_forecast_for_locations_batch(self, locations):
        """
        Update weather forecasts for multiple locations using batch API.
        This reduces API calls by batching up to 50 locations per request.

        Args:
            locations (list): List of Location model instances (max 50)

        Returns:
            dict: Dictionary with batch results
                  Format: {
                      'total_created': int,
                      'total_updated': int,
                      'location_results': {location_id: {'created': int, 'updated': int}, ...},
                      'errors': [{'location': Location, 'error': str}, ...]
                  }
        """
        if not locations:
            logger.warning("update_forecast_for_locations_batch called with empty locations list")
            return {"total_created": 0, "total_updated": 0, "location_results": {}, "errors": []}

        if len(locations) > 50:
            raise ValueError("Batch size cannot exceed 50 locations")

        # Build location details for logging
        location_details = [f"{loc.city}, {loc.country} (ID: {loc.id})" for loc in locations]

        logger.info(f"Starting batch forecast update for {len(locations)} locations: {location_details}")

        add_breadcrumb(
            category="weather",
            message=f"Batch updating forecasts for {len(locations)} locations",
            level="info",
            data={"location_count": len(locations), "locations": location_details},
        )

        # Initialize results
        total_created = 0
        total_updated = 0
        location_results = {}
        errors = []

        try:
            # Fetch batch forecast data from the API
            batch_results = self.api_client.get_forecast_batch(locations, days=3)

            if batch_results is None:
                # Batch API call failed completely
                error_msg = f"Batch API call failed for {len(locations)} locations"
                logger.error(error_msg)
                capture_message(error_msg, level="error")

                # Record error for all locations in the batch
                for location in locations:
                    errors.append({"location": location, "error": "Batch API call failed"})
                    location_results[location.id] = {"created": 0, "updated": 0}

                return {
                    "total_created": 0,
                    "total_updated": 0,
                    "location_results": location_results,
                    "errors": errors,
                }

            # Parse the batch forecast data
            parsed_batch = self.api_client.parse_forecast_data_batch(batch_results)

            # Process each location's forecast data
            for location in locations:
                try:
                    parsed_data = parsed_batch.get(location, [])

                    if not parsed_data:
                        logger.warning(f"No valid forecast data parsed for location: {location}")
                        errors.append({"location": location, "error": "No valid forecast data parsed"})
                        location_results[location.id] = {"created": 0, "updated": 0}
                        continue

                    # Store the forecast data in the database using update_or_create
                    created_count = 0
                    updated_count = 0

                    for entry in parsed_data:
                        # Extract the unique key fields
                        location_obj = entry.pop("location")
                        target_time = entry.pop("target_time")

                        # Use update_or_create to avoid duplicates
                        forecast, created = WeatherForecast.objects.update_or_create(
                            location=location_obj, target_time=target_time, defaults=entry
                        )

                        if created:
                            created_count += 1
                        else:
                            updated_count += 1

                    total_created += created_count
                    total_updated += updated_count
                    location_results[location.id] = {"created": created_count, "updated": updated_count}

                    logger.info(
                        f"Batch: Created {created_count} and updated {updated_count} forecast entries for {location}"
                    )

                except Exception as e:
                    error_msg = f"Error processing forecast data for {location}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    errors.append({"location": location, "error": str(e)})
                    location_results[location.id] = {"created": 0, "updated": 0}

                    # Capture exception with context
                    set_context(
                        "weather_batch_location_error",
                        {
                            "location": f"{location.city}, {location.country}",
                            "location_id": location.id,
                            "operation": "update_forecast_for_locations_batch",
                        },
                    )
                    capture_exception(e)

            add_breadcrumb(
                category="weather",
                message=f"Batch forecast update completed for {len(locations)} locations",
                level="info",
                data={
                    "total_created": total_created,
                    "total_updated": total_updated,
                    "errors": len(errors),
                },
            )

            return {
                "total_created": total_created,
                "total_updated": total_updated,
                "location_results": location_results,
                "errors": errors,
            }

        except Exception as e:
            # Capture unexpected exceptions at batch level
            error_msg = f"Unexpected error in batch forecast update: {str(e)}"
            logger.error(error_msg, exc_info=True)

            set_context(
                "weather_batch_error",
                {"location_count": len(locations), "locations": location_details, "operation": "batch_update"},
            )
            capture_exception(e)

            # Record error for all locations in the batch
            for location in locations:
                errors.append({"location": location, "error": str(e)})
                location_results[location.id] = {"created": 0, "updated": 0}

            return {
                "total_created": 0,
                "total_updated": 0,
                "location_results": location_results,
                "errors": errors,
            }

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
