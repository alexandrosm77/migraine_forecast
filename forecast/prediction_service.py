import logging

from .models import MigrainePrediction
from .prediction_service_base import BasePredictionService, LLMInvalidResponseError  # noqa: F401

logger = logging.getLogger(__name__)


class MigrainePredictionService(BasePredictionService):
    """
    Service for predicting migraine probability based on weather forecast data.
    """

    THRESHOLDS = {
        "temperature_change": 5.0,
        "humidity_high": 70.0,
        "humidity_low": 30.0,
        "pressure_change": 5.0,
        "pressure_low": 1005.0,
        "precipitation_high": 5.0,
        "cloud_cover_high": 80.0,
        "pm2_5_high": 25.0,  # µg/m³ WHO guideline
    }

    WEIGHTS = {
        "temperature_change": 0.25,
        "humidity_extreme": 0.10,
        "pressure_change": 0.30,
        "pressure_low": 0.15,
        "precipitation": 0.05,
        "cloud_cover": 0.05,
        "air_quality": 0.10,
    }

    PREDICTION_TYPE = "migraine"
    PREDICTION_MODEL = MigrainePrediction
    MANUAL_HIGH_THRESHOLD = 0.7
    MANUAL_MEDIUM_THRESHOLD = 0.4
    SENSITIVITY_HIGH_THRESHOLDS = (0.6, 0.3)
    SENSITIVITY_LOW_THRESHOLDS = (0.8, 0.5)

    def _call_llm_predict(self, client, **kwargs):
        # Attach air-quality forecasts for the same window so the LLM can see
        # the exact AQ snapshot used by the manual scorer.
        location = kwargs.get("location")
        forecasts = kwargs.get("forecasts") or []
        aq_rows = self._fetch_air_quality(location, forecasts)
        kwargs["air_quality_forecasts"] = list(aq_rows)
        return client.predict_probability(**kwargs)

    def _get_prediction_fk_field(self):
        return "migraine_prediction"

    def _calculate_weather_scores(self, forecasts, previous_forecasts):
        """Add PM2.5-based air_quality score on top of the base weather scores."""
        scores = super()._calculate_weather_scores(forecasts, previous_forecasts)
        scores["air_quality"] = 0.0
        if not forecasts:
            return scores
        fc_list = list(forecasts)
        location = fc_list[0].location
        aq_rows = list(self._fetch_air_quality(location, fc_list))
        if not aq_rows:
            return scores
        pm25_values = [getattr(row, "pm2_5", None) for row in aq_rows]
        pm25_values = [v for v in pm25_values if v is not None]
        if pm25_values:
            scores["air_quality"] = round(
                min(float(max(pm25_values)) / self.THRESHOLDS["pm2_5_high"], 1.0), 2
            )
        return scores

    def predict_migraine_probability(self, location, user=None, store_prediction=True,
                                     window_start_hours=None, window_end_hours=None):
        """Backward-compatible wrapper around predict()."""
        return self.predict(
            location=location, user=user, store_prediction=store_prediction,
            window_start_hours=window_start_hours, window_end_hours=window_end_hours,
        )
