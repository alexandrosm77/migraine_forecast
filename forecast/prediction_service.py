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
    }

    WEIGHTS = {
        "temperature_change": 0.25,
        "humidity_extreme": 0.15,
        "pressure_change": 0.30,
        "pressure_low": 0.15,
        "precipitation": 0.05,
        "cloud_cover": 0.10,
    }

    PREDICTION_TYPE = "migraine"
    PREDICTION_MODEL = MigrainePrediction
    MANUAL_HIGH_THRESHOLD = 0.7
    MANUAL_MEDIUM_THRESHOLD = 0.4
    SENSITIVITY_HIGH_THRESHOLDS = (0.6, 0.3)
    SENSITIVITY_LOW_THRESHOLDS = (0.8, 0.5)

    def _call_llm_predict(self, client, **kwargs):
        return client.predict_probability(**kwargs)

    def _get_prediction_fk_field(self):
        return "migraine_prediction"

    def predict_migraine_probability(self, location, user=None, store_prediction=True,
                                     window_start_hours=None, window_end_hours=None):
        """Backward-compatible wrapper around predict()."""
        return self.predict(
            location=location, user=user, store_prediction=store_prediction,
            window_start_hours=window_start_hours, window_end_hours=window_end_hours,
        )
