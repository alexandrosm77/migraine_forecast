import logging

from .models import SinusitisPrediction
from .prediction_service_base import BasePredictionService

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
    """

    THRESHOLDS = {
        "temperature_change": 7.0,
        "humidity_high": 75.0,
        "humidity_low": 25.0,
        "pressure_change": 6.0,
        "pressure_low": 1000.0,
        "precipitation_high": 3.0,
        "cloud_cover_high": 70.0,
    }

    WEIGHTS = {
        "temperature_change": 0.30,
        "humidity_extreme": 0.25,
        "pressure_change": 0.20,
        "pressure_low": 0.10,
        "precipitation": 0.10,
        "cloud_cover": 0.05,
    }

    PREDICTION_TYPE = "sinusitis"
    PREDICTION_MODEL = SinusitisPrediction
    MANUAL_HIGH_THRESHOLD = 0.65
    MANUAL_MEDIUM_THRESHOLD = 0.35
    SENSITIVITY_HIGH_THRESHOLDS = (0.55, 0.25)
    SENSITIVITY_LOW_THRESHOLDS = (0.75, 0.45)

    def _call_llm_predict(self, client, **kwargs):
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
