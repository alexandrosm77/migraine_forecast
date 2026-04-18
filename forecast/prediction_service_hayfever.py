import logging

import numpy as np

from .models import HayFeverPrediction
from .prediction_service_base import BasePredictionService

logger = logging.getLogger(__name__)


class HayFeverPredictionService(BasePredictionService):
    """
    Service for predicting hay fever (allergic rhinitis) probability.

    Drivers (in rough order of importance):
    - Pollen counts per species (alder/birch early spring, grass summer,
      olive Mediterranean spring, mugwort/ragweed late summer/autumn)
    - Wind speed (disperses pollen)
    - Dry warm conditions favour pollen release
    - PM2.5/PM10/ozone/NO2 aggravate symptoms
    - Humidity extremes

    Fallback for non-EU locations:
        Open-Meteo pollen coverage is Europe-only. When every pollen field in
        the prediction window is NULL we still emit a prediction based on
        PM2.5/PM10/ozone/wind/humidity, set
        ``weather_factors["pollen_available"] = False`` and down-weight the
        pollen contribution so confidence is inherently lower.
    """

    # Pollen concentration thresholds (grains/m³) — conservative "high" bounds
    # per-species. Above this we treat as full exposure.
    POLLEN_HIGH_THRESHOLD = 50.0

    THRESHOLDS = {
        "pollen_high": POLLEN_HIGH_THRESHOLD,
        "wind_high": 8.0,          # m/s — strong pollen dispersal
        "humidity_low": 30.0,      # dry favours release
        "humidity_high": 85.0,     # very humid aggravates symptoms
        "pm2_5_high": 25.0,        # µg/m³ WHO guideline
        "pm10_high": 50.0,         # µg/m³ WHO guideline
        "ozone_high": 120.0,       # µg/m³ WHO 8-h guideline
    }

    WEIGHTS = {
        "pollen": 0.50,
        "wind": 0.10,
        "humidity_extreme": 0.05,
        "air_quality": 0.25,
        "dry_warm": 0.10,
    }

    # Alternate weights when no pollen data is available (non-EU).
    WEIGHTS_NO_POLLEN = {
        "pollen": 0.0,
        "wind": 0.15,
        "humidity_extreme": 0.15,
        "air_quality": 0.55,
        "dry_warm": 0.15,
    }

    PREDICTION_TYPE = "hayfever"
    PREDICTION_MODEL = HayFeverPrediction
    MANUAL_HIGH_THRESHOLD = 0.6
    MANUAL_MEDIUM_THRESHOLD = 0.3
    SENSITIVITY_HIGH_THRESHOLDS = (0.5, 0.2)
    SENSITIVITY_LOW_THRESHOLDS = (0.7, 0.4)

    def _call_llm_predict(self, client, **kwargs):
        # Attach air-quality forecasts for the same window so the LLM can see
        # the exact AQ snapshot used by the manual scorer.
        location = kwargs.get("location")
        forecasts = kwargs.get("forecasts") or []
        aq_rows = self._fetch_air_quality(location, forecasts)
        kwargs["air_quality_forecasts"] = list(aq_rows)
        return client.predict_hayfever_probability(**kwargs)

    def _get_prediction_fk_field(self):
        return "hayfever_prediction"

    def predict_hayfever_probability(self, location, user=None, store_prediction=True,
                                     window_start_hours=None, window_end_hours=None):
        """Backward-compatible wrapper around predict()."""
        return self.predict(
            location=location, user=user, store_prediction=store_prediction,
            window_start_hours=window_start_hours, window_end_hours=window_end_hours,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _calculate_weather_scores(self, forecasts, previous_forecasts):
        """Compute normalised 0-1 scores for hay fever drivers.

        Output keys (numeric only, suitable for weighted sum):
            pollen, wind, humidity_extreme, air_quality, dry_warm
        """
        scores = {
            "pollen": 0.0,
            "wind": 0.0,
            "humidity_extreme": 0.0,
            "air_quality": 0.0,
            "dry_warm": 0.0,
        }
        if not forecasts:
            return scores

        fc_list = list(forecasts)
        location = fc_list[0].location
        aq_rows = list(self._fetch_air_quality(location, fc_list))

        self._score_pollen(scores, aq_rows)
        self._score_wind(scores, fc_list)
        self._score_humidity(scores, fc_list)
        self._score_air_quality(scores, aq_rows)
        self._score_dry_warm(scores, fc_list)

        return {key: round(value, 2) for key, value in scores.items()}

    def _score_pollen(self, scores, aq_rows):
        pollen_fields = (
            "alder_pollen", "birch_pollen", "grass_pollen",
            "mugwort_pollen", "olive_pollen", "ragweed_pollen",
        )
        peaks = []
        for field in pollen_fields:
            values = [getattr(row, field, None) for row in aq_rows]
            values = [v for v in values if v is not None]
            if values:
                peaks.append(max(values))
        if not peaks:
            scores["pollen"] = 0.0
            return False
        highest = max(peaks)
        scores["pollen"] = min(highest / self.THRESHOLDS["pollen_high"], 1.0)
        return True

    def _score_wind(self, scores, forecasts):
        winds = [f.wind_speed for f in forecasts if getattr(f, "wind_speed", None) is not None]
        if winds:
            scores["wind"] = min(float(np.mean(winds)) / self.THRESHOLDS["wind_high"], 1.0)

    def _score_humidity(self, scores, forecasts):
        humidities = [f.humidity for f in forecasts if getattr(f, "humidity", None) is not None]
        if not humidities:
            return
        avg_humidity = float(np.mean(humidities))
        if avg_humidity >= self.THRESHOLDS["humidity_high"]:
            scores["humidity_extreme"] = min(
                (avg_humidity - self.THRESHOLDS["humidity_high"]) / (100 - self.THRESHOLDS["humidity_high"]),
                1.0,
            )
        elif avg_humidity <= self.THRESHOLDS["humidity_low"]:
            scores["humidity_extreme"] = min(
                (self.THRESHOLDS["humidity_low"] - avg_humidity) / self.THRESHOLDS["humidity_low"],
                1.0,
            )

    def _score_air_quality(self, scores, aq_rows):
        if not aq_rows:
            return
        components = []
        for field, threshold in (
            ("pm2_5", self.THRESHOLDS["pm2_5_high"]),
            ("pm10", self.THRESHOLDS["pm10_high"]),
            ("ozone", self.THRESHOLDS["ozone_high"]),
        ):
            values = [getattr(row, field, None) for row in aq_rows]
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

    # ------------------------------------------------------------------
    # predict() override: swap in no-pollen weights + downgrade confidence
    # ------------------------------------------------------------------

    def predict(self, location, user=None, store_prediction=True,
                window_start_hours=None, window_end_hours=None):
        """Run base predict but swap weights / downgrade when pollen is absent."""
        from datetime import timedelta
        from django.utils import timezone
        from .models import WeatherForecast

        start_h, end_h = self._resolve_time_window(user, window_start_hours, window_end_hours)
        start_time = timezone.now() + timedelta(hours=start_h)
        end_time = timezone.now() + timedelta(hours=end_h)
        preview_fc = list(WeatherForecast.objects.filter(
            location=location, target_time__gte=start_time, target_time__lte=end_time,
        ).order_by("target_time"))
        pollen_available = True
        if preview_fc:
            aq_rows = list(self._fetch_air_quality(location, preview_fc))
            pollen_available = self._score_pollen({"pollen": 0.0}, aq_rows)

        try:
            if not pollen_available:
                # Shadow class attribute with an instance attribute for this call.
                self.WEIGHTS = self.WEIGHTS_NO_POLLEN
            result = super().predict(
                location=location, user=user, store_prediction=store_prediction,
                window_start_hours=window_start_hours, window_end_hours=window_end_hours,
            )
        finally:
            self.__dict__.pop("WEIGHTS", None)

        _level, prediction = result
        if prediction is not None:
            self._annotate_factors(prediction, pollen_available)
        return result

    @staticmethod
    def _annotate_factors(prediction, pollen_available):
        """Attach pollen_available/weights_used + downgrade confidence flag."""
        factors = dict(prediction.weather_factors or {})
        factors["pollen_available"] = pollen_available
        factors["weights_used"] = "default" if pollen_available else "no_pollen"
        if not pollen_available:
            factors["confidence_downgraded_no_pollen"] = True
            llm_entry = factors.get("llm")
            if isinstance(llm_entry, dict):
                detail = llm_entry.get("detail") or {}
                raw = detail.get("raw") if isinstance(detail, dict) else None
                if isinstance(raw, dict) and isinstance(raw.get("confidence"), (int, float)):
                    raw["confidence"] = round(float(raw["confidence"]) * 0.75, 3)
        prediction.weather_factors = factors
        if prediction.pk:
            prediction.save(update_fields=["weather_factors"])
