from .models import Location, WeatherForecast
from .weather_api import OpenMeteoClient
import logging

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
