import logging
from datetime import datetime, timedelta
import numpy as np
from django.utils import timezone

from .models import Location, WeatherForecast, MigrainePrediction

logger = logging.getLogger(__name__)

class MigrainePredictionService:
    """
    Service for predicting migraine probability based on weather forecast data.
    """
    
    # Weather parameters thresholds associated with migraine triggers
    # These thresholds are based on research about weather-related migraine triggers
    THRESHOLDS = {
        'temperature_change': 5.0,      # Celsius - significant temperature change
        'humidity_high': 70.0,          # Percentage - high humidity
        'humidity_low': 30.0,           # Percentage - low humidity
        'pressure_change': 5.0,         # hPa - significant pressure change
        'pressure_low': 1005.0,         # hPa - low pressure system
        'precipitation_high': 5.0,      # mm - heavy precipitation
        'cloud_cover_high': 80.0,       # Percentage - heavy cloud cover
    }
    
    # Weights for different weather parameters in prediction
    WEIGHTS = {
        'temperature_change': 0.25,
        'humidity_extreme': 0.15,
        'pressure_change': 0.30,
        'pressure_low': 0.15,
        'precipitation': 0.05,
        'cloud_cover': 0.10,
    }
    
    def __init__(self):
        """Initialize the migraine prediction service."""
        pass
    
    def predict_migraine_probability(self, location, user=None, store_prediction=True):
        """
        Predict migraine probability for a specific location and user.
        
        Args:
            location (Location): The location model instance
            user (User, optional): The user model instance
            
        Returns:
            tuple: (probability_level, prediction_instance)
        """
        # Get recent forecasts for the next 3-6 hours
        now = timezone.now()
        start_time = now
        end_time = now + timedelta(hours=6)
        
        forecasts = WeatherForecast.objects.filter(
            location=location,
            target_time__gte=start_time,
            target_time__lte=end_time
        ).order_by('target_time')
        
        if not forecasts:
            logger.warning(f"No forecasts available for location {location} in the 3-6 hour window")
            return None, None
        
        # Get previous forecasts for comparison
        previous_forecasts = WeatherForecast.objects.filter(
            location=location,
            target_time__lt=start_time
        ).order_by('-target_time')[:6]  # Last 6 hours
        
        # Calculate scores for different weather factors
        scores = self._calculate_weather_scores(forecasts, previous_forecasts)
        
        # Calculate overall probability score (0-1)
        total_score = sum(scores[factor] * self.WEIGHTS[factor] for factor in scores)
        
        # Determine probability level
        if total_score >= 0.7:
            probability_level = 'HIGH'
        elif total_score >= 0.4:
            probability_level = 'MEDIUM'
        else:
            probability_level = 'LOW'
        
        # Create prediction record
        if user and store_prediction:
            prediction = MigrainePrediction.objects.create(
                user=user,
                location=location,
                forecast=forecasts.first(),
                target_time_start=start_time,
                target_time_end=end_time,
                probability=probability_level
            )
        else:
            prediction = None
            
        return probability_level, prediction
    
    def _calculate_weather_scores(self, forecasts, previous_forecasts):
        """
        Calculate scores for different weather factors.
        
        Args:
            forecasts (QuerySet): Forecasts for the prediction window
            previous_forecasts (QuerySet): Previous forecasts for comparison
            
        Returns:
            dict: Scores for different weather factors (0-1)
        """
        scores = {
            'temperature_change': 0.0,
            'humidity_extreme': 0.0,
            'pressure_change': 0.0,
            'pressure_low': 0.0,
            'precipitation': 0.0,
            'cloud_cover': 0.0,
        }
        
        # Skip if we don't have enough data
        if not forecasts or not previous_forecasts:
            return scores
        
        # Calculate temperature change
        if previous_forecasts:
            avg_prev_temp = np.mean([f.temperature for f in previous_forecasts])
            avg_forecast_temp = np.mean([f.temperature for f in forecasts])
            temp_change = abs(avg_forecast_temp - avg_prev_temp)
            
            # Score based on temperature change threshold
            scores['temperature_change'] = min(temp_change / self.THRESHOLDS['temperature_change'], 1.0)
        
        # Calculate humidity extremes
        avg_humidity = np.mean([f.humidity for f in forecasts])
        if avg_humidity >= self.THRESHOLDS['humidity_high']:
            # High humidity score
            scores['humidity_extreme'] = (avg_humidity - self.THRESHOLDS['humidity_high']) / (100 - self.THRESHOLDS['humidity_high'])
        elif avg_humidity <= self.THRESHOLDS['humidity_low']:
            # Low humidity score
            scores['humidity_extreme'] = (self.THRESHOLDS['humidity_low'] - avg_humidity) / self.THRESHOLDS['humidity_low']
        
        # Calculate pressure change
        if previous_forecasts:
            avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
            avg_forecast_pressure = np.mean([f.pressure for f in forecasts])
            pressure_change = abs(avg_forecast_pressure - avg_prev_pressure)
            
            # Score based on pressure change threshold
            scores['pressure_change'] = min(pressure_change / self.THRESHOLDS['pressure_change'], 1.0)
        
        # Calculate low pressure score
        avg_pressure = np.mean([f.pressure for f in forecasts])
        if avg_pressure <= self.THRESHOLDS['pressure_low']:
            # Low pressure score
            scores['pressure_low'] = (self.THRESHOLDS['pressure_low'] - avg_pressure) / 20.0  # Normalize to 0-1
        
        # Calculate precipitation score
        max_precipitation = max([f.precipitation for f in forecasts], default=0)
        scores['precipitation'] = min(max_precipitation / self.THRESHOLDS['precipitation_high'], 1.0)
        
        # Calculate cloud cover score
        avg_cloud_cover = np.mean([f.cloud_cover for f in forecasts])
        scores['cloud_cover'] = min(avg_cloud_cover / self.THRESHOLDS['cloud_cover_high'], 1.0)
        
        return scores
    
    def get_recent_predictions(self, user, limit=10):
        """
        Get recent migraine predictions for a user.
        
        Args:
            user (User): The user model instance
            limit (int, optional): Maximum number of predictions to return
            
        Returns:
            QuerySet: Recent MigrainePrediction instances
        """
        return MigrainePrediction.objects.filter(
            user=user
        ).order_by('-prediction_time')[:limit]
