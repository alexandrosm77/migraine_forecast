from .models import Location, WeatherForecast, AirQualityForecast
from .weather_api import OpenMeteoClient
from .air_quality_api import OpenMeteoAirQualityClient
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
        self.air_quality_client = OpenMeteoAirQualityClient()

    # Fields to update on conflict for WeatherForecast bulk upsert
    _WEATHER_UPDATE_FIELDS = [
        "forecast_time", "temperature", "humidity", "pressure",
        "wind_speed", "precipitation", "cloud_cover",
    ]

    # Fields to update on conflict for AirQualityForecast bulk upsert
    _AQ_UPDATE_FIELDS = [
        "forecast_time", "alder_pollen", "birch_pollen", "grass_pollen",
        "mugwort_pollen", "olive_pollen", "ragweed_pollen",
        "pm10", "pm2_5", "ozone", "nitrogen_dioxide", "dust",
        "uv_index", "european_aqi", "us_aqi",
    ]

    def _bulk_upsert_weather(self, parsed_data):
        """
        Bulk upsert WeatherForecast rows using INSERT … ON CONFLICT UPDATE.
        Returns (created_count, updated_count).
        """
        if not parsed_data:
            return 0, 0

        objs = [WeatherForecast(**entry) for entry in parsed_data]
        before_count = WeatherForecast.objects.count()

        WeatherForecast.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=["location", "target_time"],
            update_fields=self._WEATHER_UPDATE_FIELDS,
        )

        after_count = WeatherForecast.objects.count()
        created_count = after_count - before_count
        updated_count = len(objs) - created_count
        return created_count, updated_count

    def _bulk_upsert_air_quality(self, parsed_data):
        """
        Bulk upsert AirQualityForecast rows using INSERT … ON CONFLICT UPDATE.
        Returns (created_count, updated_count).
        """
        if not parsed_data:
            return 0, 0

        objs = [AirQualityForecast(**entry) for entry in parsed_data]
        before_count = AirQualityForecast.objects.count()

        AirQualityForecast.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=["location", "target_time"],
            update_fields=self._AQ_UPDATE_FIELDS,
        )

        after_count = AirQualityForecast.objects.count()
        created_count = after_count - before_count
        updated_count = len(objs) - created_count
        return created_count, updated_count


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

                # Bulk upsert forecast data to avoid N+1 queries
                created_count, updated_count = self._bulk_upsert_weather(parsed_data)

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

                    # Bulk upsert forecast data to avoid N+1 queries
                    created_count, updated_count = self._bulk_upsert_weather(parsed_data)

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

    def update_air_quality_for_location(self, location):
        """
        Update air-quality forecast for a specific location using upsert pattern.

        Args:
            location (Location): The location model instance

        Returns:
            tuple: (created_count, updated_count)
        """
        with start_transaction(op="air_quality.update", name=f"update_air_quality_{location.city}"):
            logger.info(f"Starting update_air_quality_for_location for location: {location}")

            add_breadcrumb(
                category="air_quality",
                message=f"Updating air-quality forecast for {location.city}, {location.country}",
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
            set_tag("operation", "air_quality_update")

            try:
                forecast_data = self.air_quality_client.get_forecast(
                    latitude=location.latitude, longitude=location.longitude
                )

                if not forecast_data:
                    logger.error(f"Failed to fetch air-quality data for location: {location}")
                    set_context(
                        "air_quality_fetch_failure",
                        {
                            "location": f"{location.city}, {location.country}",
                            "location_id": location.id,
                            "latitude": location.latitude,
                            "longitude": location.longitude,
                            "api_client": "OpenMeteoAirQuality",
                        },
                    )
                    capture_message(
                        f"Air-quality API returned no data for {location.city}, {location.country}",
                        level="warning",
                    )
                    return 0, 0

                parsed_data = self.air_quality_client.parse_forecast_data(forecast_data, location)

                if not parsed_data:
                    logger.warning(f"No valid air-quality data parsed for location: {location}")
                    capture_message(
                        f"No valid air-quality data parsed for {location.city}, {location.country}",
                        level="warning",
                    )
                    return 0, 0

                # Bulk upsert air-quality data to avoid N+1 queries
                created_count, updated_count = self._bulk_upsert_air_quality(parsed_data)

                logger.info(
                    f"Created {created_count} and updated {updated_count} air-quality entries for {location}"
                )

                add_breadcrumb(
                    category="air_quality",
                    message=f"Air-quality update completed for {location.city}, {location.country}",
                    level="info",
                    data={"created": created_count, "updated": updated_count},
                )

                return created_count, updated_count

            except Exception as e:
                set_context(
                    "air_quality_update_error",
                    {
                        "location": f"{location.city}, {location.country}",
                        "location_id": location.id,
                        "operation": "update_air_quality_for_location",
                    },
                )
                capture_exception(e)
                logger.error(f"Error updating air-quality forecast for {location}: {str(e)}")
                raise

    def update_air_quality_for_locations_batch(self, locations):
        """
        Update air-quality forecasts for multiple locations using batch API.

        Args:
            locations (list): List of Location model instances (max 50)

        Returns:
            dict: {
                'total_created': int,
                'total_updated': int,
                'location_results': {location_id: {'created': int, 'updated': int}, ...},
                'errors': [{'location': Location, 'error': str}, ...],
            }
        """
        if not locations:
            logger.warning("update_air_quality_for_locations_batch called with empty locations list")
            return {"total_created": 0, "total_updated": 0, "location_results": {}, "errors": []}

        if len(locations) > 50:
            raise ValueError("Batch size cannot exceed 50 locations")

        location_details = [f"{loc.city}, {loc.country} (ID: {loc.id})" for loc in locations]

        logger.info(f"Starting batch air-quality update for {len(locations)} locations: {location_details}")

        add_breadcrumb(
            category="air_quality",
            message=f"Batch updating air-quality forecasts for {len(locations)} locations",
            level="info",
            data={"location_count": len(locations), "locations": location_details},
        )

        total_created = 0
        total_updated = 0
        location_results = {}
        errors = []

        try:
            batch_results = self.air_quality_client.get_forecast_batch(locations)

            if batch_results is None:
                error_msg = f"Batch air-quality API call failed for {len(locations)} locations"
                logger.error(error_msg)
                capture_message(error_msg, level="error")

                for location in locations:
                    errors.append({"location": location, "error": "Batch API call failed"})
                    location_results[location.id] = {"created": 0, "updated": 0}

                return {
                    "total_created": 0,
                    "total_updated": 0,
                    "location_results": location_results,
                    "errors": errors,
                }

            parsed_batch = self.air_quality_client.parse_forecast_data_batch(batch_results)

            for location in locations:
                try:
                    parsed_data = parsed_batch.get(location, [])

                    if not parsed_data:
                        logger.warning(f"No valid air-quality data parsed for location: {location}")
                        errors.append({"location": location, "error": "No valid air-quality data parsed"})
                        location_results[location.id] = {"created": 0, "updated": 0}
                        continue

                    # Bulk upsert air-quality data to avoid N+1 queries
                    created_count, updated_count = self._bulk_upsert_air_quality(parsed_data)

                    total_created += created_count
                    total_updated += updated_count
                    location_results[location.id] = {"created": created_count, "updated": updated_count}

                    logger.info(
                        f"Batch AQ: Created {created_count} and updated {updated_count} entries for {location}"
                    )

                except Exception as e:
                    error_msg = f"Error processing air-quality data for {location}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    errors.append({"location": location, "error": str(e)})
                    location_results[location.id] = {"created": 0, "updated": 0}

                    set_context(
                        "air_quality_batch_location_error",
                        {
                            "location": f"{location.city}, {location.country}",
                            "location_id": location.id,
                            "operation": "update_air_quality_for_locations_batch",
                        },
                    )
                    capture_exception(e)

            add_breadcrumb(
                category="air_quality",
                message=f"Batch air-quality update completed for {len(locations)} locations",
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
            error_msg = f"Unexpected error in batch air-quality update: {str(e)}"
            logger.error(error_msg, exc_info=True)

            set_context(
                "air_quality_batch_error",
                {"location_count": len(locations), "locations": location_details, "operation": "batch_update"},
            )
            capture_exception(e)

            for location in locations:
                errors.append({"location": location, "error": str(e)})
                location_results[location.id] = {"created": 0, "updated": 0}

            return {
                "total_created": 0,
                "total_updated": 0,
                "location_results": location_results,
                "errors": errors,
            }
