"""
LLM Context Builder Module

Builds structured weather context for LLM prompts with support for
low and high token budgets. Provides actual weather values instead
of normalized scores.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from django.utils import timezone

logger = logging.getLogger(__name__)


class LLMContextBuilder:
    """
    Builds weather context for LLM prompts.

    Supports two modes:
    - Low token budget (default): Compact summaries
    - High token budget: Full hourly tables and detailed context
    """

    # Approximate diurnal temperature ranges by latitude band and season
    # Format: (latitude_min, latitude_max): {season: (min_range, max_range)}
    DIURNAL_RANGES = {
        (0, 23): {"spring": (6, 10), "summer": (6, 10), "fall": (6, 10), "winter": (6, 10)},  # Tropical
        (23, 45): {"spring": (8, 14), "summer": (10, 18), "fall": (8, 14), "winter": (6, 12)},  # Subtropical/Temperate
        (45, 66): {"spring": (6, 12), "summer": (8, 15), "fall": (6, 12), "winter": (4, 10)},  # Mid-latitude
        (66, 90): {"spring": (4, 10), "summer": (5, 12), "fall": (4, 10), "winter": (2, 8)},  # Polar
    }

    # Pollen season by month and hemisphere
    # Values: "low", "moderate", "high", "very_high"
    POLLEN_SEASONS = {
        "northern": {
            1: "low",
            2: "low",
            3: "moderate",
            4: "high",
            5: "very_high",
            6: "high",
            7: "moderate",
            8: "moderate",
            9: "moderate",
            10: "low",
            11: "low",
            12: "low",
        },
        "southern": {
            1: "moderate",
            2: "moderate",
            3: "low",
            4: "low",
            5: "low",
            6: "low",
            7: "low",
            8: "moderate",
            9: "high",
            10: "very_high",
            11: "high",
            12: "moderate",
        },
    }

    def __init__(self, high_token_budget: bool = False):
        """
        Initialize the context builder.

        Args:
            high_token_budget: If True, include full hourly tables and detailed context.
                             If False (default), use compact summaries.
        """
        self.high_token_budget = high_token_budget

    def build_migraine_context(
        self,
        forecasts: List[Any],
        previous_forecasts: List[Any],
        location: Any,
        user_profile: Optional[Dict[str, Any]] = None,
        previous_predictions: Optional[List[Any]] = None,
    ) -> str:
        """
        Build context string for migraine prediction.

        Args:
            forecasts: List of WeatherForecast objects for the prediction window
            previous_forecasts: List of WeatherForecast objects from previous period
            location: Location model instance
            user_profile: Optional user health profile dict
            previous_predictions: Optional list of recent MigrainePrediction objects

        Returns:
            Formatted context string for LLM prompt
        """
        return self._build_context(
            forecasts=forecasts,
            previous_forecasts=previous_forecasts,
            location=location,
            user_profile=user_profile,
            previous_predictions=previous_predictions,
            condition_type="migraine",
        )

    def build_sinusitis_context(
        self,
        forecasts: List[Any],
        previous_forecasts: List[Any],
        location: Any,
        user_profile: Optional[Dict[str, Any]] = None,
        previous_predictions: Optional[List[Any]] = None,
    ) -> str:
        """
        Build context string for sinusitis prediction.

        Args:
            forecasts: List of WeatherForecast objects for the prediction window
            previous_forecasts: List of WeatherForecast objects from previous period
            location: Location model instance
            user_profile: Optional user health profile dict
            previous_predictions: Optional list of recent SinusitisPrediction objects

        Returns:
            Formatted context string for LLM prompt
        """
        return self._build_context(
            forecasts=forecasts,
            previous_forecasts=previous_forecasts,
            location=location,
            user_profile=user_profile,
            previous_predictions=previous_predictions,
            condition_type="sinusitis",
        )

    def _build_context(
        self,
        forecasts: List[Any],
        previous_forecasts: List[Any],
        location: Any,
        user_profile: Optional[Dict[str, Any]],
        previous_predictions: Optional[List[Any]],
        condition_type: str,
    ) -> str:
        """Build the complete context string."""
        if not forecasts:
            return "No forecast data available."

        parts = []
        now = timezone.now()

        # Get season and location info
        latitude = float(location.latitude) if location.latitude else 51.5
        season = self._get_season(now, latitude)

        # Header with location and time
        parts.append(self._format_header(location, latitude, season, now, forecasts))

        # Diurnal context (expected temperature variation)
        parts.append(self._format_diurnal_context(latitude, season, forecasts))

        # Sinusitis-specific: pollen and mold context
        if condition_type == "sinusitis":
            parts.append(self._format_seasonal_health_context(latitude, now, forecasts))

        # Hourly forecast or summary
        parts.append(self._format_hourly_forecast(forecasts))

        # Weather changes from previous period
        if previous_forecasts:
            parts.append(self._format_weather_changes(forecasts, previous_forecasts))

        # Stability within forecast window
        parts.append(self._format_window_stability(forecasts))

        # User sensitivity profile
        if user_profile:
            parts.append(self._format_user_sensitivity(user_profile))

        # Historical predictions with weather context
        if previous_predictions:
            parts.append(self._format_historical_predictions(previous_predictions, location, condition_type))

        return "\n\n".join(filter(None, parts))

    def _format_header(
        self,
        location: Any,
        latitude: float,
        season: str,
        now: datetime,
        forecasts: List[Any],
    ) -> str:
        """Format the header with location and time info."""
        city = location.city if hasattr(location, "city") else "Unknown"
        country = location.country if hasattr(location, "country") else ""

        day_name = now.strftime("%A")
        time_str = now.strftime("%H:%M UTC")

        lat_str = f"{abs(latitude):.1f}°{'N' if latitude >= 0 else 'S'}"

        if self.high_token_budget:
            return (
                f"Location: {city}, {country} ({lat_str})\n" f"Season: {season.capitalize()} | {day_name} | {time_str}"
            )
        else:
            return f"{city}, {country} ({lat_str}) | {season.capitalize()} | {day_name[:3]} {time_str}"

    def _format_diurnal_context(
        self,
        latitude: float,
        season: str,
        forecasts: List[Any],
    ) -> str:
        """Format expected diurnal temperature range context."""
        diurnal_range = self._get_expected_diurnal_range(latitude, season)

        # Determine time of day span
        if forecasts:
            start_hour = forecasts[0].target_time.hour
            end_hour = forecasts[-1].target_time.hour
            time_span = self._get_time_span_description(start_hour, end_hour)
        else:
            time_span = "unknown period"

        if self.high_token_budget:
            return (
                f"## Expected Conditions\n"
                f"Typical diurnal temperature range for this location/season: "
                f"{diurnal_range[0]}-{diurnal_range[1]}°C\n"
                f"Forecast spans {time_span}"
            )
        else:
            return f"Expected diurnal range: {diurnal_range[0]}-{diurnal_range[1]}°C | Forecast: {time_span}"

    def _get_time_span_description(self, start_hour: int, end_hour: int) -> str:
        """Get a description of the time span covered."""

        def period_name(hour: int) -> str:
            if 5 <= hour < 12:
                return "morning"
            elif 12 <= hour < 17:
                return "afternoon"
            elif 17 <= hour < 21:
                return "evening"
            else:
                return "night"

        start_period = period_name(start_hour)
        end_period = period_name(end_hour)

        if start_period == end_period:
            return start_period
        else:
            # Add natural temperature expectation
            if start_period in ["morning", "afternoon"] and end_period in ["evening", "night"]:
                return f"{start_period} to {end_period} (natural cooling expected)"
            elif start_period in ["night", "evening"] and end_period in ["morning", "afternoon"]:
                return f"{start_period} to {end_period} (natural warming expected)"
            else:
                return f"{start_period} to {end_period}"

    def _format_seasonal_health_context(
        self,
        latitude: float,
        now: datetime,
        forecasts: List[Any],
    ) -> str:
        """Format sinusitis-specific seasonal context (pollen, mold, heating)."""
        hemisphere = "northern" if latitude >= 0 else "southern"
        month = now.month
        pollen_level = self.POLLEN_SEASONS[hemisphere].get(month, "moderate")

        # Calculate average humidity and temp for mold risk
        if forecasts:
            avg_humidity = np.mean([f.humidity for f in forecasts])
            avg_temp = np.mean([f.temperature for f in forecasts])
        else:
            avg_humidity = 50
            avg_temp = 15

        # Mold risk assessment
        mold_risk = self._assess_mold_risk(avg_humidity, avg_temp)

        # Indoor heating assessment
        heating_status = self._assess_heating_status(avg_temp, month, hemisphere)

        if self.high_token_budget:
            pollen_desc = {
                "low": "Low pollen season",
                "moderate": "Moderate pollen season",
                "high": "High pollen season - elevated allergen exposure",
                "very_high": "Peak pollen season - high allergen exposure",
            }.get(pollen_level, "Unknown pollen level")

            return (
                f"## Seasonal Health Context\n"
                f"Pollen: {pollen_desc}\n"
                f"Mold risk: {mold_risk}\n"
                f"Indoor heating: {heating_status}"
            )
        else:
            return (
                f"Pollen: {pollen_level} | Mold: {mold_risk.split(' ')[0].lower()} "
                f"| Heating: {heating_status.split(' ')[0].lower()}"
            )

    def _assess_mold_risk(self, humidity: float, temperature: float) -> str:
        """Assess mold risk based on humidity and temperature."""
        if humidity >= 80 and 10 <= temperature <= 30:
            return "High - conditions favor mold growth (high humidity + mild temps)"
        elif humidity >= 70 and 10 <= temperature <= 30:
            return "Elevated - moderate mold growth conditions"
        elif humidity >= 60:
            return "Moderate - some mold risk"
        else:
            return "Low - conditions not favorable for mold"

    def _assess_heating_status(self, temperature: float, month: int, hemisphere: str) -> str:
        """Assess whether indoor heating is likely active."""
        # Winter months by hemisphere
        if hemisphere == "northern":
            heating_months = [10, 11, 12, 1, 2, 3]
        else:
            heating_months = [4, 5, 6, 7, 8, 9]

        if month in heating_months and temperature < 15:
            return "Likely active - may dry indoor air and irritate sinuses"
        elif month in heating_months:
            return "Possibly active - monitor indoor humidity"
        else:
            return "Unlikely - not heating season"

    def _format_hourly_forecast(self, forecasts: List[Any]) -> str:
        """Format hourly forecast data."""
        if not forecasts:
            return ""

        start_time = forecasts[0].target_time.strftime("%H:%M")
        end_time = forecasts[-1].target_time.strftime("%H:%M")

        if self.high_token_budget:
            # Determine downsampling rate based on window size
            num_hours = len(forecasts)
            if num_hours <= 6:
                step = 1  # Show all hours
            elif num_hours <= 12:
                step = 2  # Every 2nd hour
            elif num_hours <= 24:
                step = 3  # Every 3rd hour
            elif num_hours <= 48:
                step = 6  # Every 6th hour
            else:  # Up to 72 hours
                step = 8  # Every 8th hour

            # Downsample forecasts, always include first and last
            sampled = forecasts[::step]
            if forecasts[-1] not in sampled:
                sampled.append(forecasts[-1])

            # Format time span description
            hours_span = num_hours
            if hours_span <= 24:
                span_desc = f"{hours_span}h"
            else:
                days = hours_span // 24
                remaining_hours = hours_span % 24
                if remaining_hours > 0:
                    span_desc = f"{days}d {remaining_hours}h"
                else:
                    span_desc = f"{days}d"

            step_desc = f", every {step}h" if step > 1 else ""

            # Full hourly table
            lines = [f"## Forecast ({start_time}-{end_time} UTC, {span_desc}{step_desc})"]
            lines.append("Time  | Temp   | Pressure  | Humidity | Precip | Cloud")
            lines.append("------|--------|-----------|----------|--------|------")

            for fc in sampled:
                time_str = fc.target_time.strftime("%d %H:%M") if num_hours > 24 else fc.target_time.strftime("%H:%M")
                temp = f"{fc.temperature:.1f}°C"
                pressure = f"{fc.pressure:.1f}hPa"
                humidity = f"{fc.humidity:.0f}%"
                precip = f"{fc.precipitation:.1f}mm"
                cloud = f"{fc.cloud_cover:.0f}%"
                lines.append(f"{time_str} | {temp:>6} | {pressure:>9} | {humidity:>8} | {precip:>6} | {cloud:>5}")

            return "\n".join(lines)
        else:
            # Compact summary
            num_hours = len(forecasts)
            temps = [f.temperature for f in forecasts]
            pressures = [f.pressure for f in forecasts]
            humidities = [f.humidity for f in forecasts]
            precip_total = sum(f.precipitation for f in forecasts)

            # Format time span description
            if num_hours <= 24:
                span_desc = f"{start_time}-{end_time}"
            else:
                start_dt = forecasts[0].target_time
                end_dt = forecasts[-1].target_time
                days = num_hours // 24
                remaining_hours = num_hours % 24
                if remaining_hours > 0:
                    span_desc = (
                        f"{start_dt.strftime('%d %H:%M')}-{end_dt.strftime('%d %H:%M')} ({days}d {remaining_hours}h)"
                    )
                else:
                    span_desc = f"{start_dt.strftime('%d %H:%M')}-{end_dt.strftime('%d %H:%M')} ({days}d)"

            return (
                f"Forecast ({span_desc}): "
                f"Temp {min(temps):.1f}-{max(temps):.1f}°C, "
                f"Pressure {min(pressures):.1f}-{max(pressures):.1f}hPa, "
                f"Humidity {min(humidities):.0f}-{max(humidities):.0f}%, "
                f"Precip {precip_total:.1f}mm"
            )

    def _format_weather_changes(
        self,
        forecasts: List[Any],
        previous_forecasts: List[Any],
    ) -> str:
        """Format weather changes from previous period."""
        if not forecasts or not previous_forecasts:
            return ""

        # Calculate averages
        avg_temp = np.mean([f.temperature for f in forecasts])
        avg_prev_temp = np.mean([f.temperature for f in previous_forecasts])
        temp_change = avg_temp - avg_prev_temp

        avg_pressure = np.mean([f.pressure for f in forecasts])
        avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
        pressure_change = avg_pressure - avg_prev_pressure

        avg_humidity = np.mean([f.humidity for f in forecasts])
        avg_prev_humidity = np.mean([f.humidity for f in previous_forecasts])
        humidity_change = avg_humidity - avg_prev_humidity

        # Determine significance
        def describe_change(value: float, threshold: float, unit: str, name: str) -> str:
            direction = "+" if value > 0 else ""
            magnitude = abs(value)

            if magnitude >= threshold * 2:
                significance = " - significant change"
            elif magnitude >= threshold:
                significance = " - notable"
            else:
                significance = ""

            return f"{name}: {direction}{value:.1f}{unit}{significance}"

        if self.high_token_budget:
            lines = ["## Weather Changes (vs previous 6 hours)"]
            lines.append(
                f"Temperature: {temp_change:+.1f}°C ({avg_prev_temp:.1f}°C → {avg_temp:.1f}°C)"
                + (
                    " - significant warming"
                    if temp_change >= 5
                    else " - significant cooling" if temp_change <= -5 else ""
                )
            )
            lines.append(
                f"Pressure: {pressure_change:+.1f}hPa ({avg_prev_pressure:.1f} → {avg_pressure:.1f}hPa)"
                + (" - notable drop" if pressure_change <= -5 else " - notable rise" if pressure_change >= 5 else "")
            )
            lines.append(f"Humidity: {humidity_change:+.0f}% ({avg_prev_humidity:.0f}% → {avg_humidity:.0f}%)")
            return "\n".join(lines)
        else:
            parts = []
            parts.append(f"Temp {temp_change:+.1f}°C")

            pressure_note = ""
            if pressure_change <= -5:
                pressure_note = " (dropping)"
            elif pressure_change >= 5:
                pressure_note = " (rising)"
            parts.append(f"Pressure {pressure_change:+.1f}hPa{pressure_note}")

            parts.append(f"Humidity {humidity_change:+.0f}%")

            return f"Changes (vs 6h ago): {', '.join(parts)}"

    def _format_window_stability(self, forecasts: List[Any]) -> str:
        """Format stability metrics within the forecast window."""
        if not forecasts or len(forecasts) < 2:
            return ""

        # Calculate max hourly changes
        temp_deltas = [abs(forecasts[i + 1].temperature - forecasts[i].temperature) for i in range(len(forecasts) - 1)]
        pressure_deltas = [abs(forecasts[i + 1].pressure - forecasts[i].pressure) for i in range(len(forecasts) - 1)]

        max_temp_change = max(temp_deltas) if temp_deltas else 0
        max_pressure_change = max(pressure_deltas) if pressure_deltas else 0

        # Determine overall trend
        temp_trend = forecasts[-1].temperature - forecasts[0].temperature
        pressure_trend = forecasts[-1].pressure - forecasts[0].pressure

        def trend_word(value: float) -> str:
            if value > 0.5:
                return "rising"
            elif value < -0.5:
                return "falling"
            else:
                return "stable"

        temp_stability = "stable" if max_temp_change < 1.5 else "variable"
        pressure_stability = "stable" if max_pressure_change < 2 else "variable"

        if self.high_token_budget:
            lines = ["## Stability Within Forecast Window"]
            lines.append(f"Max hourly temp change: {max_temp_change:.1f}°C ({temp_stability})")
            lines.append(f"Max hourly pressure change: {max_pressure_change:.1f}hPa ({pressure_stability})")
            lines.append(f"Overall trend: Temperature {trend_word(temp_trend)}, pressure {trend_word(pressure_trend)}")
            return "\n".join(lines)
        else:
            return (
                f"Window stability: Δ{max_temp_change:.1f}°C/hr temp, Δ{max_pressure_change:.1f}hPa/hr pressure "
                f"({temp_stability})"
            )

    def _format_user_sensitivity(self, user_profile: Dict[str, Any]) -> str:
        """Format user sensitivity profile in natural language."""
        if not user_profile:
            return ""

        # Collect sensitivities
        sensitivity_map = {
            "sensitivity_pressure": ("barometric pressure", "pressure changes"),
            "sensitivity_temperature": ("temperature", "temperature changes"),
            "sensitivity_humidity": ("humidity", "humidity levels"),
            "sensitivity_precipitation": ("precipitation", "rain/precipitation"),
            "sensitivity_cloud_cover": ("cloud cover", "overcast conditions"),
        }

        high_sensitivities = []
        moderate_sensitivities = []

        for key, (name, description) in sensitivity_map.items():
            value = user_profile.get(key, 1.0)
            if value >= 1.5:
                high_sensitivities.append(name)
            elif value >= 1.2:
                moderate_sensitivities.append(name)

        overall = user_profile.get("sensitivity_overall", 1.0)

        if self.high_token_budget:
            lines = ["## User Health Profile"]

            if overall > 1.2:
                lines.append("This user has elevated overall sensitivity to weather changes.")
            elif overall < 0.8:
                lines.append("This user has lower than average sensitivity to weather changes.")

            if high_sensitivities:
                lines.append(f"High sensitivity to: {', '.join(high_sensitivities)}")
            if moderate_sensitivities:
                lines.append(f"Moderate sensitivity to: {', '.join(moderate_sensitivities)}")

            if not high_sensitivities and not moderate_sensitivities:
                lines.append("No specific elevated sensitivities reported.")

            return "\n".join(lines)
        else:
            parts = []
            if high_sensitivities:
                parts.append(f"High: {', '.join(high_sensitivities)}")
            if moderate_sensitivities:
                parts.append(f"Moderate: {', '.join(moderate_sensitivities)}")

            if parts:
                return f"User sensitivity: {'; '.join(parts)}"
            else:
                return "User sensitivity: Normal"

    def _format_historical_predictions(
        self,
        predictions: List[Any],
        location: Any,
        condition_type: str,
    ) -> str:
        """Format historical predictions with their weather context."""
        if not predictions:
            return ""

        # Limit based on token budget
        max_predictions = 5 if self.high_token_budget else 2
        predictions = list(predictions)[:max_predictions]

        if not predictions:
            return ""

        if self.high_token_budget:
            lines = ["## Recent Predictions with Weather Context"]
            lines.append("These show how similar conditions were previously assessed:")
            lines.append("")

            for pred in predictions:
                # Get weather data for this prediction's time window
                weather_context = self._get_prediction_weather_context(pred, location)

                time_ago = self._format_time_ago(pred.prediction_time)
                pred_time = pred.prediction_time.strftime("%a %H:%M")

                lines.append(f"{time_ago} ({pred_time}):")
                lines.append(f"  Weather: {weather_context}")
                lines.append(f"  Prediction: {pred.probability}")
                lines.append("")

            return "\n".join(lines).rstrip()
        else:
            # Compact format for low token budget
            parts = []
            for pred in predictions:
                weather_context = self._get_prediction_weather_context(pred, location, compact=True)
                time_ago = self._format_time_ago(pred.prediction_time, compact=True)
                parts.append(f"{time_ago} {weather_context} → {pred.probability}")

            return f"Recent: {' | '.join(parts)}"

    def _get_prediction_weather_context(
        self,
        prediction: Any,
        location: Any,
        compact: bool = False,
    ) -> str:
        """Get weather context for a historical prediction."""
        from .models import WeatherForecast

        try:
            # Get forecasts from the prediction's time window
            start_time = prediction.target_time_start
            end_time = prediction.target_time_end

            forecasts = list(
                WeatherForecast.objects.filter(
                    location=location,
                    target_time__gte=start_time,
                    target_time__lte=end_time,
                ).order_by("target_time")
            )

            # Get previous forecasts for comparison
            previous_forecasts = list(
                WeatherForecast.objects.filter(
                    location=location,
                    target_time__lt=start_time,
                    target_time__gte=start_time - timedelta(hours=6),
                ).order_by("-target_time")
            )

            if not forecasts:
                return "No weather data available"

            avg_temp = np.mean([f.temperature for f in forecasts])
            avg_pressure = np.mean([f.pressure for f in forecasts])
            avg_humidity = np.mean([f.humidity for f in forecasts])

            # Calculate changes if we have previous data
            if previous_forecasts:
                avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
                pressure_change = avg_pressure - avg_prev_pressure
            else:
                pressure_change = 0

            if compact:
                if abs(pressure_change) >= 3:
                    return f"Δ{pressure_change:+.0f}hPa, {avg_humidity:.0f}%"
                else:
                    return f"stable, {avg_humidity:.0f}%"
            else:
                parts = []
                if abs(pressure_change) >= 1:
                    parts.append(f"Pressure Δ{pressure_change:+.1f}hPa ({avg_prev_pressure:.0f}→{avg_pressure:.0f})")
                else:
                    parts.append(f"Pressure stable at {avg_pressure:.0f}hPa")
                parts.append(f"Temp {avg_temp:.1f}°C")
                parts.append(f"Humidity {avg_humidity:.0f}%")
                return ", ".join(parts)

        except Exception as e:
            logger.warning(f"Failed to get weather context for prediction: {e}")
            return "Weather data unavailable"

    def _format_time_ago(self, dt: datetime, compact: bool = False) -> str:
        """Format a datetime as time ago string."""
        now = timezone.now()
        diff = now - dt
        hours = diff.total_seconds() / 3600

        if compact:
            if hours < 1:
                return f"{int(diff.total_seconds() / 60)}m ago"
            elif hours < 24:
                return f"{int(hours)}h ago"
            else:
                return f"{int(hours / 24)}d ago"
        else:
            if hours < 1:
                return f"{int(diff.total_seconds() / 60)} minutes ago"
            elif hours < 24:
                return f"{int(hours)} hours ago"
            else:
                days = int(hours / 24)
                return f"{days} day{'s' if days > 1 else ''} ago"

    def _get_season(self, dt: datetime, latitude: float) -> str:
        """Determine season based on date and hemisphere."""
        month = dt.month

        # Northern hemisphere seasons
        if month in [12, 1, 2]:
            northern_season = "winter"
        elif month in [3, 4, 5]:
            northern_season = "spring"
        elif month in [6, 7, 8]:
            northern_season = "summer"
        else:
            northern_season = "fall"

        # Flip for southern hemisphere
        if latitude < 0:
            season_map = {
                "winter": "summer",
                "summer": "winter",
                "spring": "fall",
                "fall": "spring",
            }
            return season_map[northern_season]

        return northern_season

    def _get_expected_diurnal_range(self, latitude: float, season: str) -> Tuple[float, float]:
        """Get expected diurnal temperature range for location and season."""
        abs_lat = abs(latitude)

        for (lat_min, lat_max), seasons in self.DIURNAL_RANGES.items():
            if lat_min <= abs_lat < lat_max:
                return seasons.get(season, (6, 12))

        # Default fallback
        return (6, 12)
