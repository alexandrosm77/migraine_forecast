"""Single deep module for weather-based health predictions.

Collapses the former BasePredictionService + per-condition subclasses into one
``PredictionService`` driven by a ``ConditionConfig`` registry (``CONDITIONS``).
The one genuinely varying axis — weather scoring — lives behind the narrow
``ScoringStrategy`` seam. See docs/adr/0001-collapse-prediction-services-into-one-deep-module.md
"""
import copy
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
from django.utils import timezone

from .models import (
    WeatherForecast, UserHealthProfile, LLMResponse, AirQualityForecast,
    MigrainePrediction, SinusitisPrediction, HayFeverPrediction,
)
from .llm_client import LLMClient
from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, set_tag

logger = logging.getLogger(__name__)


class LLMInvalidResponseError(Exception):
    """Raised when LLM returns an invalid or malformed response."""
    pass


def _fetch_air_quality(location, forecasts):
    """Fetch AirQualityForecast rows aligned with the given weather forecasts."""
    if not location or not forecasts:
        return AirQualityForecast.objects.none()
    fc_list = list(forecasts)
    if not fc_list:
        return AirQualityForecast.objects.none()
    first = fc_list[0]
    last = fc_list[-1]
    return AirQualityForecast.objects.filter(
        location=location,
        target_time__gte=first.target_time,
        target_time__lte=last.target_time,
    ).order_by("target_time")


# ======================================================================
# Scoring seam
# ======================================================================


@dataclass
class ScoreResult:
    """Output of a ScoringStrategy.

    ``weights`` is an *output* of scoring (not mutable instance state) so the
    hay-fever no-pollen weight swap needs no shadowing. ``factor_extras`` are
    merged into ``weather_factors``; ``confidence_factor`` scales the *recorded*
    LLM confidence (applied after level classification, never affecting it).
    """
    scores: dict
    weights: dict
    factor_extras: dict = field(default_factory=dict)
    confidence_factor: float = 1.0


class ScoringStrategy(ABC):
    """Computes normalised 0-1 weather scores and selects weights for one condition."""

    def __init__(self, thresholds, weights):
        self.thresholds = thresholds
        self.weights = weights

    @abstractmethod
    def score(self, forecasts, previous_forecasts) -> ScoreResult:
        """Return a ScoreResult for the given forecast window."""

    def _base_weather_scores(self, forecasts, previous_forecasts):
        """Calculate normalised scores (0-1) for the shared weather factors."""
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
            scores["temperature_change"] = min(temp_change / self.thresholds["temperature_change"], 1.0)

        # Humidity extremes
        avg_humidity = np.mean([f.humidity for f in forecasts])
        if avg_humidity >= self.thresholds["humidity_high"]:
            scores["humidity_extreme"] = (avg_humidity - self.thresholds["humidity_high"]) / (
                100 - self.thresholds["humidity_high"]
            )
        elif avg_humidity <= self.thresholds["humidity_low"]:
            scores["humidity_extreme"] = (
                self.thresholds["humidity_low"] - avg_humidity
            ) / self.thresholds["humidity_low"]

        # Pressure change
        if previous_forecasts:
            avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
            avg_forecast_pressure = np.mean([f.pressure for f in forecasts])
            pressure_change = abs(avg_forecast_pressure - avg_prev_pressure)
            scores["pressure_change"] = min(pressure_change / self.thresholds["pressure_change"], 1.0)

        # Low pressure
        avg_pressure = np.mean([f.pressure for f in forecasts])
        if avg_pressure <= self.thresholds["pressure_low"]:
            scores["pressure_low"] = (self.thresholds["pressure_low"] - avg_pressure) / 20.0

        # Precipitation
        max_precipitation = max([f.precipitation for f in forecasts], default=0)
        scores["precipitation"] = min(max_precipitation / self.thresholds["precipitation_high"], 1.0)

        # Cloud cover
        avg_cloud_cover = np.mean([f.cloud_cover for f in forecasts])
        scores["cloud_cover"] = min(avg_cloud_cover / self.thresholds["cloud_cover_high"], 1.0)

        return {key: round(value, 2) for key, value in scores.items()}


class MigraineScoring(ScoringStrategy):
    """Base weather scores plus a PM2.5-based air_quality component."""

    def score(self, forecasts, previous_forecasts) -> ScoreResult:
        scores = self._base_weather_scores(forecasts, previous_forecasts)
        scores["air_quality"] = 0.0
        if not forecasts:
            return ScoreResult(scores=scores, weights=self.weights)
        fc_list = list(forecasts)
        location = fc_list[0].location
        aq_rows = list(_fetch_air_quality(location, fc_list))
        if not aq_rows:
            return ScoreResult(scores=scores, weights=self.weights)
        pm25_values = [getattr(row, "pm2_5", None) for row in aq_rows]
        pm25_values = [v for v in pm25_values if v is not None]
        if pm25_values:
            scores["air_quality"] = round(
                min(float(max(pm25_values)) / self.thresholds["pm2_5_high"], 1.0), 2
            )
        return ScoreResult(scores=scores, weights=self.weights)


class SinusitisScoring(ScoringStrategy):
    """Base weather scores plus a PM10/dust-based air_quality component."""

    def score(self, forecasts, previous_forecasts) -> ScoreResult:
        scores = self._base_weather_scores(forecasts, previous_forecasts)
        scores["air_quality"] = 0.0
        if not forecasts:
            return ScoreResult(scores=scores, weights=self.weights)
        fc_list = list(forecasts)
        location = fc_list[0].location
        aq_rows = list(_fetch_air_quality(location, fc_list))
        if not aq_rows:
            return ScoreResult(scores=scores, weights=self.weights)
        components = []
        for field_name, threshold in (
            ("pm10", self.thresholds["pm10_high"]),
            ("dust", self.thresholds["dust_high"]),
        ):
            values = [getattr(row, field_name, None) for row in aq_rows]
            values = [v for v in values if v is not None]
            if values:
                components.append(min(float(max(values)) / threshold, 1.0))
        if components:
            scores["air_quality"] = round(float(np.mean(components)), 2)
        return ScoreResult(scores=scores, weights=self.weights)


class HayFeverScoring(ScoringStrategy):
    """Pollen-driven scoring with a non-EU (no-pollen) weight fallback.

    When every pollen field in the window is NULL we still emit a prediction
    from PM2.5/PM10/ozone/wind/humidity, swap to ``weights_no_pollen``, record
    ``pollen_available=False`` and down-weight confidence (0.75x).
    """

    def __init__(self, thresholds, weights, weights_no_pollen):
        super().__init__(thresholds, weights)
        self.weights_no_pollen = weights_no_pollen

    def score(self, forecasts, previous_forecasts) -> ScoreResult:
        scores = {
            "pollen": 0.0,
            "wind": 0.0,
            "humidity_extreme": 0.0,
            "air_quality": 0.0,
            "dry_warm": 0.0,
        }
        if not forecasts:
            return ScoreResult(scores=scores, weights=self.weights)

        fc_list = list(forecasts)
        location = fc_list[0].location
        aq_rows = list(_fetch_air_quality(location, fc_list))

        pollen_available = self._score_pollen(scores, aq_rows)
        self._score_wind(scores, fc_list)
        self._score_humidity(scores, fc_list)
        self._score_air_quality(scores, aq_rows)
        self._score_dry_warm(scores, fc_list)

        scores = {key: round(value, 2) for key, value in scores.items()}

        if pollen_available:
            return ScoreResult(
                scores=scores, weights=self.weights,
                factor_extras={"pollen_available": True, "weights_used": "default"},
            )
        return ScoreResult(
            scores=scores, weights=self.weights_no_pollen,
            factor_extras={
                "pollen_available": False,
                "weights_used": "no_pollen",
                "confidence_downgraded_no_pollen": True,
            },
            confidence_factor=0.75,
        )

    def _score_pollen(self, scores, aq_rows):
        pollen_fields = (
            "alder_pollen", "birch_pollen", "grass_pollen",
            "mugwort_pollen", "olive_pollen", "ragweed_pollen",
        )
        peaks = []
        for field_name in pollen_fields:
            values = [getattr(row, field_name, None) for row in aq_rows]
            values = [v for v in values if v is not None]
            if values:
                peaks.append(max(values))
        if not peaks:
            scores["pollen"] = 0.0
            return False
        highest = max(peaks)
        scores["pollen"] = min(highest / self.thresholds["pollen_high"], 1.0)
        return True

    def _score_wind(self, scores, forecasts):
        winds = [f.wind_speed for f in forecasts if getattr(f, "wind_speed", None) is not None]
        if winds:
            scores["wind"] = min(float(np.mean(winds)) / self.thresholds["wind_high"], 1.0)

    def _score_humidity(self, scores, forecasts):
        humidities = [f.humidity for f in forecasts if getattr(f, "humidity", None) is not None]
        if not humidities:
            return
        avg_humidity = float(np.mean(humidities))
        if avg_humidity >= self.thresholds["humidity_high"]:
            scores["humidity_extreme"] = min(
                (avg_humidity - self.thresholds["humidity_high"]) / (100 - self.thresholds["humidity_high"]),
                1.0,
            )
        elif avg_humidity <= self.thresholds["humidity_low"]:
            scores["humidity_extreme"] = min(
                (self.thresholds["humidity_low"] - avg_humidity) / self.thresholds["humidity_low"],
                1.0,
            )

    def _score_air_quality(self, scores, aq_rows):
        if not aq_rows:
            return
        components = []
        for field_name, threshold in (
            ("pm2_5", self.thresholds["pm2_5_high"]),
            ("pm10", self.thresholds["pm10_high"]),
            ("ozone", self.thresholds["ozone_high"]),
        ):
            values = [getattr(row, field_name, None) for row in aq_rows]
            values = [v for v in values if v is not None]
            if values:
                components.append(min(float(max(values)) / threshold, 1.0))
        if components:
            scores["air_quality"] = float(np.mean(components))

    def _score_dry_warm(self, scores, forecasts):
        """Warm + dry + little precipitation favours pollen release."""
        temps = [f.temperature for f in forecasts if getattr(f, "temperature", None) is not None]
        precs = [f.precipitation for f in forecasts if getattr(f, "precipitation", None) is not None]
        if not temps:
            return
        avg_temp = float(np.mean(temps))
        temp_score = max(0.0, min((avg_temp - 10.0) / 20.0, 1.0))  # ramps 10→30°C
        total_precip = float(sum(precs)) if precs else 0.0
        precip_score = max(0.0, 1.0 - min(total_precip / 5.0, 1.0))
        scores["dry_warm"] = round((temp_score + precip_score) / 2.0, 2)


# ======================================================================
# Condition registry
# ======================================================================


@dataclass(frozen=True)
class ConditionConfig:
    """Per-condition data + the scoring strategy for one health condition."""
    prediction_type: str          # e.g. "migraine"
    prediction_model: type        # Django model class
    manual_high: float
    manual_medium: float
    sensitivity_high: tuple       # (high, medium) thresholds for HIGH-sensitivity users
    sensitivity_low: tuple        # (high, medium) thresholds for LOW-sensitivity users
    llm_method: str               # LLMClient method name, e.g. "predict_probability"
    scoring: ScoringStrategy


CONDITIONS = {
    "migraine": ConditionConfig(
        prediction_type="migraine",
        prediction_model=MigrainePrediction,
        manual_high=0.7,
        manual_medium=0.4,
        sensitivity_high=(0.6, 0.3),
        sensitivity_low=(0.8, 0.5),
        llm_method="predict_probability",
        scoring=MigraineScoring(
            thresholds={
                "temperature_change": 5.0,
                "humidity_high": 70.0,
                "humidity_low": 30.0,
                "pressure_change": 5.0,
                "pressure_low": 1005.0,
                "precipitation_high": 5.0,
                "cloud_cover_high": 80.0,
                "pm2_5_high": 25.0,  # µg/m³ WHO guideline
            },
            weights={
                "temperature_change": 0.25,
                "humidity_extreme": 0.10,
                "pressure_change": 0.30,
                "pressure_low": 0.15,
                "precipitation": 0.05,
                "cloud_cover": 0.05,
                "air_quality": 0.10,
            },
        ),
    ),
    "sinusitis": ConditionConfig(
        prediction_type="sinusitis",
        prediction_model=SinusitisPrediction,
        manual_high=0.65,
        manual_medium=0.35,
        sensitivity_high=(0.55, 0.25),
        sensitivity_low=(0.75, 0.45),
        llm_method="predict_sinusitis_probability",
        scoring=SinusitisScoring(
            thresholds={
                "temperature_change": 7.0,
                "humidity_high": 75.0,
                "humidity_low": 25.0,
                "pressure_change": 6.0,
                "pressure_low": 1000.0,
                "precipitation_high": 3.0,
                "cloud_cover_high": 70.0,
                "pm10_high": 50.0,    # µg/m³ WHO guideline
                "dust_high": 100.0,   # µg/m³ coarse dust irritation threshold
            },
            weights={
                "temperature_change": 0.30,
                "humidity_extreme": 0.10,
                "pressure_change": 0.20,
                "pressure_low": 0.10,
                "precipitation": 0.10,
                "cloud_cover": 0.05,
                "air_quality": 0.15,
            },
        ),
    ),
    "hayfever": ConditionConfig(
        prediction_type="hayfever",
        prediction_model=HayFeverPrediction,
        manual_high=0.6,
        manual_medium=0.3,
        sensitivity_high=(0.5, 0.2),
        sensitivity_low=(0.7, 0.4),
        llm_method="predict_hayfever_probability",
        scoring=HayFeverScoring(
            thresholds={
                "pollen_high": 50.0,       # grains/m³ conservative "high" bound
                "wind_high": 8.0,          # m/s — strong pollen dispersal
                "humidity_low": 30.0,      # dry favours release
                "humidity_high": 85.0,     # very humid aggravates symptoms
                "pm2_5_high": 25.0,        # µg/m³ WHO guideline
                "pm10_high": 50.0,         # µg/m³ WHO guideline
                "ozone_high": 120.0,       # µg/m³ WHO 8-h guideline
            },
            weights={
                "pollen": 0.50,
                "wind": 0.10,
                "humidity_extreme": 0.05,
                "air_quality": 0.25,
                "dry_warm": 0.10,
            },
            weights_no_pollen={
                "pollen": 0.0,
                "wind": 0.15,
                "humidity_extreme": 0.15,
                "air_quality": 0.55,
                "dry_warm": 0.15,
            },
        ),
    ),
}


# ======================================================================
# Deep prediction service
# ======================================================================


class PredictionService:
    """Deep weather-based health prediction service for a single condition.

    Construct with a ``ConditionConfig`` (or via :meth:`for_condition`); the
    only condition-specific behaviour lives in ``config.scoring``.
    """

    def __init__(self, config: ConditionConfig):
        self.config = config

    @classmethod
    def for_condition(cls, name: str) -> "PredictionService":
        return cls(CONDITIONS[name])

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

        score_result = self.config.scoring.score(forecasts, previous_forecasts)
        scores = score_result.scores

        adjusted_weights = dict(score_result.weights)
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
            logger.info(f"Using manual calculation for {self.config.prediction_type} prediction")
            total_score = sum(scores[f] * adjusted_weights.get(f, 0.0) for f in scores)
            probability_level = self._classify_score(total_score, applied_profile)

        if total_score is not None:
            factors_payload["total_score"] = round(total_score, 2)

        if llm_detail is not None:
            # The recorded weather_factors get a (possibly) confidence-downgraded
            # copy of the detail; the original llm_detail (full confidence) is
            # still handed to _store_llm_response so the LLMResponse row is
            # unaffected — exactly as the old post-hoc annotation behaved.
            detail_for_factors = llm_detail
            if score_result.confidence_factor != 1.0:
                detail_for_factors = copy.deepcopy(llm_detail)
                raw = detail_for_factors.get("raw")
                if isinstance(raw, dict) and isinstance(raw.get("confidence"), (int, float)):
                    raw["confidence"] = round(
                        float(raw["confidence"]) * score_result.confidence_factor, 3
                    )
            factors_payload["llm"] = {"used": llm_used, "detail": detail_for_factors}
            try:
                parsed = (detail_for_factors or {}).get("raw") or {}
                factors_payload["llm_analysis_text"] = parsed.get("analysis_text")
                factors_payload["llm_prevention_tips"] = parsed.get("prevention_tips")
            except Exception:
                logger.exception("Failed to extract LLM analysis/tips")

        # Merge condition-specific annotations (e.g. hay-fever pollen flags).
        for key, value in score_result.factor_extras.items():
            factors_payload[key] = value

        prediction = self._create_and_store_prediction(
            user, location, forecasts, start_time, end_time,
            probability_level, factors_payload, store_prediction,
            llm_used, llm_detail, original_probability_level, confidence_adjusted,
        )

        return probability_level, prediction

    def get_recent_predictions(self, user, limit=10):
        """Get recent predictions for a user."""
        return self.config.prediction_model.objects.filter(user=user).order_by("-prediction_time")[:limit]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _call_llm_predict(self, client, **kwargs):
        # Attach air-quality forecasts for the same window so the LLM can see
        # the exact AQ snapshot used by the manual scorer.
        location = kwargs.get("location")
        forecasts = kwargs.get("forecasts") or []
        aq_rows = _fetch_air_quality(location, forecasts)
        kwargs["air_quality_forecasts"] = list(aq_rows)
        return getattr(client, self.config.llm_method)(**kwargs)

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
        high_thr = self.config.manual_high
        med_thr = self.config.manual_medium
        if applied_profile is not None:
            preset = applied_profile.get("sensitivity_preset", "NORMAL")
            if preset == "HIGH":
                high_thr, med_thr = self.config.sensitivity_high
            elif preset == "LOW":
                high_thr, med_thr = self.config.sensitivity_low
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
        prediction = self.config.prediction_model(
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
                f"{self.config.prediction_type}_prediction",
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
                f"{self.config.prediction_type.capitalize()} prediction generated: "
                f"{probability_level} for {location.city}, {location.country}",
                level="info",
            )

        return prediction

    def _store_llm_response(self, user, location, prediction, llm_detail,
                            probability_level, original_probability_level, confidence_adjusted):
        if llm_detail is None:
            return
        try:
            fk_kwargs = {f"{self.config.prediction_type}_prediction": prediction}
            LLMResponse.objects.create(
                user=user,
                location=location,
                prediction_type=self.config.prediction_type,
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
            logger.exception(f"Failed to store LLMResponse for {self.config.prediction_type} prediction")

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
            message=f"Attempting LLM {self.config.prediction_type} prediction",
            level="info",
            data={
                "location": f"{location.city}, {location.country}",
                "model": llm_config.model,
                "user_id": user.id if user else None,
            },
        )
        set_tag("llm_model", llm_config.model)
        set_tag("prediction_type", self.config.prediction_type)

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
                error_msg = f"LLM returned invalid probability level for {self.config.prediction_type}: {llm_level}"
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
            logger.exception(f"LLM {self.config.prediction_type} prediction failed; falling back to manual calculation")
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
                    f"LLM {self.config.prediction_type} prediction downgraded: {llm_level} -> {downgraded} "
                    f"(confidence: {llm_confidence:.2f}, threshold: {confidence_threshold:.2f})"
                )
                return downgraded, True
            else:
                logger.info(
                    f"LLM {self.config.prediction_type} prediction successful: {llm_level} "
                    f"(confidence: {llm_confidence:.2f})"
                )
                return llm_level, False
        else:
            confidence_str = f"{llm_confidence:.2f}" if llm_confidence is not None else "N/A"
            logger.info(
                f"LLM {self.config.prediction_type} prediction successful: {llm_level} "
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
                recent_preds = self.config.prediction_model.objects.filter(
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
