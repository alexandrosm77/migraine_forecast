import logging
import requests
from datetime import datetime, timedelta
import numpy as np
from django.utils import timezone

from .models import Location, WeatherForecast, ActualWeather, WeatherComparisonReport
from .tools import ensure_timezone_aware
from .weather_api import OpenMeteoClient

logger = logging.getLogger(__name__)

class DataComparisonService:
    """
    Service for comparing forecasted weather data with actual weather data.
    """
    
    def __init__(self):
        """Initialize the data comparison service."""
        self.api_client = OpenMeteoClient()
    
    def collect_actual_weather(self, location):
        """
        Collect actual weather data for a specific location.
        
        Args:
            location (Location): The location model instance
            
        Returns:
            ActualWeather: The created ActualWeather instance
        """
        # Use the API to get current weather data
        params = {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "current": ",".join([
                "temperature_2m",
                "relative_humidity_2m",
                "surface_pressure",
                "precipitation",
                "cloud_cover",
                "wind_speed_10m"
            ]),
            "timezone": "auto"
        }
        
        try:
            # Use the Open-Meteo API to get current weather
            response = requests.get(self.api_client.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()
            
            if "current" not in data:
                logger.error(f"Invalid current weather data format for location {location}")
                return None
            
            current = data["current"]
            
            # Create ActualWeather record
            actual_weather = ActualWeather.objects.create(
                location=location,
                recorded_time=ensure_timezone_aware(datetime.fromisoformat(current.get("time", timezone.now().isoformat()))),
                temperature=current.get("temperature_2m", 0),
                humidity=current.get("relative_humidity_2m", 0),
                pressure=current.get("surface_pressure", 0),
                wind_speed=current.get("wind_speed_10m", 0),
                precipitation=current.get("precipitation", 0),
                cloud_cover=current.get("cloud_cover", 0)
            )
            
            logger.info(f"Collected actual weather data for {location}")
            return actual_weather
            
        except Exception as e:
            logger.error(f"Error collecting actual weather data: {e}")
            return None
    
    def compare_forecast_with_actual(self, forecast, actual):
        """
        Compare forecasted weather data with actual weather data.
        
        Args:
            forecast (WeatherForecast): The forecast model instance
            actual (ActualWeather): The actual weather model instance
            
        Returns:
            WeatherComparisonReport: The created comparison report
        """
        if not forecast or not actual:
            logger.error("Cannot compare: missing forecast or actual data")
            return None
        
        # Calculate differences between forecast and actual values
        temperature_diff = abs(forecast.temperature - actual.temperature)
        humidity_diff = abs(forecast.humidity - actual.humidity)
        pressure_diff = abs(forecast.pressure - actual.pressure)
        wind_speed_diff = abs(forecast.wind_speed - actual.wind_speed)
        precipitation_diff = abs(forecast.precipitation - actual.precipitation)
        cloud_cover_diff = abs(forecast.cloud_cover - actual.cloud_cover)
        
        # Create comparison report
        report = WeatherComparisonReport.objects.create(
            location=forecast.location,
            forecast=forecast,
            actual=actual,
            temperature_diff=temperature_diff,
            humidity_diff=humidity_diff,
            pressure_diff=pressure_diff,
            wind_speed_diff=wind_speed_diff,
            precipitation_diff=precipitation_diff,
            cloud_cover_diff=cloud_cover_diff
        )
        
        logger.info(f"Created comparison report for {forecast.location} at {actual.recorded_time}")
        return report
    
    def generate_comparison_for_location(self, location):
        """
        Generate comparison between forecast and actual weather for a location.
        
        Args:
            location (Location): The location model instance
            
        Returns:
            list: List of created WeatherComparisonReport instances
        """
        # Collect actual weather data
        actual = self.collect_actual_weather(location)
        if not actual:
            return []
        
        # Find forecasts that predicted this time period
        time_threshold = timedelta(hours=1)
        relevant_forecasts = WeatherForecast.objects.filter(
            location=location,
            target_time__gte=actual.recorded_time - time_threshold,
            target_time__lte=actual.recorded_time + time_threshold
        )
        
        # Compare each relevant forecast with the actual data
        reports = []
        for forecast in relevant_forecasts:
            report = self.compare_forecast_with_actual(forecast, actual)
            if report:
                reports.append(report)
        
        return reports
    
    def generate_all_comparisons(self):
        """
        Generate comparisons for all locations.
        
        Returns:
            dict: Dictionary mapping location IDs to lists of created reports
        """
        locations = Location.objects.all()
        results = {}
        
        for location in locations:
            reports = self.generate_comparison_for_location(location)
            results[location.id] = reports
        
        return results
    
    def get_forecast_accuracy_metrics(self, location, days=30):
        """
        Calculate forecast accuracy metrics for a location over a time period.
        
        Args:
            location (Location): The location model instance
            days (int): Number of days to look back
            
        Returns:
            dict: Dictionary containing accuracy metrics
        """
        start_date = timezone.now() - timedelta(days=days)
        
        # Get comparison reports for the specified time period
        reports = WeatherComparisonReport.objects.filter(
            location=location,
            created_at__gte=start_date
        )
        
        if not reports:
            return {
                "count": 0,
                "avg_temperature_diff": 0,
                "avg_humidity_diff": 0,
                "avg_pressure_diff": 0,
                "avg_wind_speed_diff": 0,
                "avg_precipitation_diff": 0,
                "avg_cloud_cover_diff": 0
            }
        
        # Calculate average differences
        avg_temperature_diff = np.mean([r.temperature_diff for r in reports])
        avg_humidity_diff = np.mean([r.humidity_diff for r in reports])
        avg_pressure_diff = np.mean([r.pressure_diff for r in reports])
        avg_wind_speed_diff = np.mean([r.wind_speed_diff for r in reports])
        avg_precipitation_diff = np.mean([r.precipitation_diff for r in reports])
        avg_cloud_cover_diff = np.mean([r.cloud_cover_diff for r in reports])
        
        return {
            "count": len(reports),
            "avg_temperature_diff": avg_temperature_diff,
            "avg_humidity_diff": avg_humidity_diff,
            "avg_pressure_diff": avg_pressure_diff,
            "avg_wind_speed_diff": avg_wind_speed_diff,
            "avg_precipitation_diff": avg_precipitation_diff,
            "avg_cloud_cover_diff": avg_cloud_cover_diff
        }
