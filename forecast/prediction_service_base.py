import logging
from abc import ABC, abstractmethod
from datetime import timedelta

import numpy as np
from django.utils import timezone

from .models import WeatherForecast, UserHealthProfile, LLMResponse
from .llm_client import LLMClient
from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, set_tag

logger = logging.getLogger(__name__)


class LLMInvalidResponseError(Exception):
    """Raised when LLM returns an invalid or malformed response."""
    pass


class BasePredictionService(ABC):
    """
    Abstract base class for weather-based health prediction services.

    Subclasses must define class-level constants and implement abstract methods.
    """

    # --- Subclasses MUST override these ---
    THRESHOLDS = {}
    WEIGHTS = {}
    PREDICTION_TYPE = ""          # e.g. "migraine" or "sinusitis"
    PREDICTION_MODEL = None       # Django model class
    MANUAL_HIGH_THRESHOLD = 0.7
    MANUAL_MEDIUM_THRESHOLD = 0.4
    SENSITIVITY_HIGH_THRESHOLDS = (0.6, 0.3)
    SENSITIVITY_LOW_THRESHOLDS = (0.8, 0.5)

    def __init__(self):
        pass

    @abstractmethod
    def _call_llm_predict(self, client, **kwargs):
        """Call the appropriate LLM client method. Returns (level, detail)."""
        pass

    @abstractmethod
    def _get_prediction_fk_field(self):
        """Return the FK field name on LLMResponse, e.g. 'migraine_prediction'."""
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(self, location, user=None, store_prediction=True,
                window_start_hours=None, window_end_hours=None):
        """
        Predict probability for a specific location and user.

        Returns:
            tuple: (probability_level, prediction_instance)
        """
        window_start_hours, window_end_hours = self._resolve_time_window(
            user, window_start_hours, window_end_hours
        )

        start_time = timezone.now() + timedelta(hours=window_start_hours)
        end_time = timezone.now() + timedelta(hours=window_end_hours)

        forecasts = WeatherForecast.objects.filter(
            location=location, target_time__gte=start_time, target_time__lte=end_time
        ).order_by("target_time")

        if not forecasts:
            logger.warning(
                f"No forecasts available for location {location} "
                f"in the {window_start_hours}-{window_end_hours} hour window"
            )
            capture_message(
                f"No forecasts available for location {location.city}, {location.country}",
                level="warning",
            )
            return None, None

        previous_forecasts = WeatherForecast.objects.filter(
            location=location,
            target_time__gte=start_time - timedelta(hours=24),
            target_time__lt=start_time
        ).order_by("-target_time")

        outlook_forecasts = WeatherForecast.objects.filter(
            location=location,
            target_time__gte=timezone.now(),
            target_time__lte=timezone.now() + timedelta(hours=24)
        ).order_by("target_time")

        scores = self._calculate_weather_scores(forecasts, previous_forecasts)

        adjusted_weights = dict(self.WEIGHTS)
        applied_profile = self._load_user_profile(user)

        factors_payload = dict(scores)
        if applied_profile is not None:
            factors_payload["applied_profile"] = applied_profile
            factors_payload["weights"] = adjusted_weights

        # Try LLM prediction
        probability_level, llm_used, llm_detail, original_probability_level, confidence_adjusted = (
            self._try_llm_prediction(
                location, user, forecasts, previous_forecasts, outlook_forecasts,
                factors_payload, applied_profile, start_time, end_time
            )
        )
        total_score = None

        # Fallback to manual calculation
        if probability_level is None:
            logger.info(f"Using manual calculation for {self.PREDICTION_TYPE} prediction")
            total_score = sum(scores[f] * adjusted_weights.get(f, 0.0) for f in scores)
            probability_level = self._classify_score(total_score, applied_profile)

        if total_score is not None:
            factors_payload["total_score"] = round(total_score, 2)

        if llm_detail is not None:
            factors_payload["llm"] = {"used": llm_used, "detail": llm_detail}
            try:
                parsed = (llm_detail or {}).get("raw") or {}
                factors_payload["llm_analysis_text"] = parsed.get("analysis_text")
                factors_payload["llm_prevention_tips"] = parsed.get("prevention_tips")
            except Exception:
                logger.exception("Failed to extract LLM analysis/tips")

        prediction = self._create_and_store_prediction(
            user, location, forecasts, start_time, end_time,
            probability_level, factors_payload, store_prediction,
            llm_used, llm_detail, original_probability_level, confidence_adjusted,
        )

        return probability_level, prediction

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve_time_window(self, user, start, end):
        if start is None or end is None:
            try:
                if user and hasattr(user, "health_profile"):
                    profile = user.health_profile
                    start = start or profile.prediction_window_start_hours
                    end = end or profile.prediction_window_end_hours
                else:
                    start = start or 3
                    end = end or 6
            except Exception:
                start = start or 3
                end = end or 6
        return start, end

    def _load_user_profile(self, user):
        if user is None:
            return None
        try:
            profile = user.health_profile
            return {
                "sensitivity_preset": profile.sensitivity_preset,
                "language": profile.language,
            }
        except UserHealthProfile.DoesNotExist:
            return None
        except Exception:
            logger.exception("Failed to load user health profile, proceeding with defaults")
            return None

    def _classify_score(self, total_score, applied_profile):
        high_thr = self.MANUAL_HIGH_THRESHOLD
        med_thr = self.MANUAL_MEDIUM_THRESHOLD
        if applied_profile is not None:
            preset = applied_profile.get("sensitivity_preset", "NORMAL")
            if preset == "HIGH":
                high_thr, med_thr = self.SENSITIVITY_HIGH_THRESHOLDS
            elif preset == "LOW":
                high_thr, med_thr = self.SENSITIVITY_LOW_THRESHOLDS
        if total_score >= high_thr:
            return "HIGH"
        elif total_score >= med_thr:
            return "MEDIUM"
        return "LOW"

    def _create_and_store_prediction(
        self, user, location, forecasts, start_time, end_time,
        probability_level, factors_payload, store_prediction,
        llm_used, llm_detail, original_probability_level, confidence_adjusted,
    ):
        prediction = self.PREDICTION_MODEL(
            user=user,
            location=location,
            forecast=forecasts.first(),
            target_time_start=start_time,
            target_time_end=end_time,
            probability=probability_level,
            weather_factors=factors_payload,
        )

        if not user:
            return None

        if store_prediction:
            prediction.save()
            self._store_llm_response(
                user, location, prediction, llm_detail,
                probability_level, original_probability_level, confidence_adjusted,
            )
            set_context(
                f"{self.PREDICTION_TYPE}_prediction",
                {
                    "location": f"{location.city}, {location.country}",
                    "user_id": user.id,
                    "probability_level": probability_level,
                    "original_probability_level": original_probability_level,
                    "confidence_adjusted": confidence_adjusted,
                    "llm_used": llm_used,
                    "window_start": str(start_time),
                    "window_end": str(end_time),
                },
            )
            capture_message(
                f"{self.PREDICTION_TYPE.capitalize()} prediction generated: "
                f"{probability_level} for {location.city}, {location.country}",
                level="info",
            )

        return prediction

    def _store_llm_response(self, user, location, prediction, llm_detail,
                            probability_level, original_probability_level, confidence_adjusted):
        if llm_detail is None:
            return
        try:
            fk_kwargs = {self._get_prediction_fk_field(): prediction}
            LLMResponse.objects.create(
                user=user,
                location=location,
                prediction_type=self.PREDICTION_TYPE,
                request_payload=(llm_detail or {}).get("request_payload", {}),
                response_api_raw=(llm_detail or {}).get("api_raw"),
                response_parsed=(llm_detail or {}).get("raw"),
                probability_level=probability_level,
                original_probability_level=original_probability_level or "",
                confidence=(llm_detail or {}).get("raw", {}).get("confidence"),
                confidence_adjusted=confidence_adjusted,
                rationale=(llm_detail or {}).get("raw", {}).get("rationale") or "",
                analysis_text=(llm_detail or {}).get("raw", {}).get("analysis_text") or "",
                prevention_tips=(llm_detail or {}).get("raw", {}).get("prevention_tips") or [],
                inference_time=(llm_detail or {}).get("inference_time"),
                **fk_kwargs,
            )
        except Exception:
            logger.exception(f"Failed to store LLMResponse for {self.PREDICTION_TYPE} prediction")

    def _try_llm_prediction(self, location, user, forecasts, previous_forecasts,
                            outlook_forecasts, factors_payload, applied_profile,
                            start_time, end_time):
        """Attempt LLM-based prediction. Returns 5-tuple."""
        from forecast.models import LLMConfiguration

        llm_config = LLMConfiguration.get_config()
        probability_level = None
        llm_used = False
        llm_detail = None
        original_probability_level = None
        confidence_adjusted = False

        if not llm_config.is_active:
            return probability_level, llm_used, llm_detail, original_probability_level, confidence_adjusted

        add_breadcrumb(
            category="prediction",
            message=f"Attempting LLM {self.PREDICTION_TYPE} prediction",
            level="info",
            data={
                "location": f"{location.city}, {location.country}",
                "model": llm_config.model,
                "user_id": user.id if user else None,
            },
        )
        set_tag("llm_model", llm_config.model)
        set_tag("prediction_type", self.PREDICTION_TYPE)

        try:
            client = LLMClient(
                base_url=llm_config.base_url,
                api_key=llm_config.api_key,
                model=llm_config.model,
                timeout=llm_config.timeout,
                extra_payload=llm_config.extra_payload,
            )
            loc_label = f"{location.city}, {location.country}"

            context_payload = self._build_context_payload(
                location, user, forecasts, previous_forecasts,
                start_time, end_time,
            )

            llm_level, llm_detail = self._call_llm_predict(
                client,
                scores=factors_payload,
                location_label=loc_label,
                user_profile=applied_profile,
                context=context_payload,
                forecasts=list(forecasts),
                previous_forecasts=list(previous_forecasts),
                location=location,
                high_token_budget=llm_config.high_token_budget,
                outlook_forecasts=list(outlook_forecasts),
            )

            if llm_level in {"LOW", "MEDIUM", "HIGH"}:
                llm_used = True
                original_probability_level = llm_level
                probability_level, confidence_adjusted = self._apply_confidence_threshold(
                    llm_level, llm_detail, llm_config.confidence_threshold
                )
                add_breadcrumb(
                    category="prediction",
                    message="LLM prediction successful",
                    level="info",
                    data={
                        "probability_level": probability_level,
                        "original_probability_level": original_probability_level,
                        "confidence": (llm_detail or {}).get("raw", {}).get("confidence"),
                        "confidence_adjusted": confidence_adjusted,
                    },
                )
            else:
                error_msg = f"LLM returned invalid probability level for {self.PREDICTION_TYPE}: {llm_level}"
                logger.warning(error_msg)
                set_context(
                    "llm_invalid_response",
                    {"location": loc_label, "llm_level": llm_level, "llm_detail": llm_detail},
                )
                capture_message(error_msg, level="warning")
                raise LLMInvalidResponseError(error_msg)

        except LLMInvalidResponseError:
            raise
        except Exception as e:
            logger.exception(f"LLM {self.PREDICTION_TYPE} prediction failed; falling back to manual calculation")
            set_context(
                "llm_prediction_failure",
                {
                    "location": f"{location.city}, {location.country}",
                    "model": llm_config.model,
                    "user_id": user.id if user else None,
                    "error_type": type(e).__name__,
                },
            )
            capture_exception(e)

        return probability_level, llm_used, llm_detail, original_probability_level, confidence_adjusted

    def _apply_confidence_threshold(self, llm_level, llm_detail, confidence_threshold):
        """Apply confidence threshold, potentially downgrading the level."""
        llm_confidence = (llm_detail or {}).get("raw", {}).get("confidence")

        if llm_confidence is not None and llm_confidence < confidence_threshold:
            downgrade_map = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}
            downgraded = downgrade_map[llm_level]
            if downgraded != llm_level:
                logger.info(
                    f"LLM {self.PREDICTION_TYPE} prediction downgraded: {llm_level} -> {downgraded} "
                    f"(confidence: {llm_confidence:.2f}, threshold: {confidence_threshold:.2f})"
                )
                return downgraded, True
            else:
                logger.info(
                    f"LLM {self.PREDICTION_TYPE} prediction successful: {llm_level} "
                    f"(confidence: {llm_confidence:.2f})"
                )
                return llm_level, False
        else:
            confidence_str = f"{llm_confidence:.2f}" if llm_confidence is not None else "N/A"
            logger.info(
                f"LLM {self.PREDICTION_TYPE} prediction successful: {llm_level} "
                f"(confidence: {confidence_str})"
            )
            return llm_level, False

    def _build_context_payload(self, location, user, forecasts, previous_forecasts,
                               start_time, end_time):
        """Build the context payload sent to the LLM."""
        try:
            fc_list = list(forecasts)
            prev_list = list(previous_forecasts)

            temps = [f.temperature for f in fc_list] if fc_list else []
            pressures = [f.pressure for f in fc_list] if fc_list else []
            humidities = [f.humidity for f in fc_list] if fc_list else []
            cloud_covers = [f.cloud_cover for f in fc_list] if fc_list else []
            precipitations = [f.precipitation for f in fc_list] if fc_list else []

            context_payload = {}

            # Aggregates
            if temps:
                context_payload["aggregates"] = {
                    "avg_forecast_temperature": round(float(np.mean(temps)), 1),
                    "min_forecast_temperature": round(float(min(temps)), 1),
                    "max_forecast_temperature": round(float(max(temps)), 1),
                    "temperature_range": round(float(max(temps) - min(temps)), 1),
                    "avg_forecast_humidity": round(float(np.mean(humidities)), 0) if humidities else None,
                    "min_forecast_humidity": round(float(min(humidities)), 0) if humidities else None,
                    "max_forecast_humidity": round(float(max(humidities)), 0) if humidities else None,
                    "humidity_range": round(float(max(humidities) - min(humidities)), 0) if humidities else None,
                    "avg_forecast_pressure": round(float(np.mean(pressures)), 1) if pressures else None,
                    "min_forecast_pressure": round(float(min(pressures)), 1) if pressures else None,
                    "max_forecast_pressure": round(float(max(pressures)), 1) if pressures else None,
                    "pressure_range": round(float(max(pressures) - min(pressures)), 1) if pressures else None,
                    "avg_forecast_cloud_cover": round(float(np.mean(cloud_covers)), 0) if cloud_covers else None,
                    "min_forecast_cloud_cover": round(float(min(cloud_covers)), 0) if cloud_covers else None,
                    "max_forecast_cloud_cover": round(float(max(cloud_covers)), 0) if cloud_covers else None,
                    "cloud_cover_range": (
                        round(float(max(cloud_covers) - min(cloud_covers)), 0) if cloud_covers else None
                    ),
                    "max_precipitation": round(float(max(precipitations)), 1) if precipitations else 0,
                    "total_precipitation": round(float(sum(precipitations)), 1) if precipitations else 0,
                }

            # Changes vs previous period
            if fc_list and prev_list:
                context_payload["changes"] = {
                    "temperature_change": round(
                        float(np.mean(temps) - np.mean([f.temperature for f in prev_list])), 1
                    ),
                    "pressure_change": round(
                        float(np.mean(pressures) - np.mean([f.pressure for f in prev_list])), 1
                    ),
                    "humidity_change": round(
                        float(np.mean(humidities) - np.mean([f.humidity for f in prev_list])), 1
                    ),
                }

            # Intraday variation for large windows
            if len(fc_list) > 6:
                temp_deltas = [
                    abs(fc_list[i + 1].temperature - fc_list[i].temperature)
                    for i in range(len(fc_list) - 1)
                ]
                pressure_deltas = [
                    abs(fc_list[i + 1].pressure - fc_list[i].pressure)
                    for i in range(len(fc_list) - 1)
                ]
                context_payload["intraday_variation"] = {
                    "max_hourly_temp_change": round(float(max(temp_deltas)), 1) if temp_deltas else 0,
                    "max_hourly_pressure_change": round(float(max(pressure_deltas)), 1) if pressure_deltas else 0,
                    "window_hours": len(fc_list),
                }

            # Temporal context
            context_payload["temporal_context"] = self._build_temporal_context(
                location, start_time, end_time
            )

            # Previous predictions summary
            if user:
                recent_preds = self.PREDICTION_MODEL.objects.filter(
                    user=user, location=location,
                    prediction_time__gte=start_time - timedelta(hours=24)
                ).values_list("probability", flat=True)
                if recent_preds:
                    pred_list = list(recent_preds)
                    context_payload["previous_predictions"] = {
                        "count": len(pred_list),
                        "high_count": pred_list.count("HIGH"),
                        "medium_count": pred_list.count("MEDIUM"),
                        "low_count": pred_list.count("LOW"),
                    }

            # Weather trend (12-24h ago vs 0-12h ago)
            if prev_list:
                older_forecasts = WeatherForecast.objects.filter(
                    location=location,
                    target_time__gte=start_time - timedelta(hours=24),
                    target_time__lt=start_time - timedelta(hours=12),
                ).order_by("target_time")

                if older_forecasts.exists():
                    older_list = list(older_forecasts)
                    prev_avg_temp = np.mean([f.temperature for f in prev_list])
                    older_avg_temp = np.mean([f.temperature for f in older_list])
                    prev_avg_pressure = np.mean([f.pressure for f in prev_list])
                    older_avg_pressure = np.mean([f.pressure for f in older_list])

                    temp_trend = float(prev_avg_temp - older_avg_temp)
                    pressure_trend = float(prev_avg_pressure - older_avg_pressure)

                    if abs(temp_trend) > 2 or abs(pressure_trend) > 3:
                        context_payload["weather_trend"] = {
                            "temp_trend": round(temp_trend, 1),
                            "pressure_trend": round(pressure_trend, 1),
                        }

            return context_payload
        except Exception:
            logger.exception("Failed building LLM context payload")
            return {}

    def _build_temporal_context(self, location, start_time, end_time):
        """Build temporal context dict for LLM."""
        now = timezone.now()
        hours_ahead = round((end_time - start_time).total_seconds() / 3600, 1)

        def _period(hour):
            if 5 <= hour < 12:
                return "morning"
            elif 12 <= hour < 17:
                return "afternoon"
            elif 17 <= hour < 21:
                return "evening"
            return "night"

        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_of_week = now.weekday()

        month = now.month
        is_southern = location.latitude < 0
        if month in [12, 1, 2]:
            season = "summer" if is_southern else "winter"
        elif month in [3, 4, 5]:
            season = "fall" if is_southern else "spring"
        elif month in [6, 7, 8]:
            season = "winter" if is_southern else "summer"
        else:
            season = "spring" if is_southern else "fall"

        return {
            "current_time": now.strftime("%Y-%m-%d %H:%M"),
            "current_hour": now.hour,
            "current_period": _period(now.hour),
            "day_of_week": day_names[day_of_week],
            "is_weekend": day_of_week >= 5,
            "season": season,
            "window_start_time": start_time.strftime("%Y-%m-%d %H:%M"),
            "window_end_time": end_time.strftime("%Y-%m-%d %H:%M"),
            "window_start_period": _period(start_time.hour),
            "window_duration_hours": hours_ahead,
        }

    def _calculate_weather_scores(self, forecasts, previous_forecasts):
        """
        Calculate normalised scores (0-1) for different weather factors.
        Uses self.THRESHOLDS so each subclass gets its own parameter set.
        """
        scores = {
            "temperature_change": 0.0,
            "humidity_extreme": 0.0,
            "pressure_change": 0.0,
            "pressure_low": 0.0,
            "precipitation": 0.0,
            "cloud_cover": 0.0,
        }

        if not forecasts or not previous_forecasts:
            return scores

        # Temperature change
        if previous_forecasts:
            avg_prev_temp = np.mean([f.temperature for f in previous_forecasts])
            avg_forecast_temp = np.mean([f.temperature for f in forecasts])
            temp_change = abs(avg_forecast_temp - avg_prev_temp)
            scores["temperature_change"] = min(temp_change / self.THRESHOLDS["temperature_change"], 1.0)

        # Humidity extremes
        avg_humidity = np.mean([f.humidity for f in forecasts])
        if avg_humidity >= self.THRESHOLDS["humidity_high"]:
            scores["humidity_extreme"] = (avg_humidity - self.THRESHOLDS["humidity_high"]) / (
                100 - self.THRESHOLDS["humidity_high"]
            )
        elif avg_humidity <= self.THRESHOLDS["humidity_low"]:
            scores["humidity_extreme"] = (
                self.THRESHOLDS["humidity_low"] - avg_humidity
            ) / self.THRESHOLDS["humidity_low"]

        # Pressure change
        if previous_forecasts:
            avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
            avg_forecast_pressure = np.mean([f.pressure for f in forecasts])
            pressure_change = abs(avg_forecast_pressure - avg_prev_pressure)
            scores["pressure_change"] = min(pressure_change / self.THRESHOLDS["pressure_change"], 1.0)

        # Low pressure
        avg_pressure = np.mean([f.pressure for f in forecasts])
        if avg_pressure <= self.THRESHOLDS["pressure_low"]:
            scores["pressure_low"] = (self.THRESHOLDS["pressure_low"] - avg_pressure) / 20.0

        # Precipitation
        max_precipitation = max([f.precipitation for f in forecasts], default=0)
        scores["precipitation"] = min(max_precipitation / self.THRESHOLDS["precipitation_high"], 1.0)

        # Cloud cover
        avg_cloud_cover = np.mean([f.cloud_cover for f in forecasts])
        scores["cloud_cover"] = min(avg_cloud_cover / self.THRESHOLDS["cloud_cover_high"], 1.0)

        return {key: round(value, 2) for key, value in scores.items()}

    def get_recent_predictions(self, user, limit=10):
        """Get recent predictions for a user."""
        return self.PREDICTION_MODEL.objects.filter(user=user).order_by("-prediction_time")[:limit]
