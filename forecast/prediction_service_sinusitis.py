import logging

import numpy as np

from .models import SinusitisPrediction
from .prediction_service_base import BasePredictionService
from .prediction_service_hayfever import HayFeverPredictionService

logger = logging.getLogger(__name__)


class SinusitisPredictionService(BasePredictionService):
    """
    Service for predicting sinusitis flare-up probability based on weather forecast data.

    Sinusitis is often triggered by:
    - Rapid temperature changes (especially cold fronts)
    - High humidity (promotes mold and allergens)
    - Low humidity (dries out sinuses)
    - Barometric pressure changes (affects sinus pressure)
    - High pollen counts (correlated with certain weather patterns)
    - Coarse particulates (PM10, dust) that directly irritate sinus mucosa
    """

    THRESHOLDS = {
        "temperature_change": 7.0,
        "humidity_high": 75.0,
        "humidity_low": 25.0,
        "pressure_change": 6.0,
        "pressure_low": 1000.0,
        "precipitation_high": 3.0,
        "cloud_cover_high": 70.0,
        "pm10_high": 50.0,    # µg/m³ WHO guideline
        "dust_high": 100.0,   # µg/m³ coarse dust irritation threshold
    }

    WEIGHTS = {
        "temperature_change": 0.30,
        "humidity_extreme": 0.10,
        "pressure_change": 0.20,
        "pressure_low": 0.10,
        "precipitation": 0.10,
        "cloud_cover": 0.05,
        "air_quality": 0.15,
    }

    PREDICTION_TYPE = "sinusitis"
    PREDICTION_MODEL = SinusitisPrediction
    MANUAL_HIGH_THRESHOLD = 0.65
    MANUAL_MEDIUM_THRESHOLD = 0.35
    SENSITIVITY_HIGH_THRESHOLDS = (0.55, 0.25)
    SENSITIVITY_LOW_THRESHOLDS = (0.75, 0.45)

    def _call_llm_predict(self, client, **kwargs):
        # Attach air-quality forecasts for the same window so the LLM can see
        # the exact AQ snapshot used by the manual scorer.
        location = kwargs.get("location")
        forecasts = kwargs.get("forecasts") or []
        aq_rows = HayFeverPredictionService._fetch_air_quality(location, forecasts)
        kwargs["air_quality_forecasts"] = list(aq_rows)
        return client.predict_sinusitis_probability(**kwargs)

    def _get_prediction_fk_field(self):
        return "sinusitis_prediction"

    def predict_sinusitis_probability(self, location, user=None, store_prediction=True,
                                      window_start_hours=None, window_end_hours=None):
        """Backward-compatible wrapper around predict()."""
        return self.predict(
            location=location, user=user, store_prediction=store_prediction,
            window_start_hours=window_start_hours, window_end_hours=window_end_hours,
        )

    def _calculate_weather_scores(self, forecasts, previous_forecasts):
        """Extend base weather scores with an air_quality component (PM10 + dust)."""
        scores = super()._calculate_weather_scores(forecasts, previous_forecasts)
        scores["air_quality"] = 0.0
        if not forecasts:
            return scores

        fc_list = list(forecasts)
        location = fc_list[0].location
        aq_rows = list(HayFeverPredictionService._fetch_air_quality(location, fc_list))
        if not aq_rows:
            return scores

        components = []
        for field, threshold in (
            ("pm10", self.THRESHOLDS["pm10_high"]),
            ("dust", self.THRESHOLDS["dust_high"]),
        ):
            values = [getattr(row, field, None) for row in aq_rows]
            values = [v for v in values if v is not None]
            if values:
                components.append(min(float(max(values)) / threshold, 1.0))
        if components:
            scores["air_quality"] = round(float(np.mean(components)), 2)
        return scores
