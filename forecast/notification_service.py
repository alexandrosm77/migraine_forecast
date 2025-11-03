from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.utils import translation
import logging
from datetime import timedelta

from .models import MigrainePrediction, SinusitisPrediction, Location, NotificationLog
from .prediction_service import MigrainePredictionService
from .prediction_service_sinusitis import SinusitisPredictionService
from .weather_service import WeatherService
from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, set_tag

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Service for sending email notifications about migraine and sinusitis predictions.
    """

    def __init__(self):
        """Initialize the notification service."""
        self.prediction_service = MigrainePredictionService()
        self.sinusitis_prediction_service = SinusitisPredictionService()
        self.weather_service = WeatherService()

    def _get_user_language(self, user):
        """
        Get the user's preferred language.

        Args:
            user: User object

        Returns:
            str: Language code (e.g., 'en', 'el') or None
        """
        try:
            return user.health_profile.language
        except Exception:
            return None

    def _should_send_notification(self, user, severity_level, notification_type="general"):
        """
        Check if a notification should be sent based on all user preferences.

        Args:
            user: User object
            severity_level: "LOW", "MEDIUM", or "HIGH"
            notification_type: "migraine", "sinusitis", or "general"

        Returns:
            tuple: (should_send: bool, reason: str)
        """
        try:
            profile = user.health_profile
        except Exception:
            # No profile, use defaults - allow notification
            return True, "No profile found, using defaults"

        # Check if email notifications are enabled
        if not profile.email_notifications_enabled:
            return False, "Email notifications disabled"

        # Check notification mode - if digest mode, don't send immediate notifications
        if profile.notification_mode == "DIGEST":
            return False, "User is in digest mode"

        # Check severity threshold
        if not profile.should_send_notification(severity_level):
            return False, f"Severity {severity_level} below threshold {profile.notification_severity_threshold}"

        # Check quiet hours
        if profile.is_in_quiet_hours():
            return False, "Currently in quiet hours"

        # Check daily limits
        now = timezone.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check overall daily limit
        if profile.daily_notification_limit > 0:
            today_count = NotificationLog.objects.filter(
                user=user, status="sent", sent_at__gte=start_of_day, sent_at__lt=start_of_day + timedelta(days=1)
            ).count()

            if today_count >= profile.daily_notification_limit:
                return False, f"Daily limit reached ({today_count}/{profile.daily_notification_limit})"

        # Check per-type limits
        if notification_type == "migraine" and profile.daily_migraine_notification_limit > 0:
            migraine_count = NotificationLog.objects.filter(
                user=user,
                status="sent",
                notification_type="migraine",
                sent_at__gte=start_of_day,
                sent_at__lt=start_of_day + timedelta(days=1),
            ).count()

            if migraine_count >= profile.daily_migraine_notification_limit:
                return (
                    False,
                    f"Migraine daily limit reached ({migraine_count}/{profile.daily_migraine_notification_limit})",
                )

        if notification_type == "sinusitis" and profile.daily_sinusitis_notification_limit > 0:
            sinusitis_count = NotificationLog.objects.filter(
                user=user,
                status="sent",
                notification_type="sinusitis",
                sent_at__gte=start_of_day,
                sent_at__lt=start_of_day + timedelta(days=1),
            ).count()

            if sinusitis_count >= profile.daily_sinusitis_notification_limit:
                return (
                    False,
                    f"Sinusitis daily limit reached ({sinusitis_count}/{profile.daily_sinusitis_notification_limit})",
                )

        # Check notification frequency using optimized timestamp fields
        if profile.last_notification_sent_at:
            time_since_last = (now - profile.last_notification_sent_at).total_seconds() / 3600
            if time_since_last < profile.notification_frequency_hours:
                return (
                    False,
                    f"Too soon since last notification ({time_since_last:.1f}h < {profile.notification_frequency_hours}h)",  # noqa: E501
                )

        return True, "All checks passed"

    def _create_notification_log(self, user, notification_type, migraine_preds=None, sinusitis_preds=None):
        """
        Create a notification log entry.

        Args:
            user: User object
            notification_type: Type of notification
            migraine_preds: List of MigrainePrediction objects
            sinusitis_preds: List of SinusitisPrediction objects

        Returns:
            NotificationLog object
        """
        migraine_preds = migraine_preds or []
        sinusitis_preds = sinusitis_preds or []

        # Determine highest severity
        all_severities = [p.probability for p in migraine_preds + sinusitis_preds]
        severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        highest_severity = max(all_severities, key=lambda x: severity_order.get(x, 0)) if all_severities else "LOW"

        # Count unique locations
        all_locations = set([p.location for p in migraine_preds + sinusitis_preds])

        log = NotificationLog.objects.create(
            user=user,
            notification_type=notification_type,
            channel="email",
            status="pending",
            recipient=user.email,
            severity_level=highest_severity,
            locations_count=len(all_locations),
            predictions_count=len(migraine_preds) + len(sinusitis_preds),
            scheduled_time=timezone.now(),
        )

        # Add predictions to the log
        if migraine_preds:
            log.migraine_predictions.set(migraine_preds)
        if sinusitis_preds:
            log.sinusitis_predictions.set(sinusitis_preds)

        return log

    def _update_last_notification_timestamp(self, user, notification_type):
        """
        Update the last notification timestamp for a user.

        Args:
            user: User object
            notification_type: "migraine", "sinusitis", or "combined"
        """
        try:
            profile = user.health_profile
            now = timezone.now()

            profile.last_notification_sent_at = now

            if notification_type in ["migraine", "combined"]:
                profile.last_migraine_notification_sent_at = now

            if notification_type in ["sinusitis", "combined"]:
                profile.last_sinusitis_notification_sent_at = now

            profile.save()
        except Exception as e:
            logger.warning(f"Could not update last notification timestamp for user {user.username}: {e}")

    def send_migraine_alert(self, prediction):
        """
        Send migraine alert email for a specific prediction.

        Args:
            prediction (MigrainePrediction): The prediction model instance

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        user = prediction.user
        location = prediction.location
        forecast = prediction.forecast
        probability_level = prediction.probability
        weather_factors = prediction.weather_factors

        # Add breadcrumb for email sending
        add_breadcrumb(
            category="email",
            message="Sending migraine alert email",
            level="info",
            data={"user": user.username, "location": str(location), "probability": probability_level},
        )

        set_tag("email_type", "migraine_alert")
        set_tag("risk_level", probability_level)

        # Create notification log
        notification_log = self._create_notification_log(user, "migraine", migraine_preds=[prediction])

        # Skip if user has no email
        if not user.email:
            logger.warning(f"Cannot send migraine alert to user {user.username}: No email address")
            notification_log.mark_skipped("No email address")
            capture_message(f"Cannot send migraine alert: User {user.username} has no email address", level="warning")
            return False

        # Check if notification should be sent based on all preferences
        should_send, reason = self._should_send_notification(user, probability_level, "migraine")
        if not should_send:
            logger.info(f"Skipping migraine alert for user {user.username}: {reason}")
            notification_log.mark_skipped(reason)
            return False

        # Get additional context for human-friendly explanations
        detailed_factors = self._get_detailed_weather_factors(prediction)

        # Prepare email context
        context = {
            "user": user,
            "location": location,
            "prediction": prediction,
            "forecast": forecast,
            "start_time": prediction.target_time_start,
            "end_time": prediction.target_time_end,
            "temperature": forecast.temperature,
            "humidity": forecast.humidity,
            "pressure": forecast.pressure,
            "precipitation": forecast.precipitation,
            "cloud_cover": forecast.cloud_cover,
            "probability_level": probability_level,
            "weather_factors": weather_factors,
            "detailed_factors": detailed_factors,
            "llm_analysis_text": (weather_factors or {}).get("llm_analysis_text"),
            "llm_prevention_tips": (weather_factors or {}).get("llm_prevention_tips") or [],
        }

        # Activate user's language for email rendering
        user_language = self._get_user_language(user)
        if user_language:
            translation.activate(user_language)

        try:
            # Render email content
            factor_count = detailed_factors.get("contributing_factors_count", 0)
            if factor_count > 0:
                factor_word = "Factor" if factor_count == 1 else "Factors"
                subject = (
                    f"{probability_level} Migraine Alert for {location.city} - " f"{factor_count} Weather {factor_word}"
                )
            else:
                subject = f"{probability_level} Migraine Alert for {location.city}"
            html_message = render_to_string("forecast/email/migraine_alert.html", context)
            plain_message = strip_tags(html_message)
        finally:
            # Deactivate translation to avoid affecting other parts of the system
            translation.deactivate()

        # Update notification log with subject
        notification_log.subject = subject
        notification_log.save()

        try:
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Sent migraine alert email to {user.email}")

            add_breadcrumb(
                category="email",
                message="Migraine alert email sent successfully",
                level="info",
                data={"recipient": user.email},
            )

            # Mark notification as sent and update timestamp
            notification_log.mark_sent()
            self._update_last_notification_timestamp(user, "migraine")

            return True
        except Exception as e:
            logger.error(f"Failed to send migraine alert email: {e}")

            # Mark notification as failed
            notification_log.mark_failed(str(e))

            # Capture exception with context
            set_context(
                "email_send_error",
                {
                    "email_type": "migraine_alert",
                    "recipient": user.email,
                    "user": user.username,
                    "location": str(location),
                    "probability": probability_level,
                    "subject": subject,
                    "smtp_host": settings.EMAIL_HOST,
                    "smtp_port": settings.EMAIL_PORT,
                },
            )
            capture_exception(e)

            return False

    def send_combined_alert(self, migraine_predictions=None, sinusitis_predictions=None):
        """
        Send a combined alert email for migraine and/or sinusitis predictions across multiple locations.

        Args:
            migraine_predictions (list, optional): List of MigrainePrediction instances
            sinusitis_predictions (list, optional): List of SinusitisPrediction instances

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        # Convert single predictions to lists for backward compatibility
        if migraine_predictions is not None and not isinstance(migraine_predictions, list):
            migraine_predictions = [migraine_predictions]
        if sinusitis_predictions is not None and not isinstance(sinusitis_predictions, list):
            sinusitis_predictions = [sinusitis_predictions]

        # At least one prediction must be provided
        if not migraine_predictions and not sinusitis_predictions:
            logger.error("send_combined_alert called with no predictions")
            capture_message("send_combined_alert called with no predictions", level="error")
            return False

        # Get user from whichever prediction list is available
        all_predictions = (migraine_predictions or []) + (sinusitis_predictions or [])
        if not all_predictions:
            logger.error("send_combined_alert called with empty prediction lists")
            capture_message("send_combined_alert called with empty prediction lists", level="error")
            return False

        user = all_predictions[0].user

        # Create notification log
        notification_log = self._create_notification_log(
            user, "combined", migraine_preds=migraine_predictions, sinusitis_preds=sinusitis_predictions
        )

        # Add breadcrumb for combined email
        add_breadcrumb(
            category="email",
            message="Sending combined alert email",
            level="info",
            data={
                "user": user.username,
                "migraine_count": len(migraine_predictions) if migraine_predictions else 0,
                "sinusitis_count": len(sinusitis_predictions) if sinusitis_predictions else 0,
            },
        )

        set_tag("email_type", "combined_alert")

        # Skip if user has no email
        if not user.email:
            logger.warning(f"Cannot send combined alert to user {user.username}: No email address")
            notification_log.mark_skipped("No email address")
            capture_message(f"Cannot send combined alert: User {user.username} has no email address", level="warning")
            return False

        # Determine highest severity for notification check
        all_severities = [p.probability for p in all_predictions]
        severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        highest_severity = max(all_severities, key=lambda x: severity_order.get(x, 0))

        # Check if notification should be sent
        should_send, reason = self._should_send_notification(user, highest_severity, "general")
        if not should_send:
            logger.info(f"Skipping combined alert for user {user.username}: {reason}")
            notification_log.mark_skipped(reason)
            return False

        # Prepare location-based predictions
        location_data = []

        # Group predictions by location
        from collections import defaultdict

        location_predictions = defaultdict(lambda: {"migraine": None, "sinusitis": None})

        if migraine_predictions:
            for pred in migraine_predictions:
                location_predictions[pred.location.id]["migraine"] = pred
                location_predictions[pred.location.id]["location"] = pred.location

        if sinusitis_predictions:
            for pred in sinusitis_predictions:
                location_predictions[pred.location.id]["sinusitis"] = pred
                location_predictions[pred.location.id]["location"] = pred.location

        # Build location data for template
        for loc_id, preds in location_predictions.items():
            location = preds["location"]
            migraine_pred = preds["migraine"]
            sinusitis_pred = preds["sinusitis"]

            # Get forecast from whichever prediction is available
            forecast = (migraine_pred or sinusitis_pred).forecast

            loc_data = {
                "location": location,
                "forecast": forecast,
                "start_time": (migraine_pred or sinusitis_pred).target_time_start,
                "end_time": (migraine_pred or sinusitis_pred).target_time_end,
            }

            # Add migraine data if available
            if migraine_pred:
                migraine_detailed_factors = self._get_detailed_weather_factors(migraine_pred)
                migraine_weather_factors = migraine_pred.weather_factors or {}

                loc_data.update(
                    {
                        "migraine_prediction": migraine_pred,
                        "migraine_probability_level": migraine_pred.probability,
                        "migraine_detailed_factors": migraine_detailed_factors,
                        "migraine_llm_analysis_text": migraine_weather_factors.get("llm_analysis_text"),
                        "migraine_llm_prevention_tips": migraine_weather_factors.get("llm_prevention_tips") or [],
                    }
                )

            # Add sinusitis data if available
            if sinusitis_pred:
                sinusitis_detailed_factors = self._get_detailed_sinusitis_factors(sinusitis_pred)
                sinusitis_weather_factors = sinusitis_pred.weather_factors or {}

                loc_data.update(
                    {
                        "sinusitis_prediction": sinusitis_pred,
                        "sinusitis_probability_level": sinusitis_pred.probability,
                        "sinusitis_detailed_factors": sinusitis_detailed_factors,
                        "sinusitis_llm_analysis_text": sinusitis_weather_factors.get("llm_analysis_text"),
                        "sinusitis_llm_prevention_tips": sinusitis_weather_factors.get("llm_prevention_tips") or [],
                    }
                )

            location_data.append(loc_data)

        # Prepare context for email
        # Determine if we have any migraine or sinusitis predictions
        has_migraine = any(loc.get("migraine_prediction") for loc in location_data)
        has_sinusitis = any(loc.get("sinusitis_prediction") for loc in location_data)

        # Get first location with tips for each type
        first_migraine_tips = None
        first_sinusitis_tips = None

        for loc in location_data:
            if not first_migraine_tips and loc.get("migraine_llm_prevention_tips"):
                first_migraine_tips = loc.get("migraine_llm_prevention_tips")
            if not first_sinusitis_tips and loc.get("sinusitis_llm_prevention_tips"):
                first_sinusitis_tips = loc.get("sinusitis_llm_prevention_tips")

        context = {
            "user": user,
            "locations": location_data,
            "location_count": len(location_data),
            "has_migraine": has_migraine,
            "has_sinusitis": has_sinusitis,
            "first_migraine_tips": first_migraine_tips,
            "first_sinusitis_tips": first_sinusitis_tips,
        }

        # Activate user's language for email rendering
        user_language = self._get_user_language(user)
        if user_language:
            translation.activate(user_language)

        try:
            # Build subject line
            location_names = [loc["location"].city for loc in location_data]
            if len(location_names) == 1:
                location_str = location_names[0]
            elif len(location_names) == 2:
                location_str = f"{location_names[0]} & {location_names[1]}"
            else:
                location_str = f"{len(location_names)} locations"

            subject = f"Health Alert for {location_str}"

            # Render email content
            html_message = render_to_string("forecast/email/combined_alert.html", context)
            plain_message = strip_tags(html_message)
        finally:
            # Deactivate translation to avoid affecting other parts of the system
            translation.deactivate()

        # Update notification log with subject
        notification_log.subject = subject
        notification_log.save()

        try:
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(
                f"Sent combined alert email to {user.email} "
                f"({len(migraine_predictions or [])} migraine, {len(sinusitis_predictions or [])} sinusitis "
                f"across {len(location_data)} location(s))"
            )

            add_breadcrumb(
                category="email",
                message="Combined alert email sent successfully",
                level="info",
                data={"recipient": user.email, "location_count": len(location_data)},
            )

            # Mark notification as sent and update timestamp
            notification_log.mark_sent()
            self._update_last_notification_timestamp(user, "combined")

            return True
        except Exception as e:
            logger.error(f"Failed to send combined alert email: {e}")

            # Mark notification as failed
            notification_log.mark_failed(str(e))

            # Capture exception with context
            set_context(
                "email_send_error",
                {
                    "email_type": "combined_alert",
                    "recipient": user.email,
                    "user": user.username,
                    "migraine_count": len(migraine_predictions or []),
                    "sinusitis_count": len(sinusitis_predictions or []),
                    "location_count": len(location_data),
                    "subject": subject,
                    "smtp_host": settings.EMAIL_HOST,
                    "smtp_port": settings.EMAIL_PORT,
                },
            )
            capture_exception(e)

            return False

    def send_test_email(self, user_email):
        """
        Send a test email to verify email configuration.

        Args:
            user_email (str): The recipient email address

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        subject = "Test Email from Migraine Forecast App"
        message = (
            "This is a test email from the Migraine Forecast application. "
            "If you received this, email notifications are working correctly."
        )

        try:
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user_email],
                fail_silently=False,
            )
            logger.info(f"Sent test email to {user_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send test email: {e}")
            return False

    def _get_detailed_weather_factors(self, prediction):
        """
        Get detailed, human-friendly explanations of weather factors contributing to the alert.

        Args:
            prediction (MigrainePrediction): The prediction model instance

        Returns:
            dict: Detailed weather factor information with explanations
        """
        from .prediction_service import MigrainePredictionService

        # Import thresholds for comparison
        thresholds = MigrainePredictionService.THRESHOLDS
        weights = MigrainePredictionService.WEIGHTS
        weather_factors = prediction.weather_factors or {}

        detailed_factors = []

        # Get current and previous weather data for context
        from .models import WeatherForecast
        import numpy as np

        # Get forecasts for the prediction window
        forecasts = WeatherForecast.objects.filter(
            location=prediction.location,
            target_time__gte=prediction.target_time_start,
            target_time__lte=prediction.target_time_end,
        ).order_by("target_time")

        # Get previous forecasts for comparison
        previous_forecasts = WeatherForecast.objects.filter(
            location=prediction.location, target_time__lt=prediction.target_time_start
        ).order_by("-target_time")[:6]

        if not forecasts:
            return {"factors": detailed_factors, "total_score": 0}

        # Temperature change analysis
        if weather_factors.get("temperature_change", 0) > 0 and previous_forecasts:
            avg_prev_temp = np.mean([f.temperature for f in previous_forecasts])
            avg_forecast_temp = np.mean([f.temperature for f in forecasts])
            temp_change = abs(avg_forecast_temp - avg_prev_temp)

            if temp_change >= thresholds["temperature_change"]:
                direction = "increase" if avg_forecast_temp > avg_prev_temp else "decrease"
                detailed_factors.append(
                    {
                        "name": "Temperature Change",
                        "score": weather_factors["temperature_change"],
                        "weight": weights["temperature_change"],
                        "explanation": (
                            f"Temperature will {direction} by {temp_change:.1f}°C "
                            f"(from {avg_prev_temp:.1f}°C to {avg_forecast_temp:.1f}°C). "
                            f"Changes of {thresholds['temperature_change']}°C or more "
                            "can trigger migraines."
                        ),
                        "severity": ("high" if temp_change >= thresholds["temperature_change"] * 2 else "medium"),
                    }
                )

        # Humidity analysis
        if weather_factors.get("humidity_extreme", 0) > 0:
            avg_humidity = np.mean([f.humidity for f in forecasts])

            if avg_humidity >= thresholds["humidity_high"]:
                detailed_factors.append(
                    {
                        "name": "High Humidity",
                        "score": weather_factors["humidity_extreme"],
                        "weight": weights["humidity_extreme"],
                        "explanation": (
                            f"Humidity will be {avg_humidity:.1f}%, which is above the "
                            f"{thresholds['humidity_high']}% threshold. "
                            "High humidity can increase migraine risk."
                        ),
                        "severity": "high" if avg_humidity >= 85 else "medium",
                    }
                )
            elif avg_humidity <= thresholds["humidity_low"]:
                detailed_factors.append(
                    {
                        "name": "Low Humidity",
                        "score": weather_factors["humidity_extreme"],
                        "weight": weights["humidity_extreme"],
                        "explanation": (
                            f"Humidity will be {avg_humidity:.1f}%, which is below the "
                            f"{thresholds['humidity_low']}% threshold. "
                            "Very dry air can trigger migraines."
                        ),
                        "severity": "high" if avg_humidity <= 20 else "medium",
                    }
                )

        # Pressure change analysis
        if weather_factors.get("pressure_change", 0) > 0 and previous_forecasts:
            avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
            avg_forecast_pressure = np.mean([f.pressure for f in forecasts])
            pressure_change = abs(avg_forecast_pressure - avg_prev_pressure)

            if pressure_change >= thresholds["pressure_change"]:
                direction = "increase" if avg_forecast_pressure > avg_prev_pressure else "drop"
                detailed_factors.append(
                    {
                        "name": "Barometric Pressure Change",
                        "score": weather_factors["pressure_change"],
                        "weight": weights["pressure_change"],
                        "explanation": (
                            f"Barometric pressure will {direction} by {pressure_change:.1f} hPa "
                            f"(from {avg_prev_pressure:.1f} to {avg_forecast_pressure:.1f} hPa). "
                            f"Pressure changes of {thresholds['pressure_change']} hPa or more "
                            "are strong migraine triggers."
                        ),
                        "severity": ("high" if pressure_change >= thresholds["pressure_change"] * 2 else "medium"),
                    }
                )

        # Low pressure analysis
        if weather_factors.get("pressure_low", 0) > 0:
            avg_pressure = np.mean([f.pressure for f in forecasts])
            detailed_factors.append(
                {
                    "name": "Low Barometric Pressure",
                    "score": weather_factors["pressure_low"],
                    "weight": weights["pressure_low"],
                    "explanation": (
                        f"Barometric pressure will be {avg_pressure:.1f} hPa, "
                        f"which is below the {thresholds['pressure_low']} hPa threshold. "
                        "Low pressure systems are associated with increased migraine frequency."
                    ),
                    "severity": "high" if avg_pressure <= 995 else "medium",
                }
            )

        # Precipitation analysis
        if weather_factors.get("precipitation", 0) > 0:
            max_precipitation = max([f.precipitation for f in forecasts], default=0)
            detailed_factors.append(
                {
                    "name": "Heavy Precipitation",
                    "score": weather_factors["precipitation"],
                    "weight": weights["precipitation"],
                    "explanation": (
                        f"Expected precipitation of {max_precipitation:.1f} mm, "
                        f"which exceeds the {thresholds['precipitation_high']} mm threshold. "
                        "Heavy rain or storms can trigger migraines."
                    ),
                    "severity": "high" if max_precipitation >= 10 else "medium",
                }
            )

        # Cloud cover analysis
        if weather_factors.get("cloud_cover", 0) > 0:
            avg_cloud_cover = np.mean([f.cloud_cover for f in forecasts])
            detailed_factors.append(
                {
                    "name": "Heavy Cloud Cover",
                    "score": weather_factors["cloud_cover"],
                    "weight": weights["cloud_cover"],
                    "explanation": (
                        f"Cloud cover will be {avg_cloud_cover:.1f}%, which is above the "
                        f"{thresholds['cloud_cover_high']}% threshold. "
                        "Overcast conditions can affect some migraine sufferers."
                    ),
                    "severity": "medium",
                }
            )

        # Calculate total weighted score
        total_score = sum(factor["score"] * factor["weight"] for factor in detailed_factors)

        # Sort factors by their weighted contribution (score * weight)
        detailed_factors.sort(key=lambda x: x["score"] * x["weight"], reverse=True)

        return {
            "factors": detailed_factors,
            "total_score": round(total_score, 2),
            "contributing_factors_count": len(detailed_factors),
        }

    def send_sinusitis_alert(self, prediction):
        """
        Send sinusitis alert email for a specific prediction.

        Args:
            prediction (SinusitisPrediction): The prediction model instance

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        user = prediction.user
        location = prediction.location
        forecast = prediction.forecast
        probability_level = prediction.probability
        weather_factors = prediction.weather_factors

        # Skip if user has no email
        if not user.email:
            logger.warning(f"Cannot send sinusitis alert to user {user.username}: No email address")
            return False

        # Check if user has email notifications enabled
        try:
            if hasattr(user, "health_profile") and not user.health_profile.email_notifications_enabled:
                logger.info(f"Skipping sinusitis alert for user {user.username}: Email notifications disabled")
                return False
        except Exception as e:
            logger.warning(f"Could not check email notification preference for user {user.username}: {e}")
            # Continue with sending email if we can't determine preference

        # Get additional context for human-friendly explanations
        detailed_factors = self._get_detailed_sinusitis_factors(prediction)

        # Prepare email context
        context = {
            "user": user,
            "location": location,
            "prediction": prediction,
            "forecast": forecast,
            "start_time": prediction.target_time_start,
            "end_time": prediction.target_time_end,
            "temperature": forecast.temperature,
            "humidity": forecast.humidity,
            "pressure": forecast.pressure,
            "precipitation": forecast.precipitation,
            "cloud_cover": forecast.cloud_cover,
            "probability_level": probability_level,
            "weather_factors": weather_factors,
            "detailed_factors": detailed_factors,
            "llm_analysis_text": (weather_factors or {}).get("llm_analysis_text"),
            "llm_prevention_tips": (weather_factors or {}).get("llm_prevention_tips") or [],
        }

        # Activate user's language for email rendering
        user_language = self._get_user_language(user)
        if user_language:
            translation.activate(user_language)

        try:
            # Render email content
            factor_count = detailed_factors.get("contributing_factors_count", 0)
            if factor_count > 0:
                factor_word = "Factor" if factor_count == 1 else "Factors"
                subject = (
                    f"{probability_level} Sinusitis Alert for {location.city} - "
                    f"{factor_count} Weather {factor_word}"
                )
            else:
                subject = f"{probability_level} Sinusitis Alert for {location.city}"
            html_message = render_to_string("forecast/email/sinusitis_alert.html", context)
            plain_message = strip_tags(html_message)
        finally:
            # Deactivate translation to avoid affecting other parts of the system
            translation.deactivate()

        try:
            # Send email
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Sent sinusitis alert email to {user.email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send sinusitis alert email: {e}")
            return False

    def check_and_send_combined_notifications(self, migraine_predictions: dict, sinusitis_predictions: dict):
        """
        Check both migraine and sinusitis predictions and send combined notifications.

        This method groups predictions by user across ALL locations and sends:
        - A single email per user containing all their predictions from all locations
        - Combines both migraine and sinusitis predictions in the same email

        Args:
            migraine_predictions (dict): Dictionary mapping location IDs to migraine prediction data
            sinusitis_predictions (dict): Dictionary mapping location IDs to sinusitis prediction data

        Returns:
            int: Number of notifications sent (one per user)
        """
        from django.utils import timezone
        from collections import defaultdict

        # Group predictions by user
        user_predictions = defaultdict(lambda: {"migraine": [], "sinusitis": []})

        # Get all locations with associated users
        locations = Location.objects.select_related("user").all()

        # Track which users we've already processed to avoid duplicate checks
        processed_users = set()

        for location in locations:
            # Skip if no user associated
            if not location.user:
                continue

            user = location.user

            # Skip if we've already processed this user (since we now send one email per user)
            if user.id in processed_users:
                continue

            # Mark this user as processed
            processed_users.add(user.id)

            # Check user-level daily notification limit and frequency preference
            try:
                user_profile = user.health_profile
                limit = int(user_profile.daily_notification_limit)
                notification_frequency_hours = int(user_profile.notification_frequency_hours)
            except Exception:
                limit = 1  # Default to 1 if no profile exists
                notification_frequency_hours = 3  # Default to 3 hours

            if limit <= 0:
                # Notifications disabled for this user
                logger.debug(f"Notifications disabled for user {user.username} (limit={limit})")
                continue

            # Count notifications sent today for this user (across all locations)
            now = timezone.now()
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)

            # Count unique notification emails sent today (we now send combined emails)
            # We'll count by checking if any prediction was sent today
            migraine_sent_today = MigrainePrediction.objects.filter(
                user=user,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).exists()

            sinusitis_sent_today = SinusitisPrediction.objects.filter(
                user=user,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).exists()

            # If either type was sent today, count it as 1 email sent
            emails_sent_today = 1 if (migraine_sent_today or sinusitis_sent_today) else 0

            if emails_sent_today >= limit:
                # Already reached today's limit for this user
                logger.debug(f"User {user.username} has reached daily limit ({limit})")
                continue

            # Check notification frequency - find the most recent notification sent
            frequency_cutoff = now - timedelta(hours=notification_frequency_hours)

            recent_migraine = (
                MigrainePrediction.objects.filter(
                    user=user,
                    notification_sent=True,
                    prediction_time__gte=frequency_cutoff,
                )
                .order_by("-prediction_time")
                .first()
            )

            recent_sinusitis = (
                SinusitisPrediction.objects.filter(
                    user=user,
                    notification_sent=True,
                    prediction_time__gte=frequency_cutoff,
                )
                .order_by("-prediction_time")
                .first()
            )

            # If either type was sent within the frequency window, skip
            if recent_migraine or recent_sinusitis:
                most_recent_time = None
                if recent_migraine and recent_sinusitis:
                    most_recent_time = max(recent_migraine.prediction_time, recent_sinusitis.prediction_time)
                elif recent_migraine:
                    most_recent_time = recent_migraine.prediction_time
                else:
                    most_recent_time = recent_sinusitis.prediction_time

                hours_since = (now - most_recent_time).total_seconds() / 3600
                logger.debug(
                    f"User {user.username} was notified {hours_since:.1f} hours ago, "
                    f"minimum frequency is {notification_frequency_hours} hours"
                )
                continue

            # Collect predictions for ALL locations for this user
            user_migraine_preds = []
            user_sinusitis_preds = []

            for user_location in user.locations.all():
                # Get predictions for this location
                migraine_data = migraine_predictions.get(user_location.id)
                sinusitis_data = sinusitis_predictions.get(user_location.id)

                # Check migraine prediction
                if migraine_data:
                    try:
                        user_profile = user.health_profile
                        if not user_profile.migraine_predictions_enabled:
                            migraine_data = None
                    except Exception:
                        pass

                    if migraine_data:
                        prob_level = migraine_data.get("probability")
                        pred = migraine_data.get("prediction")
                        if prob_level in ["HIGH", "MEDIUM"] and pred and not pred.notification_sent:
                            user_migraine_preds.append(pred)

                # Check sinusitis prediction
                if sinusitis_data:
                    try:
                        user_profile = user.health_profile
                        if not user_profile.sinusitis_predictions_enabled:
                            sinusitis_data = None
                    except Exception:
                        pass

                    if sinusitis_data:
                        prob_level = sinusitis_data.get("probability")
                        pred = sinusitis_data.get("prediction")
                        if prob_level in ["HIGH", "MEDIUM"] and pred and not pred.notification_sent:
                            user_sinusitis_preds.append(pred)

            # Add to user_predictions if we have any predictions
            if user_migraine_preds or user_sinusitis_preds:
                user_predictions[user.id]["migraine"] = user_migraine_preds
                user_predictions[user.id]["sinusitis"] = user_sinusitis_preds

        # Now send one email per user with all their predictions
        notifications_sent = 0

        for user_id, predictions in user_predictions.items():
            migraine_preds = predictions["migraine"]
            sinusitis_preds = predictions["sinusitis"]

            # Skip if no predictions to send
            if not migraine_preds and not sinusitis_preds:
                continue

            # Get user object
            from django.contrib.auth.models import User

            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                continue

            # Check if user has email notifications enabled
            try:
                if hasattr(user, "health_profile") and not user.health_profile.email_notifications_enabled:
                    logger.info(f"Skipping notifications for user {user.username}: Email notifications disabled")
                    continue
            except Exception as e:
                logger.warning(f"Could not check email notification preference for user {user.username}: {e}")

            # Send combined notification for all locations
            if self.send_combined_alert(migraine_predictions=migraine_preds, sinusitis_predictions=sinusitis_preds):
                # Mark all predictions as sent
                for pred in migraine_preds:
                    pred.notification_sent = True
                    pred.save()
                for pred in sinusitis_preds:
                    pred.notification_sent = True
                    pred.save()

                notifications_sent += 1

                location_count = len(set([p.location for p in migraine_preds + sinusitis_preds]))
                logger.info(
                    f"Sent combined alert to {user.email} covering {location_count} location(s) "
                    f"({len(migraine_preds)} migraine, {len(sinusitis_preds)} sinusitis)"
                )

        logger.info(f"Sent {notifications_sent} combined alert notifications")
        return notifications_sent

    def _get_detailed_sinusitis_factors(self, prediction):
        """
        Get detailed, human-friendly explanations of weather factors contributing to sinusitis alert.

        Args:
            prediction (SinusitisPrediction): The prediction model instance

        Returns:
            dict: Detailed weather factor information with explanations
        """
        from .prediction_service_sinusitis import SinusitisPredictionService

        # Import thresholds for comparison
        thresholds = SinusitisPredictionService.THRESHOLDS
        weights = SinusitisPredictionService.WEIGHTS
        weather_factors = prediction.weather_factors or {}

        detailed_factors = []

        # Get current and previous weather data for context
        from .models import WeatherForecast
        import numpy as np

        # Get forecasts for the prediction window
        forecasts = WeatherForecast.objects.filter(
            location=prediction.location,
            target_time__gte=prediction.target_time_start,
            target_time__lte=prediction.target_time_end,
        ).order_by("target_time")

        # Get previous forecasts for comparison
        previous_forecasts = WeatherForecast.objects.filter(
            location=prediction.location, target_time__lt=prediction.target_time_start
        ).order_by("-target_time")[:6]

        if not forecasts:
            return {"factors": detailed_factors, "total_score": 0}

        # Temperature change analysis
        if weather_factors.get("temperature_change", 0) > 0 and previous_forecasts:
            avg_prev_temp = np.mean([f.temperature for f in previous_forecasts])
            avg_forecast_temp = np.mean([f.temperature for f in forecasts])
            temp_change = abs(avg_forecast_temp - avg_prev_temp)

            if temp_change >= thresholds["temperature_change"]:
                direction = "increase" if avg_forecast_temp > avg_prev_temp else "decrease"
                detailed_factors.append(
                    {
                        "name": "Temperature Change",
                        "score": weather_factors["temperature_change"],
                        "weight": weights["temperature_change"],
                        "explanation": (
                            f"Temperature will {direction} by {temp_change:.1f}°C "
                            f"(from {avg_prev_temp:.1f}°C to {avg_forecast_temp:.1f}°C). "
                            "Rapid temperature changes can irritate sinuses."
                        ),
                        "severity": ("high" if temp_change >= thresholds["temperature_change"] * 1.5 else "medium"),
                    }
                )

        # Humidity analysis
        if weather_factors.get("humidity_extreme", 0) > 0:
            avg_humidity = np.mean([f.humidity for f in forecasts])

            if avg_humidity >= thresholds["humidity_high"]:
                detailed_factors.append(
                    {
                        "name": "High Humidity",
                        "score": weather_factors["humidity_extreme"],
                        "weight": weights["humidity_extreme"],
                        "explanation": (
                            f"Humidity will be {avg_humidity:.1f}%, which is above the "
                            f"{thresholds['humidity_high']}% threshold. "
                            "High humidity promotes mold growth and allergens that can trigger sinusitis."
                        ),
                        "severity": "high" if avg_humidity >= 85 else "medium",
                    }
                )
            elif avg_humidity <= thresholds["humidity_low"]:
                detailed_factors.append(
                    {
                        "name": "Low Humidity",
                        "score": weather_factors["humidity_extreme"],
                        "weight": weights["humidity_extreme"],
                        "explanation": (
                            f"Humidity will be {avg_humidity:.1f}%, which is below the "
                            f"{thresholds['humidity_low']}% threshold. "
                            "Very dry air can dry out and irritate sinus passages."
                        ),
                        "severity": "high" if avg_humidity <= 15 else "medium",
                    }
                )

        # Pressure change analysis
        if weather_factors.get("pressure_change", 0) > 0 and previous_forecasts:
            avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
            avg_forecast_pressure = np.mean([f.pressure for f in forecasts])
            pressure_change = abs(avg_forecast_pressure - avg_prev_pressure)

            if pressure_change >= thresholds["pressure_change"]:
                direction = "increase" if avg_forecast_pressure > avg_prev_pressure else "drop"
                detailed_factors.append(
                    {
                        "name": "Barometric Pressure Change",
                        "score": weather_factors["pressure_change"],
                        "weight": weights["pressure_change"],
                        "explanation": (
                            f"Barometric pressure will {direction} by {pressure_change:.1f} hPa "
                            f"(from {avg_prev_pressure:.1f} to {avg_forecast_pressure:.1f} hPa). "
                            "Pressure changes can affect sinus pressure and cause discomfort."
                        ),
                        "severity": ("high" if pressure_change >= thresholds["pressure_change"] * 1.5 else "medium"),
                    }
                )

        # Low pressure analysis
        if weather_factors.get("pressure_low", 0) > 0:
            avg_pressure = np.mean([f.pressure for f in forecasts])
            detailed_factors.append(
                {
                    "name": "Low Barometric Pressure",
                    "score": weather_factors["pressure_low"],
                    "weight": weights["pressure_low"],
                    "explanation": (
                        f"Barometric pressure will be {avg_pressure:.1f} hPa, "
                        f"which is below the {thresholds['pressure_low']} hPa threshold. "
                        "Low pressure systems can worsen sinus symptoms."
                    ),
                    "severity": "high" if avg_pressure <= 990 else "medium",
                }
            )

        # Precipitation analysis
        if weather_factors.get("precipitation", 0) > 0:
            max_precipitation = max([f.precipitation for f in forecasts], default=0)
            detailed_factors.append(
                {
                    "name": "Precipitation",
                    "score": weather_factors["precipitation"],
                    "weight": weights["precipitation"],
                    "explanation": (
                        f"Expected precipitation of {max_precipitation:.1f} mm. "
                        "Rain can increase mold spores and allergens in the air."
                    ),
                    "severity": "high" if max_precipitation >= 8 else "medium",
                }
            )

        # Cloud cover analysis
        if weather_factors.get("cloud_cover", 0) > 0:
            avg_cloud_cover = np.mean([f.cloud_cover for f in forecasts])
            detailed_factors.append(
                {
                    "name": "Cloud Cover",
                    "score": weather_factors["cloud_cover"],
                    "weight": weights["cloud_cover"],
                    "explanation": (
                        f"Cloud cover will be {avg_cloud_cover:.1f}%, which is above the "
                        f"{thresholds['cloud_cover_high']}% threshold."
                    ),
                    "severity": "medium",
                }
            )

        # Calculate total weighted score
        total_score = sum(factor["score"] * factor["weight"] for factor in detailed_factors)

        # Sort factors by their weighted contribution (score * weight)
        detailed_factors.sort(key=lambda x: x["score"] * x["weight"], reverse=True)

        return {
            "factors": detailed_factors,
            "total_score": round(total_score, 2),
            "contributing_factors_count": len(detailed_factors),
        }
