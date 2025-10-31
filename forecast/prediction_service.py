import logging
from datetime import datetime, timedelta
import numpy as np
from django.utils import timezone
from django.conf import settings

from .models import Location, WeatherForecast, MigrainePrediction, UserHealthProfile, LLMResponse
from .llm_client import LLMClient

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
        start_time = timezone.now()
        end_time = start_time + timedelta(hours=6)
        
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

        # Optionally adjust scores/weights based on user health profile
        adjusted_weights = dict(self.WEIGHTS)
        applied_profile = None
        if user is not None:
            try:
                profile = user.health_profile
                applied_profile = {
                    'sensitivity_overall': profile.sensitivity_overall,
                    'sensitivity_temperature': profile.sensitivity_temperature,
                    'sensitivity_humidity': profile.sensitivity_humidity,
                    'sensitivity_pressure': profile.sensitivity_pressure,
                    'sensitivity_cloud_cover': profile.sensitivity_cloud_cover,
                    'sensitivity_precipitation': profile.sensitivity_precipitation,
                }
                # Map weight keys to profile keys and adjust weights
                factor_to_profile = {
                    'temperature_change': 'sensitivity_temperature',
                    'humidity_extreme': 'sensitivity_humidity',
                    'pressure_change': 'sensitivity_pressure',
                    'pressure_low': 'sensitivity_pressure',
                    'precipitation': 'sensitivity_precipitation',
                    'cloud_cover': 'sensitivity_cloud_cover',
                }
                for k, w in adjusted_weights.items():
                    pk = factor_to_profile.get(k)
                    if pk:
                        adjusted_weights[k] = max(0.0, w * profile.sensitivity_overall * getattr(profile, pk, 1.0))
                # Re-normalize weights to sum to 1.0 to keep score scale comparable
                total_w = sum(adjusted_weights.values())
                if total_w > 0:
                    for k in adjusted_weights:
                        adjusted_weights[k] = adjusted_weights[k] / total_w
            except UserHealthProfile.DoesNotExist:
                pass
            except Exception:
                logger.exception("Failed to apply user health profile, proceeding with default weights")

        factors_payload = dict(scores)
        if applied_profile is not None:
            factors_payload['applied_profile'] = applied_profile
            factors_payload['weights'] = adjusted_weights

        # Try LLM prediction first as the main prediction engine
        llm_used = False
        llm_detail = None
        probability_level = None

        if getattr(settings, 'LLM_ENABLED', True):
            try:
                base_url = getattr(settings, 'LLM_BASE_URL', 'http://localhost:11434')
                api_key = getattr(settings, 'LLM_API_KEY', '')
                model = getattr(settings, 'LLM_MODEL', 'ibm/granite4:tiny-h')
                timeout = getattr(settings, 'LLM_TIMEOUT', 8.0)
                client = LLMClient(base_url=base_url, api_key=api_key, model=model, timeout=timeout)
                loc_label = f"{location.city}, {location.country}"
                # Build minimal context with only essential aggregates and changes
                try:
                    fc_list = list(forecasts)
                    prev_list = list(previous_forecasts)
                    # Only send aggregates and changes, not raw samples (reduces token count significantly)
                    context_payload = {
                        'aggregates': {
                            'avg_forecast_temperature': round(float(np.mean([f.temperature for f in fc_list])), 1) if fc_list else None,
                            'avg_forecast_humidity': round(float(np.mean([f.humidity for f in fc_list])), 0) if fc_list else None,
                            'avg_forecast_pressure': round(float(np.mean([f.pressure for f in fc_list])), 1) if fc_list else None,
                            'max_precipitation': round(float(max([f.precipitation for f in fc_list], default=0)), 1),
                        },
                        'changes': {
                            'temperature_change': round(float(abs((np.mean([f.temperature for f in fc_list]) if fc_list else 0) - (np.mean([f.temperature for f in prev_list]) if prev_list else 0))), 1),
                            'pressure_change': round(float(abs((np.mean([f.pressure for f in fc_list]) if fc_list else 0) - (np.mean([f.pressure for f in prev_list]) if prev_list else 0))), 1),
                        },
                    }

                    # Add compact temporal context
                    hours_ahead = round((end_time - start_time).total_seconds() / 3600, 1)
                    hour_of_day = start_time.hour
                    if 5 <= hour_of_day < 12:
                        day_period = "morning"
                    elif 12 <= hour_of_day < 17:
                        day_period = "afternoon"
                    elif 17 <= hour_of_day < 21:
                        day_period = "evening"
                    else:
                        day_period = "night"

                    context_payload['forecast_time'] = {
                        'hours_ahead': hours_ahead,
                        'day_period': day_period,
                    }

                    # Add summarized previous predictions (last 24h only)
                    if user:
                        from datetime import timedelta
                        recent_predictions = MigrainePrediction.objects.filter(
                            user=user,
                            location=location,
                            prediction_time__gte=start_time - timedelta(hours=24)
                        ).values_list('probability', flat=True)

                        if recent_predictions:
                            pred_list = list(recent_predictions)
                            context_payload['previous_predictions'] = {
                                'count': len(pred_list),
                                'high_count': pred_list.count('HIGH'),
                                'medium_count': pred_list.count('MEDIUM'),
                                'low_count': pred_list.count('LOW'),
                            }

                    # Add summarized previous weather forecasts (last 12-24h)
                    # This helps LLM understand recent weather trends
                    if prev_list:
                        # Get weather from 12-24h ago for trend analysis
                        older_forecasts = WeatherForecast.objects.filter(
                            location=location,
                            target_time__gte=start_time - timedelta(hours=24),
                            target_time__lt=start_time - timedelta(hours=12)
                        ).order_by('target_time')

                        if older_forecasts.exists():
                            older_list = list(older_forecasts)
                            # Calculate trends: are conditions getting worse or better?
                            prev_avg_temp = np.mean([f.temperature for f in prev_list]) if prev_list else 0
                            older_avg_temp = np.mean([f.temperature for f in older_list]) if older_list else 0
                            prev_avg_pressure = np.mean([f.pressure for f in prev_list]) if prev_list else 0
                            older_avg_pressure = np.mean([f.pressure for f in older_list]) if older_list else 0

                            # Only include if there's a meaningful trend
                            temp_trend = prev_avg_temp - older_avg_temp
                            pressure_trend = prev_avg_pressure - older_avg_pressure

                            if abs(temp_trend) > 2 or abs(pressure_trend) > 3:
                                context_payload['weather_trend'] = {
                                    'temp_trend': round(float(temp_trend), 1),
                                    'pressure_trend': round(float(pressure_trend), 1),
                                }

                except Exception:
                    logger.exception('Failed building LLM context payload')
                    context_payload = {}

                llm_level, llm_detail = client.predict_probability(
                    scores=factors_payload,
                    location_label=loc_label,
                    user_profile=applied_profile,
                    context=context_payload,
                )
                if llm_level in {'LOW', 'MEDIUM', 'HIGH'}:
                    llm_used = True
                    probability_level = llm_level
                    logger.info(f'LLM prediction successful: {probability_level}')
                else:
                    logger.warning('LLM returned invalid probability level, will fall back to manual calculation')
            except Exception:
                logger.exception('LLM prediction failed; falling back to manual calculation')

        # Fallback to manual calculation if LLM is disabled or failed
        if probability_level is None:
            logger.info('Using manual calculation for prediction')
            # Calculate overall probability score (0-1)
            total_score = sum(scores[factor] * adjusted_weights.get(factor, 0.0) for factor in scores)

            # Determine probability level (shift thresholds slightly by overall sensitivity)
            high_thr = 0.7
            med_thr = 0.4
            if user is not None and applied_profile is not None:
                overall = applied_profile.get('sensitivity_overall', 1.0)
                # More sensitive → lower thresholds; less sensitive → higher thresholds (clamped)
                shift = (overall - 1.0) * 0.15  # max +/- 15% threshold shift per overall unit
                high_thr = min(max(high_thr - shift, 0.5), 0.9)
                med_thr = min(max(med_thr - shift, 0.25), 0.7)

            if total_score >= high_thr:
                probability_level = 'HIGH'
            elif total_score >= med_thr:
                probability_level = 'MEDIUM'
            else:
                probability_level = 'LOW'

        # Add LLM details to factors payload if available
        if llm_detail is not None:
            factors_payload['llm'] = {
                'used': llm_used,
                'detail': llm_detail,
            }
            try:
                parsed = (llm_detail or {}).get('raw') or {}
                factors_payload['llm_analysis_text'] = parsed.get('analysis_text')
                factors_payload['llm_prevention_tips'] = parsed.get('prevention_tips')
            except Exception:
                logger.exception('Failed to extract LLM analysis/tips')

        prediction = MigrainePrediction(
            user=user,
            location=location,
            forecast=forecasts.first(),
            target_time_start=start_time,
            target_time_end=end_time,
            probability=probability_level,
            weather_factors=factors_payload
        )
        
        # Create prediction record
        if user:
            if store_prediction:
                prediction.save()
                # Persist LLM response if available
                try:
                    if llm_detail is not None:
                        LLMResponse.objects.create(
                            user=user,
                            location=location,
                            prediction=prediction,
                            request_payload=(llm_detail or {}).get('request_payload', {}),
                            response_api_raw=(llm_detail or {}).get('api_raw'),
                            response_parsed=(llm_detail or {}).get('raw'),
                            probability_level=(llm_detail or {}).get('raw', {}).get('probability_level') or probability_level,
                            confidence=(llm_detail or {}).get('raw', {}).get('confidence'),
                            rationale=(llm_detail or {}).get('raw', {}).get('rationale') or '',
                            analysis_text=(llm_detail or {}).get('raw', {}).get('analysis_text') or '',
                            prevention_tips=(llm_detail or {}).get('raw', {}).get('prevention_tips') or [],
                        )
                except Exception:
                    logger.exception('Failed to store LLMResponse')
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
        
        return {key: round(value, 2) for key, value in scores.items()}
    
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
