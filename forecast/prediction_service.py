import logging
from datetime import timedelta
import numpy as np
from django.utils import timezone

from .models import WeatherForecast, MigrainePrediction, UserHealthProfile, LLMResponse
from .llm_client import LLMClient
from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, set_tag

logger = logging.getLogger(__name__)


class MigrainePredictionService:
    """
    Service for predicting migraine probability based on weather forecast data.
    """

    # Weather parameters thresholds associated with migraine triggers
    # These thresholds are based on research about weather-related migraine triggers
    THRESHOLDS = {
        "temperature_change": 5.0,  # Celsius - significant temperature change
        "humidity_high": 70.0,  # Percentage - high humidity
        "humidity_low": 30.0,  # Percentage - low humidity
        "pressure_change": 5.0,  # hPa - significant pressure change
        "pressure_low": 1005.0,  # hPa - low pressure system
        "precipitation_high": 5.0,  # mm - heavy precipitation
        "cloud_cover_high": 80.0,  # Percentage - heavy cloud cover
    }

    # Weights for different weather parameters in prediction
    WEIGHTS = {
        "temperature_change": 0.25,
        "humidity_extreme": 0.15,
        "pressure_change": 0.30,
        "pressure_low": 0.15,
        "precipitation": 0.05,
        "cloud_cover": 0.10,
    }

    def __init__(self):
        """Initialize the migraine prediction service."""
        pass

    def predict_migraine_probability(
        self, location, user=None, store_prediction=True, window_start_hours=None, window_end_hours=None
    ):  # noqa: E501
        """
        Predict migraine probability for a specific location and user.

        Args:
            location (Location): The location model instance
            user (User, optional): The user model instance
            store_prediction (bool): Whether to store the prediction in the database
            window_start_hours (int, optional): Start of prediction window in hours ahead (default: 3)
            window_end_hours (int, optional): End of prediction window in hours ahead (default: 6)

        Returns:
            tuple: (probability_level, prediction_instance)
        """
        # Get user preferences for time window if not specified
        if window_start_hours is None or window_end_hours is None:
            try:
                if user and hasattr(user, "health_profile"):
                    profile = user.health_profile
                    window_start_hours = window_start_hours or profile.prediction_window_start_hours
                    window_end_hours = window_end_hours or profile.prediction_window_end_hours
                else:
                    window_start_hours = window_start_hours or 3
                    window_end_hours = window_end_hours or 6
            except Exception:
                window_start_hours = window_start_hours or 3
                window_end_hours = window_end_hours or 6

        # Get recent forecasts for the user's preferred time window
        start_time = timezone.now() + timedelta(hours=window_start_hours)
        end_time = timezone.now() + timedelta(hours=window_end_hours)

        forecasts = WeatherForecast.objects.filter(
            location=location, target_time__gte=start_time, target_time__lte=end_time
        ).order_by("target_time")

        if not forecasts:
            logger.warning(
                f"No forecasts available for location {location} in the {window_start_hours}-{window_end_hours} hour window"  # noqa: E501
            )  # noqa: E501
            return None, None

        # Get previous forecasts for comparison
        previous_forecasts = WeatherForecast.objects.filter(location=location, target_time__lt=start_time).order_by(
            "-target_time"
        )[
            :6
        ]  # Last 6 hours

        # Calculate scores for different weather factors
        scores = self._calculate_weather_scores(forecasts, previous_forecasts)

        # Optionally adjust scores/weights based on user health profile
        adjusted_weights = dict(self.WEIGHTS)
        applied_profile = None
        if user is not None:
            try:
                profile = user.health_profile
                applied_profile = {
                    "sensitivity_overall": profile.sensitivity_overall,
                    "sensitivity_temperature": profile.sensitivity_temperature,
                    "sensitivity_humidity": profile.sensitivity_humidity,
                    "sensitivity_pressure": profile.sensitivity_pressure,
                    "sensitivity_cloud_cover": profile.sensitivity_cloud_cover,
                    "sensitivity_precipitation": profile.sensitivity_precipitation,
                    "language": profile.language,  # Pass user's language preference to LLM
                }
                # Map weight keys to profile keys and adjust weights
                factor_to_profile = {
                    "temperature_change": "sensitivity_temperature",
                    "humidity_extreme": "sensitivity_humidity",
                    "pressure_change": "sensitivity_pressure",
                    "pressure_low": "sensitivity_pressure",
                    "precipitation": "sensitivity_precipitation",
                    "cloud_cover": "sensitivity_cloud_cover",
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
            factors_payload["applied_profile"] = applied_profile
            factors_payload["weights"] = adjusted_weights

        # Try LLM prediction first as the main prediction engine
        llm_used = False
        llm_detail = None
        probability_level = None
        total_score = None  # Will store the actual score used for classification

        # Get LLM configuration from database (with fallback to settings)
        from forecast.models import LLMConfiguration

        llm_config = LLMConfiguration.get_config()

        if llm_config.is_active:
            # Add breadcrumb for LLM prediction attempt
            add_breadcrumb(
                category="prediction",
                message="Attempting LLM prediction",
                level="info",
                data={
                    "location": f"{location.city}, {location.country}",
                    "model": llm_config.model,
                    "user_id": user.id if user else None,
                },
            )

            set_tag("llm_model", llm_config.model)
            set_tag("prediction_type", "migraine")

            try:
                client = LLMClient(
                    base_url=llm_config.base_url,
                    api_key=llm_config.api_key,
                    model=llm_config.model,
                    timeout=llm_config.timeout,
                )
                loc_label = f"{location.city}, {location.country}"
                # Build minimal context with only essential aggregates and changes
                try:
                    fc_list = list(forecasts)
                    prev_list = list(previous_forecasts)

                    # Calculate temperature statistics for the prediction window
                    temps = [f.temperature for f in fc_list] if fc_list else []
                    pressures = [f.pressure for f in fc_list] if fc_list else []
                    humidities = [f.humidity for f in fc_list] if fc_list else []
                    cloud_covers = [f.cloud_cover for f in fc_list] if fc_list else []
                    precipitations = [f.precipitation for f in fc_list] if fc_list else []

                    # Only send aggregates and changes, not raw samples (reduces token count significantly)
                    context_payload = {
                        "aggregates": {
                            # Temperature
                            "avg_forecast_temperature": (round(float(np.mean(temps)), 1) if temps else None),
                            "min_forecast_temperature": (round(float(min(temps)), 1) if temps else None),
                            "max_forecast_temperature": (round(float(max(temps)), 1) if temps else None),
                            "temperature_range": (round(float(max(temps) - min(temps)), 1) if temps else None),
                            # Humidity
                            "avg_forecast_humidity": (round(float(np.mean(humidities)), 0) if humidities else None),
                            "min_forecast_humidity": (round(float(min(humidities)), 0) if humidities else None),
                            "max_forecast_humidity": (round(float(max(humidities)), 0) if humidities else None),
                            "humidity_range": (
                                round(float(max(humidities) - min(humidities)), 0) if humidities else None
                            ),
                            # Pressure
                            "avg_forecast_pressure": (round(float(np.mean(pressures)), 1) if pressures else None),
                            "min_forecast_pressure": (round(float(min(pressures)), 1) if pressures else None),
                            "max_forecast_pressure": (round(float(max(pressures)), 1) if pressures else None),
                            "pressure_range": (round(float(max(pressures) - min(pressures)), 1) if pressures else None),
                            # Cloud cover
                            "avg_forecast_cloud_cover": (
                                round(float(np.mean(cloud_covers)), 0) if cloud_covers else None
                            ),
                            "min_forecast_cloud_cover": (round(float(min(cloud_covers)), 0) if cloud_covers else None),
                            "max_forecast_cloud_cover": (round(float(max(cloud_covers)), 0) if cloud_covers else None),
                            "cloud_cover_range": (
                                round(float(max(cloud_covers) - min(cloud_covers)), 0) if cloud_covers else None
                            ),
                            # Precipitation
                            "max_precipitation": (round(float(max(precipitations)), 1) if precipitations else 0),
                            "total_precipitation": (round(float(sum(precipitations)), 1) if precipitations else 0),
                        },
                        "changes": {
                            "temperature_change": round(
                                float(
                                    (np.mean([f.temperature for f in fc_list]) if fc_list else 0)
                                    - (np.mean([f.temperature for f in prev_list]) if prev_list else 0)
                                ),
                                1,
                            ),
                            "pressure_change": round(
                                float(
                                    (np.mean([f.pressure for f in fc_list]) if fc_list else 0)
                                    - (np.mean([f.pressure for f in prev_list]) if prev_list else 0)
                                ),
                                1,
                            ),
                            "humidity_change": round(
                                float(
                                    (np.mean([f.humidity for f in fc_list]) if fc_list else 0)
                                    - (np.mean([f.humidity for f in prev_list]) if prev_list else 0)
                                ),
                                1,
                            ),
                        },
                    }

                    # For large windows (>6 hours), add intraday variation metrics
                    # This helps LLM understand temperature swings throughout the day
                    if len(fc_list) > 6:
                        # Calculate max temperature change between consecutive hours
                        temp_deltas = [
                            abs(fc_list[i + 1].temperature - fc_list[i].temperature) for i in range(len(fc_list) - 1)
                        ]
                        max_hourly_temp_change = max(temp_deltas) if temp_deltas else 0

                        # Calculate max pressure change between consecutive hours
                        pressure_deltas = [
                            abs(fc_list[i + 1].pressure - fc_list[i].pressure) for i in range(len(fc_list) - 1)
                        ]
                        max_hourly_pressure_change = max(pressure_deltas) if pressure_deltas else 0

                        context_payload["intraday_variation"] = {
                            "max_hourly_temp_change": round(float(max_hourly_temp_change), 1),
                            "max_hourly_pressure_change": round(float(max_hourly_pressure_change), 1),
                            "window_hours": len(fc_list),
                        }

                    # Add comprehensive temporal context
                    now = timezone.now()
                    hours_ahead = round((end_time - start_time).total_seconds() / 3600, 1)

                    # Current time information
                    current_hour = now.hour
                    if 5 <= current_hour < 12:
                        current_period = "morning"
                    elif 12 <= current_hour < 17:
                        current_period = "afternoon"
                    elif 17 <= current_hour < 21:
                        current_period = "evening"
                    else:
                        current_period = "night"

                    # Prediction window start time information
                    start_hour = start_time.hour
                    if 5 <= start_hour < 12:
                        window_start_period = "morning"
                    elif 12 <= start_hour < 17:
                        window_start_period = "afternoon"
                    elif 17 <= start_hour < 21:
                        window_start_period = "evening"
                    else:
                        window_start_period = "night"

                    # Day of week (0=Monday, 6=Sunday)
                    day_of_week = now.weekday()
                    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                    is_weekend = day_of_week >= 5

                    # Season (Northern Hemisphere)
                    month = now.month
                    if month in [12, 1, 2]:
                        season = "winter"
                    elif month in [3, 4, 5]:
                        season = "spring"
                    elif month in [6, 7, 8]:
                        season = "summer"
                    else:
                        season = "fall"

                    context_payload["temporal_context"] = {
                        # Current time when prediction is being made
                        "current_time": now.strftime("%Y-%m-%d %H:%M"),
                        "current_hour": current_hour,
                        "current_period": current_period,
                        "day_of_week": day_names[day_of_week],
                        "is_weekend": is_weekend,
                        "season": season,
                        # Prediction window information
                        "window_start_time": start_time.strftime("%Y-%m-%d %H:%M"),
                        "window_end_time": end_time.strftime("%Y-%m-%d %H:%M"),
                        "window_start_period": window_start_period,
                        "window_duration_hours": hours_ahead,
                    }

                    # Add summarized previous predictions (last 24h only)
                    if user:
                        recent_predictions = MigrainePrediction.objects.filter(
                            user=user, location=location, prediction_time__gte=start_time - timedelta(hours=24)
                        ).values_list("probability", flat=True)

                        if recent_predictions:
                            pred_list = list(recent_predictions)
                            context_payload["previous_predictions"] = {
                                "count": len(pred_list),
                                "high_count": pred_list.count("HIGH"),
                                "medium_count": pred_list.count("MEDIUM"),
                                "low_count": pred_list.count("LOW"),
                            }

                    # Add summarized previous weather forecasts (last 12-24h)
                    # This helps LLM understand recent weather trends
                    if prev_list:
                        # Get weather from 12-24h ago for trend analysis
                        older_forecasts = WeatherForecast.objects.filter(
                            location=location,
                            target_time__gte=start_time - timedelta(hours=24),
                            target_time__lt=start_time - timedelta(hours=12),
                        ).order_by("target_time")

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
                                context_payload["weather_trend"] = {
                                    "temp_trend": round(float(temp_trend), 1),
                                    "pressure_trend": round(float(pressure_trend), 1),
                                }

                except Exception:
                    logger.exception("Failed building LLM context payload")
                    context_payload = {}

                # Get recent predictions for context (with full objects, not just values)
                recent_predictions = None
                if user:
                    recent_predictions = list(MigrainePrediction.objects.filter(
                        user=user,
                        location=location,
                        prediction_time__gte=start_time - timedelta(hours=24)
                    ).order_by("-prediction_time")[:5])

                llm_level, llm_detail = client.predict_probability(
                    scores=factors_payload,
                    location_label=loc_label,
                    user_profile=applied_profile,
                    context=context_payload,
                    forecasts=list(forecasts),
                    previous_forecasts=list(previous_forecasts),
                    location=location,
                    previous_predictions=recent_predictions,
                    high_token_budget=llm_config.high_token_budget,
                )
                if llm_level in {"LOW", "MEDIUM", "HIGH"}:
                    llm_used = True
                    probability_level = llm_level
                    logger.info(f"LLM prediction successful: {probability_level}")

                    add_breadcrumb(
                        category="prediction",
                        message="LLM prediction successful",
                        level="info",
                        data={"probability_level": probability_level},
                    )
                else:
                    logger.warning("LLM returned invalid probability level, will fall back to manual calculation")

                    set_context(
                        "llm_invalid_response",
                        {"location": loc_label, "llm_level": llm_level, "llm_detail": llm_detail},
                    )
                    capture_message(f"LLM returned invalid probability level: {llm_level}", level="warning")

            except Exception as e:
                logger.exception("LLM prediction failed; falling back to manual calculation")

                set_context(
                    "llm_prediction_failure",
                    {
                        "location": loc_label,
                        "model": llm_config.model,
                        "user_id": user.id if user else None,
                        "error_type": type(e).__name__,
                    },
                )
                capture_exception(e)

        # Fallback to manual calculation if LLM is disabled or failed
        if probability_level is None:
            logger.info("Using manual calculation for prediction")
            # Calculate overall probability score (0-1)
            total_score = sum(scores[factor] * adjusted_weights.get(factor, 0.0) for factor in scores)

            # Determine probability level (shift thresholds slightly by overall sensitivity)
            high_thr = 0.7
            med_thr = 0.4
            if user is not None and applied_profile is not None:
                overall = applied_profile.get("sensitivity_overall", 1.0)
                # More sensitive → lower thresholds; less sensitive → higher thresholds (clamped)
                shift = (overall - 1.0) * 0.15  # max +/- 15% threshold shift per overall unit
                high_thr = min(max(high_thr - shift, 0.5), 0.9)
                med_thr = min(max(med_thr - shift, 0.25), 0.7)

            if total_score >= high_thr:
                probability_level = "HIGH"
            elif total_score >= med_thr:
                probability_level = "MEDIUM"
            else:
                probability_level = "LOW"

        # Store the total score used for classification (if calculated manually)
        if total_score is not None:
            factors_payload["total_score"] = round(total_score, 2)

        # Add LLM details to factors payload if available
        if llm_detail is not None:
            factors_payload["llm"] = {
                "used": llm_used,
                "detail": llm_detail,
            }
            try:
                parsed = (llm_detail or {}).get("raw") or {}
                factors_payload["llm_analysis_text"] = parsed.get("analysis_text")
                factors_payload["llm_prevention_tips"] = parsed.get("prevention_tips")
            except Exception:
                logger.exception("Failed to extract LLM analysis/tips")

        prediction = MigrainePrediction(
            user=user,
            location=location,
            forecast=forecasts.first(),
            target_time_start=start_time,
            target_time_end=end_time,
            probability=probability_level,
            weather_factors=factors_payload,
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
                            prediction_type="migraine",
                            migraine_prediction=prediction,
                            request_payload=(llm_detail or {}).get("request_payload", {}),
                            response_api_raw=(llm_detail or {}).get("api_raw"),
                            response_parsed=(llm_detail or {}).get("raw"),
                            probability_level=(llm_detail or {}).get("raw", {}).get("probability_level")
                            or probability_level,
                            confidence=(llm_detail or {}).get("raw", {}).get("confidence"),
                            rationale=(llm_detail or {}).get("raw", {}).get("rationale") or "",
                            analysis_text=(llm_detail or {}).get("raw", {}).get("analysis_text") or "",
                            prevention_tips=(llm_detail or {}).get("raw", {}).get("prevention_tips") or [],
                        )
                except Exception:
                    logger.exception("Failed to store LLMResponse")
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
            "temperature_change": 0.0,
            "humidity_extreme": 0.0,
            "pressure_change": 0.0,
            "pressure_low": 0.0,
            "precipitation": 0.0,
            "cloud_cover": 0.0,
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
            scores["temperature_change"] = min(temp_change / self.THRESHOLDS["temperature_change"], 1.0)

        # Calculate humidity extremes
        avg_humidity = np.mean([f.humidity for f in forecasts])
        if avg_humidity >= self.THRESHOLDS["humidity_high"]:
            # High humidity score
            scores["humidity_extreme"] = (avg_humidity - self.THRESHOLDS["humidity_high"]) / (
                100 - self.THRESHOLDS["humidity_high"]
            )
        elif avg_humidity <= self.THRESHOLDS["humidity_low"]:
            # Low humidity score
            scores["humidity_extreme"] = (self.THRESHOLDS["humidity_low"] - avg_humidity) / self.THRESHOLDS[
                "humidity_low"
            ]

        # Calculate pressure change
        if previous_forecasts:
            avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
            avg_forecast_pressure = np.mean([f.pressure for f in forecasts])
            pressure_change = abs(avg_forecast_pressure - avg_prev_pressure)

            # Score based on pressure change threshold
            scores["pressure_change"] = min(pressure_change / self.THRESHOLDS["pressure_change"], 1.0)

        # Calculate low pressure score
        avg_pressure = np.mean([f.pressure for f in forecasts])
        if avg_pressure <= self.THRESHOLDS["pressure_low"]:
            # Low pressure score
            scores["pressure_low"] = (self.THRESHOLDS["pressure_low"] - avg_pressure) / 20.0  # Normalize to 0-1

        # Calculate precipitation score
        max_precipitation = max([f.precipitation for f in forecasts], default=0)
        scores["precipitation"] = min(max_precipitation / self.THRESHOLDS["precipitation_high"], 1.0)

        # Calculate cloud cover score
        avg_cloud_cover = np.mean([f.cloud_cover for f in forecasts])
        scores["cloud_cover"] = min(avg_cloud_cover / self.THRESHOLDS["cloud_cover_high"], 1.0)

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
        return MigrainePrediction.objects.filter(user=user).order_by("-prediction_time")[:limit]
