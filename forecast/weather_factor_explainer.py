import logging

import numpy as np

logger = logging.getLogger(__name__)


class WeatherFactorExplainer:
    """
    Generates human-friendly explanations of weather factors that contribute
    to condition-specific predictions (migraine, sinusitis, etc.).
    """

    # ------------------------------------------------------------------
    # Per-condition factor configuration
    # ------------------------------------------------------------------

    _MIGRAINE_FACTOR_CONFIG = {
        "llm_prediction_field": "migraine_prediction",
        "temp_trigger_text": "Rapid temperature changes are a known migraine trigger.",
        "temp_severity_multiplier": 2.0,
        "humidity_high_text": "Extreme humidity levels can increase migraine risk.",
        "humidity_low_text": "Very dry air can trigger migraines.",
        "humidity_low_severe": 20,
        "humidity_change_threshold": 5,
        "humidity_change_detail": True,
        "pressure_change_text": "Rapid pressure changes are one of the strongest migraine triggers.",
        "pressure_change_severity_multiplier": 2.0,
        "pressure_change_detail": True,
        "pressure_low_text": "Low pressure systems are associated with increased migraine frequency.",
        "pressure_low_severe": 995,
        "pressure_low_range_from_llm": True,
        "precip_heavy_name": "Heavy Precipitation",
        "precip_moderate_name": "Moderate Precipitation",
        "precip_heavy_text": "Heavy rain or storms can trigger migraines.",
        "precip_moderate_text": "Rain and changing weather patterns can contribute to migraine risk.",
        "precip_severe": 10,
        "cloud_heavy_name": "Heavy Cloud Cover",
        "cloud_moderate_name": "Moderate Cloud Cover",
        "cloud_heavy_text": "Overcast conditions can affect some migraine sufferers.",
        "cloud_moderate_text": "Changing light conditions can contribute to migraine risk for some people.",
    }

    _SINUSITIS_FACTOR_CONFIG = {
        "llm_prediction_field": None,
        "temp_trigger_text": "Rapid temperature changes can irritate sinuses.",
        "temp_severity_multiplier": 1.5,
        "humidity_high_text": "High humidity promotes mold growth and allergens that can trigger sinusitis.",
        "humidity_low_text": "Very dry air can dry out and irritate sinus passages.",
        "humidity_low_severe": 15,
        "humidity_change_threshold": 10,
        "humidity_change_detail": False,
        "pressure_change_text": "Pressure changes can affect sinus pressure and cause discomfort.",
        "pressure_change_severity_multiplier": 1.5,
        "pressure_change_detail": False,
        "pressure_low_text": "Low pressure systems can worsen sinus symptoms.",
        "pressure_low_severe": 990,
        "pressure_low_range_from_llm": False,
        "precip_heavy_name": "Precipitation",
        "precip_moderate_name": "Precipitation",
        "precip_heavy_text": "Rain can increase mold spores and allergens in the air.",
        "precip_moderate_text": "Rain can increase mold spores and allergens in the air.",
        "precip_severe": 8,
        "cloud_heavy_name": "Cloud Cover",
        "cloud_moderate_name": "Cloud Cover",
        "cloud_heavy_text": None,
        "cloud_moderate_text": None,
    }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_detailed_weather_factors(self, prediction):
        """Get detailed migraine weather factors."""
        return self._get_detailed_factors(prediction, "migraine")

    def get_detailed_sinusitis_factors(self, prediction):
        """Get detailed sinusitis weather factors."""
        return self._get_detailed_factors(prediction, "sinusitis")

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def _get_detailed_factors(self, prediction, prediction_type):
        """
        Get detailed, human-friendly explanations of weather factors for any condition type.

        Args:
            prediction: MigrainePrediction or SinusitisPrediction instance
            prediction_type: "migraine" or "sinusitis"

        Returns:
            dict with factors, total_score, contributing_factors_count
        """
        from .models import WeatherForecast, LLMResponse

        if prediction_type == "migraine":
            from .prediction_service import MigrainePredictionService
            thresholds = MigrainePredictionService.THRESHOLDS
            weights = MigrainePredictionService.WEIGHTS
            cfg = self._MIGRAINE_FACTOR_CONFIG
        else:
            from .prediction_service_sinusitis import SinusitisPredictionService
            thresholds = SinusitisPredictionService.THRESHOLDS
            weights = SinusitisPredictionService.WEIGHTS
            cfg = self._SINUSITIS_FACTOR_CONFIG

        wf = prediction.weather_factors or {}
        factors = []

        # Optionally load LLM context
        llm_ctx = None
        if cfg["llm_prediction_field"]:
            try:
                fk_filter = {cfg["llm_prediction_field"]: prediction}
                llm_resp = LLMResponse.objects.filter(**fk_filter).first()
                if llm_resp and llm_resp.request_payload:
                    llm_ctx = llm_resp.request_payload.get("context", {})
            except Exception:
                logger.debug("Could not retrieve LLM context for prediction %s", prediction.id)

        # Fetch forecasts
        forecasts = WeatherForecast.objects.filter(
            location=prediction.location,
            target_time__gte=prediction.target_time_start,
            target_time__lte=prediction.target_time_end,
        ).order_by("target_time")
        previous_forecasts = WeatherForecast.objects.filter(
            location=prediction.location, target_time__lt=prediction.target_time_start
        ).order_by("-target_time")[:6]

        if not forecasts:
            return {"factors": factors, "total_score": 0}

        # --- Individual factors ---
        self._add_temperature_factor(factors, wf, forecasts, previous_forecasts, llm_ctx, thresholds, weights, cfg)
        self._add_humidity_factor(factors, wf, forecasts, previous_forecasts, llm_ctx, thresholds, weights, cfg)
        self._add_pressure_change_factor(factors, wf, forecasts, previous_forecasts, llm_ctx, thresholds, weights, cfg)
        self._add_low_pressure_factor(factors, wf, forecasts, previous_forecasts, llm_ctx, thresholds, weights, cfg)
        self._add_precipitation_factor(factors, wf, forecasts, llm_ctx, thresholds, weights, cfg)
        self._add_cloud_cover_factor(factors, wf, forecasts, llm_ctx, thresholds, weights, cfg)

        # Calculate total weighted score
        total_score = 0.0
        for factor_name in ["temperature_change", "humidity_extreme", "pressure_change",
                            "pressure_low", "precipitation", "cloud_cover"]:
            total_score += wf.get(factor_name, 0) * weights.get(factor_name, 0)

        factors.sort(key=lambda x: x["score"] * x["weight"], reverse=True)

        return {
            "factors": factors,
            "total_score": round(total_score, 2),
            "contributing_factors_count": len(factors),
        }

    # ------------------------------------------------------------------
    # Factor helper methods
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_value(llm_ctx, section, key, fallback_fn):
        """Get a value from LLM context or compute it from a fallback function."""
        if llm_ctx and section in llm_ctx and key in llm_ctx[section]:
            return llm_ctx[section][key]
        return fallback_fn()

    def _add_temperature_factor(self, factors, wf, forecasts, prev_forecasts,
                                llm_ctx, thresholds, weights, cfg):
        if wf.get("temperature_change", 0) <= 0 or not prev_forecasts:
            return

        if llm_ctx and "changes" in llm_ctx and "temperature_change" in llm_ctx["changes"]:
            temp_change = llm_ctx["changes"]["temperature_change"]
            avg_forecast_temp = (llm_ctx.get("aggregates", {}).get("avg_forecast_temperature")
                                 or np.mean([f.temperature for f in forecasts]))
            avg_prev_temp = avg_forecast_temp - temp_change
        else:
            avg_prev_temp = np.mean([f.temperature for f in prev_forecasts])
            avg_forecast_temp = np.mean([f.temperature for f in forecasts])
            temp_change = abs(avg_forecast_temp - avg_prev_temp)

        if temp_change < thresholds["temperature_change"]:
            return

        direction = "increase" if avg_forecast_temp > avg_prev_temp else "decrease"
        pct_text = ""
        if cfg.get("pressure_change_detail"):  # migraine includes % change
            pct = abs((temp_change / avg_prev_temp) * 100) if avg_prev_temp != 0 else 0
            pct_text = f" ({pct:.0f}% change)"

        factors.append({
            "name": "Temperature Change",
            "score": wf["temperature_change"],
            "weight": weights["temperature_change"],
            "explanation": (
                f"Temperature will {direction} by {temp_change:.1f}°C{pct_text} "
                f"from {avg_prev_temp:.1f}°C to {avg_forecast_temp:.1f}°C. "
                f"{cfg['temp_trigger_text']}"
            ),
            "severity": ("high" if temp_change >= thresholds["temperature_change"] * cfg["temp_severity_multiplier"]
                         else "medium"),
        })

    def _add_humidity_factor(self, factors, wf, forecasts, prev_forecasts,
                             llm_ctx, thresholds, weights, cfg):
        if wf.get("humidity_extreme", 0) <= 0:
            return

        avg_humidity = self._resolve_value(
            llm_ctx, "aggregates", "avg_forecast_humidity",
            lambda: float(np.mean([f.humidity for f in forecasts]))
        )

        if avg_humidity >= thresholds["humidity_high"]:
            change_text = self._compute_humidity_change_text(
                avg_humidity, prev_forecasts, llm_ctx, cfg
            )
            factors.append({
                "name": "High Humidity",
                "score": wf["humidity_extreme"],
                "weight": weights["humidity_extreme"],
                "explanation": (
                    f"Humidity will be {avg_humidity:.1f}%, which is very high.{change_text} "
                    f"{cfg['humidity_high_text']}"
                ),
                "severity": "high" if avg_humidity >= 85 else "medium",
            })
        elif avg_humidity <= thresholds["humidity_low"]:
            change_text = self._compute_humidity_change_text(
                avg_humidity, prev_forecasts, llm_ctx, cfg
            )
            factors.append({
                "name": "Low Humidity",
                "score": wf["humidity_extreme"],
                "weight": weights["humidity_extreme"],
                "explanation": (
                    f"Humidity will be {avg_humidity:.1f}%, which is very low.{change_text} "
                    f"{cfg['humidity_low_text']}"
                ),
                "severity": "high" if avg_humidity <= cfg["humidity_low_severe"] else "medium",
            })

    def _compute_humidity_change_text(self, avg_humidity, prev_forecasts, llm_ctx, cfg):
        """Compute humidity change text, with detail level based on config."""
        if llm_ctx and "changes" in llm_ctx and "humidity_change" in llm_ctx["changes"]:
            humidity_change = llm_ctx["changes"]["humidity_change"]
            avg_prev = avg_humidity - humidity_change
        elif prev_forecasts:
            avg_prev = float(np.mean([f.humidity for f in prev_forecasts]))
            humidity_change = avg_humidity - avg_prev
        else:
            return ""

        threshold = cfg["humidity_change_threshold"]
        if abs(humidity_change) < threshold:
            return ""

        change_dir = "rising" if humidity_change > 0 else ("dropping" if humidity_change < 0 else "falling")
        if cfg["humidity_change_detail"] and avg_prev != 0:
            pct = abs((humidity_change / avg_prev) * 100)
            return (f" Humidity is {change_dir} by {abs(humidity_change):.1f} percentage points "
                    f"({pct:.0f}% change) from {avg_prev:.1f}%.")
        return f" Humidity is {change_dir} by {abs(humidity_change):.1f}%."

    def _add_pressure_change_factor(self, factors, wf, forecasts, prev_forecasts,
                                    llm_ctx, thresholds, weights, cfg):
        if wf.get("pressure_change", 0) <= 0 or not prev_forecasts:
            return

        if llm_ctx and "changes" in llm_ctx and "pressure_change" in llm_ctx["changes"]:
            pressure_change = llm_ctx["changes"]["pressure_change"]
            avg_forecast = (llm_ctx.get("aggregates", {}).get("avg_forecast_pressure")
                            or np.mean([f.pressure for f in forecasts]))
            avg_prev = avg_forecast - pressure_change
        else:
            avg_prev = float(np.mean([f.pressure for f in prev_forecasts]))
            avg_forecast = float(np.mean([f.pressure for f in forecasts]))
            pressure_change = abs(avg_forecast - avg_prev)

        if pressure_change < thresholds["pressure_change"]:
            return

        direction = "rise" if avg_forecast > avg_prev else "drop"
        pct_text = ""
        if cfg["pressure_change_detail"] and avg_prev != 0:
            pct = abs((pressure_change / avg_prev) * 100)
            pct_text = f" ({pct:.1f}% change)"

        severity_thr = thresholds["pressure_change"] * cfg["pressure_change_severity_multiplier"]
        factors.append({
            "name": "Pressure Change",
            "score": wf["pressure_change"],
            "weight": weights["pressure_change"],
            "explanation": (
                f"Barometric pressure will {direction} by {pressure_change:.1f} hPa{pct_text} "
                f"from {avg_prev:.1f} hPa to {avg_forecast:.1f} hPa. "
                f"{cfg['pressure_change_text']}"
            ),
            "severity": "high" if pressure_change >= severity_thr else "medium",
        })

    def _add_low_pressure_factor(self, factors, wf, forecasts, prev_forecasts,
                                 llm_ctx, thresholds, weights, cfg):
        if wf.get("pressure_low", 0) <= 0:
            return

        avg_pressure = self._resolve_value(
            llm_ctx, "aggregates", "avg_forecast_pressure",
            lambda: float(np.mean([f.pressure for f in forecasts]))
        )

        if avg_pressure > thresholds["pressure_low"]:
            return

        range_text = ""
        if cfg["pressure_low_range_from_llm"] and llm_ctx and "aggregates" in llm_ctx:
            min_p = llm_ctx["aggregates"].get("min_forecast_pressure")
            max_p = llm_ctx["aggregates"].get("max_forecast_pressure")
            if min_p is not None and max_p is not None:
                range_text = f" Pressure will range from {min_p:.1f} to {max_p:.1f} hPa."
        if not range_text:
            pressures = [f.pressure for f in forecasts]
            if pressures:
                range_text = f" Pressure will range from {min(pressures):.1f} to {max(pressures):.1f} hPa."

        factors.append({
            "name": "Low Pressure",
            "score": wf["pressure_low"],
            "weight": weights["pressure_low"],
            "explanation": (
                f"Barometric pressure is low at {avg_pressure:.1f} hPa.{range_text} "
                f"{cfg['pressure_low_text']}"
            ),
            "severity": "high" if avg_pressure <= cfg["pressure_low_severe"] else "medium",
        })

    def _add_precipitation_factor(self, factors, wf, forecasts, llm_ctx, thresholds, weights, cfg):
        if wf.get("precipitation", 0) <= 0:
            return

        max_precip = max([f.precipitation for f in forecasts], default=0)
        if max_precip < thresholds["precipitation_high"]:
            return

        is_heavy = max_precip >= cfg["precip_severe"]
        name = cfg["precip_heavy_name"] if is_heavy else cfg["precip_moderate_name"]
        explanation = cfg["precip_heavy_text"] if is_heavy else cfg["precip_moderate_text"]
        factors.append({
            "name": name,
            "score": wf["precipitation"],
            "weight": weights["precipitation"],
            "explanation": f"Max precipitation: {max_precip:.1f} mm/hr. {explanation}",
            "severity": "high" if is_heavy else "medium",
        })

    def _add_cloud_cover_factor(self, factors, wf, forecasts, llm_ctx, thresholds, weights, cfg):
        if wf.get("cloud_cover", 0) <= 0:
            return

        avg_cloud = self._resolve_value(
            llm_ctx, "aggregates", "avg_forecast_cloud_cover",
            lambda: float(np.mean([f.cloud_cover for f in forecasts]))
        )

        if avg_cloud < thresholds["cloud_cover_high"] * 0.7:
            return

        is_heavy = avg_cloud >= thresholds["cloud_cover_high"]
        name = cfg["cloud_heavy_name"] if is_heavy else cfg["cloud_moderate_name"]

        if is_heavy and cfg["cloud_heavy_text"]:
            text = cfg["cloud_heavy_text"]
        elif not is_heavy and cfg["cloud_moderate_text"]:
            text = cfg["cloud_moderate_text"]
        else:
            text = (f"Cloud cover above {thresholds['cloud_cover_high']:.0f}% "
                    f"is associated with weather changes.")

        factors.append({
            "name": name,
            "score": wf["cloud_cover"],
            "weight": weights["cloud_cover"],
            "explanation": f"Cloud cover will be around {avg_cloud:.0f}%. {text}",
            "severity": "medium",
        })
