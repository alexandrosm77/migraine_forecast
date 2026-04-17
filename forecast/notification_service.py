import logging
from datetime import timedelta

import numpy as np
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone
from django.utils import translation

from .models import (
    MigrainePrediction,
    SinusitisPrediction,
    HayFeverPrediction,
    Location,
    NotificationLog,
)
from .prediction_service import MigrainePredictionService
from .prediction_service_sinusitis import SinusitisPredictionService
from .prediction_service_hayfever import HayFeverPredictionService
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
        self.hayfever_prediction_service = HayFeverPredictionService()
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

    def _should_send_notification(self, user, severity_level, notification_type="general", is_digest=False):
        """
        Check if a notification should be sent based on all user preferences.

        Args:
            user: User object
            severity_level: "LOW", "MEDIUM", or "HIGH"
            notification_type: "migraine", "sinusitis", or "general"
            is_digest: If True, skip the DIGEST mode check (used when intentionally sending a digest)

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
        # (but allow if this is an intentional digest send)
        if profile.notification_mode == "DIGEST" and not is_digest:
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

        if notification_type == "hayfever" and profile.daily_hay_fever_notification_limit > 0:
            hayfever_count = NotificationLog.objects.filter(
                user=user,
                status="sent",
                notification_type="hayfever",
                sent_at__gte=start_of_day,
                sent_at__lt=start_of_day + timedelta(days=1),
            ).count()

            if hayfever_count >= profile.daily_hay_fever_notification_limit:
                return (
                    False,
                    f"Hay fever daily limit reached "
                    f"({hayfever_count}/{profile.daily_hay_fever_notification_limit})",
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

    def _create_notification_log(self, user, notification_type, migraine_preds=None,
                                 sinusitis_preds=None, hayfever_preds=None):
        """
        Create a notification log entry.

        Args:
            user: User object
            notification_type: Type of notification
            migraine_preds: List of MigrainePrediction objects
            sinusitis_preds: List of SinusitisPrediction objects
            hayfever_preds: List of HayFeverPrediction objects

        Returns:
            NotificationLog object
        """
        migraine_preds = migraine_preds or []
        sinusitis_preds = sinusitis_preds or []
        hayfever_preds = hayfever_preds or []

        # Determine highest severity
        all_severities = [p.probability for p in migraine_preds + sinusitis_preds + hayfever_preds]
        severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        highest_severity = max(all_severities, key=lambda x: severity_order.get(x, 0)) if all_severities else "LOW"

        # Count unique locations
        all_locations = set([p.location for p in migraine_preds + sinusitis_preds + hayfever_preds])

        log = NotificationLog.objects.create(
            user=user,
            notification_type=notification_type,
            channel="email",
            status="pending",
            recipient=user.email,
            severity_level=highest_severity,
            locations_count=len(all_locations),
            predictions_count=len(migraine_preds) + len(sinusitis_preds) + len(hayfever_preds),
            scheduled_time=timezone.now(),
        )

        # Add predictions to the log
        if migraine_preds:
            log.migraine_predictions.set(migraine_preds)
        if sinusitis_preds:
            log.sinusitis_predictions.set(sinusitis_preds)
        if hayfever_preds:
            log.hayfever_predictions.set(hayfever_preds)

        return log

    def _update_last_notification_timestamp(self, user, notification_type):
        """
        Update the last notification timestamp for a user.

        Args:
            user: User object
            notification_type: "migraine", "sinusitis", "hayfever", or "combined"
        """
        try:
            profile = user.health_profile
            now = timezone.now()

            profile.last_notification_sent_at = now

            if notification_type in ["migraine", "combined"]:
                profile.last_migraine_notification_sent_at = now

            if notification_type in ["sinusitis", "combined"]:
                profile.last_sinusitis_notification_sent_at = now

            if notification_type in ["hayfever", "combined"]:
                profile.last_hay_fever_notification_sent_at = now

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
            "llm_rationale": (weather_factors or {}).get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),
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

    def send_combined_alert(self, migraine_predictions=None, sinusitis_predictions=None,
                            hayfever_predictions=None, is_digest=False):
        """
        Send a combined alert email for migraine/sinusitis/hay fever predictions across multiple locations.

        Args:
            migraine_predictions (list, optional): List of MigrainePrediction instances
            sinusitis_predictions (list, optional): List of SinusitisPrediction instances
            hayfever_predictions (list, optional): List of HayFeverPrediction instances
            is_digest (bool): If True, this is a digest send and DIGEST mode check is bypassed

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        # Convert single predictions to lists for backward compatibility
        if migraine_predictions is not None and not isinstance(migraine_predictions, list):
            migraine_predictions = [migraine_predictions]
        if sinusitis_predictions is not None and not isinstance(sinusitis_predictions, list):
            sinusitis_predictions = [sinusitis_predictions]
        if hayfever_predictions is not None and not isinstance(hayfever_predictions, list):
            hayfever_predictions = [hayfever_predictions]

        # At least one prediction must be provided
        if not migraine_predictions and not sinusitis_predictions and not hayfever_predictions:
            logger.error("send_combined_alert called with no predictions")
            capture_message("send_combined_alert called with no predictions", level="error")
            return False

        # Get user from whichever prediction list is available
        all_predictions = (
            (migraine_predictions or []) + (sinusitis_predictions or []) + (hayfever_predictions or [])
        )
        if not all_predictions:
            logger.error("send_combined_alert called with empty prediction lists")
            capture_message("send_combined_alert called with empty prediction lists", level="error")
            return False

        user = all_predictions[0].user

        # Create notification log
        notification_log = self._create_notification_log(
            user, "combined",
            migraine_preds=migraine_predictions,
            sinusitis_preds=sinusitis_predictions,
            hayfever_preds=hayfever_predictions,
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
                "hayfever_count": len(hayfever_predictions) if hayfever_predictions else 0,
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
        should_send, reason = self._should_send_notification(user, highest_severity, "general", is_digest=is_digest)
        if not should_send:
            logger.info(f"Skipping combined alert for user {user.username}: {reason}")
            notification_log.mark_skipped(reason)
            return False

        # Prepare location-based predictions
        location_data = []

        # Group predictions by location
        from collections import defaultdict

        location_predictions = defaultdict(lambda: {"migraine": None, "sinusitis": None, "hayfever": None})

        if migraine_predictions:
            for pred in migraine_predictions:
                location_predictions[pred.location.id]["migraine"] = pred
                location_predictions[pred.location.id]["location"] = pred.location

        if sinusitis_predictions:
            for pred in sinusitis_predictions:
                location_predictions[pred.location.id]["sinusitis"] = pred
                location_predictions[pred.location.id]["location"] = pred.location

        if hayfever_predictions:
            for pred in hayfever_predictions:
                location_predictions[pred.location.id]["hayfever"] = pred
                location_predictions[pred.location.id]["location"] = pred.location

        # Build location data for template
        for loc_id, preds in location_predictions.items():
            location = preds["location"]
            migraine_pred = preds["migraine"]
            sinusitis_pred = preds["sinusitis"]
            hayfever_pred = preds["hayfever"]

            # Get forecast from whichever prediction is available
            any_pred = migraine_pred or sinusitis_pred or hayfever_pred
            forecast = any_pred.forecast

            loc_data = {
                "location": location,
                "forecast": forecast,
                "start_time": any_pred.target_time_start,
                "end_time": any_pred.target_time_end,
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
                        "migraine_llm_rationale": migraine_weather_factors.get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),  # noqa
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
                        "sinusitis_llm_rationale": sinusitis_weather_factors.get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),  # noqa
                        "sinusitis_llm_prevention_tips": sinusitis_weather_factors.get("llm_prevention_tips") or [],
                    }
                )

            # Add hay fever data if available
            if hayfever_pred:
                hayfever_weather_factors = hayfever_pred.weather_factors or {}

                loc_data.update(
                    {
                        "hayfever_prediction": hayfever_pred,
                        "hayfever_probability_level": hayfever_pred.probability,
                        "hayfever_weather_factors": hayfever_weather_factors,
                        "hayfever_pollen_available": hayfever_weather_factors.get("pollen_available", True),
                        "hayfever_llm_analysis_text": hayfever_weather_factors.get("llm_analysis_text"),
                        "hayfever_llm_rationale": hayfever_weather_factors.get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),  # noqa
                        "hayfever_llm_prevention_tips": hayfever_weather_factors.get("llm_prevention_tips") or [],
                    }
                )

            location_data.append(loc_data)

        # Prepare context for email
        # Determine if we have any migraine, sinusitis, or hay fever predictions
        has_migraine = any(loc.get("migraine_prediction") for loc in location_data)
        has_sinusitis = any(loc.get("sinusitis_prediction") for loc in location_data)
        has_hayfever = any(loc.get("hayfever_prediction") for loc in location_data)

        # Get first location with tips for each type
        first_migraine_tips = None
        first_sinusitis_tips = None
        first_hayfever_tips = None

        for loc in location_data:
            if not first_migraine_tips and loc.get("migraine_llm_prevention_tips"):
                first_migraine_tips = loc.get("migraine_llm_prevention_tips")
            if not first_sinusitis_tips and loc.get("sinusitis_llm_prevention_tips"):
                first_sinusitis_tips = loc.get("sinusitis_llm_prevention_tips")
            if not first_hayfever_tips and loc.get("hayfever_llm_prevention_tips"):
                first_hayfever_tips = loc.get("hayfever_llm_prevention_tips")

        context = {
            "user": user,
            "locations": location_data,
            "location_count": len(location_data),
            "has_migraine": has_migraine,
            "has_sinusitis": has_sinusitis,
            "has_hayfever": has_hayfever,
            "first_migraine_tips": first_migraine_tips,
            "first_sinusitis_tips": first_sinusitis_tips,
            "first_hayfever_tips": first_hayfever_tips,
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
                f"({len(migraine_predictions or [])} migraine, {len(sinusitis_predictions or [])} sinusitis, "
                f"{len(hayfever_predictions or [])} hay fever "
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
                    "hayfever_count": len(hayfever_predictions or []),
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

    # ------------------------------------------------------------------
    # Condition-specific explanation configs for _get_detailed_factors
    # ------------------------------------------------------------------

    _MIGRAINE_FACTOR_CONFIG = {
        "llm_prediction_field": "migraine_prediction",
        "temp_trigger_text": "Rapid temperature changes are a known migraine trigger.",
        "temp_severity_multiplier": 2.0,
        "humidity_high_text": "Extreme humidity levels can increase migraine risk.",
        "humidity_low_text": "Very dry air can trigger migraines.",
        "humidity_low_severe": 20,
        "humidity_change_threshold": 5,
        "humidity_change_detail": True,  # include % change text
        "pressure_change_text": "Rapid pressure changes are one of the strongest migraine triggers.",
        "pressure_change_severity_multiplier": 2.0,
        "pressure_change_detail": True,  # include % change text
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
        "llm_prediction_field": None,  # sinusitis doesn't use LLM context
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
        "cloud_heavy_text": None,  # use threshold-based text
        "cloud_moderate_text": None,
    }

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

        # --- Temperature change ---
        self._add_temperature_factor(
            factors, wf, forecasts, previous_forecasts, llm_ctx, thresholds, weights, cfg
        )
        # --- Humidity ---
        self._add_humidity_factor(
            factors, wf, forecasts, previous_forecasts, llm_ctx, thresholds, weights, cfg
        )
        # --- Pressure change ---
        self._add_pressure_change_factor(
            factors, wf, forecasts, previous_forecasts, llm_ctx, thresholds, weights, cfg
        )
        # --- Low pressure ---
        self._add_low_pressure_factor(
            factors, wf, forecasts, previous_forecasts, llm_ctx, thresholds, weights, cfg
        )
        # --- Precipitation ---
        self._add_precipitation_factor(
            factors, wf, forecasts, llm_ctx, thresholds, weights, cfg
        )
        # --- Cloud cover ---
        self._add_cloud_cover_factor(
            factors, wf, forecasts, llm_ctx, thresholds, weights, cfg
        )

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
    # Factor helper methods used by _get_detailed_factors
    # ------------------------------------------------------------------

    def _resolve_value(self, llm_ctx, section, key, fallback_fn):
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

    def _get_detailed_weather_factors(self, prediction):
        """Get detailed migraine weather factors. Delegates to _get_detailed_factors."""
        return self._get_detailed_factors(prediction, "migraine")

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

        # Check if notification should be sent based on all preferences
        should_send, reason = self._should_send_notification(user, probability_level, "sinusitis")
        if not should_send:
            logger.info(f"Skipping sinusitis alert for user {user.username}: {reason}")
            return False

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
            "llm_rationale": (weather_factors or {}).get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),
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

    def send_hayfever_alert(self, prediction):
        """
        Send hay fever alert email for a specific prediction.

        Args:
            prediction (HayFeverPrediction): The prediction model instance

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        user = prediction.user
        location = prediction.location
        forecast = prediction.forecast
        probability_level = prediction.probability
        weather_factors = prediction.weather_factors or {}

        # Skip if user has no email
        if not user.email:
            logger.warning(f"Cannot send hay fever alert to user {user.username}: No email address")
            return False

        # Check if notification should be sent based on all preferences
        should_send, reason = self._should_send_notification(user, probability_level, "hayfever")
        if not should_send:
            logger.info(f"Skipping hay fever alert for user {user.username}: {reason}")
            return False

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
            "pollen_available": weather_factors.get("pollen_available", True),
            "llm_analysis_text": weather_factors.get("llm_analysis_text"),
            "llm_rationale": (weather_factors.get("llm", {}) or {}).get("detail", {}).get("raw", {}).get("rationale"),
            "llm_prevention_tips": weather_factors.get("llm_prevention_tips") or [],
        }

        # Activate user's language for email rendering
        user_language = self._get_user_language(user)
        if user_language:
            translation.activate(user_language)

        try:
            subject = f"{probability_level} Hay Fever Alert for {location.city}"
            html_message = render_to_string("forecast/email/hayfever_alert.html", context)
            plain_message = strip_tags(html_message)
        finally:
            # Deactivate translation to avoid affecting other parts of the system
            translation.deactivate()

        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Sent hay fever alert email to {user.email}")
            self._update_last_notification_timestamp(user, "hayfever")
            return True
        except Exception as e:
            logger.error(f"Failed to send hay fever alert email: {e}")
            return False

    def check_and_send_combined_notifications(self, migraine_predictions: dict, sinusitis_predictions: dict,
                                              hayfever_predictions: dict = None):
        """
        Check migraine, sinusitis, and hay fever predictions and send combined notifications.

        This method groups predictions by user across ALL locations and sends:
        - A single email per user containing all their predictions from all locations
        - Combines migraine, sinusitis, and hay fever predictions in the same email

        Args:
            migraine_predictions (dict): Dictionary mapping location IDs to migraine prediction data
            sinusitis_predictions (dict): Dictionary mapping location IDs to sinusitis prediction data
            hayfever_predictions (dict, optional): Dictionary mapping location IDs to hay fever prediction data

        Returns:
            int: Number of notifications sent (one per user)
        """
        from django.db.models import Max

        hayfever_predictions = hayfever_predictions or {}

        now = timezone.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        # --- Batch-load all relevant data ---

        # 1. Get all locations with users and health profiles in 1 query
        locations = Location.objects.select_related("user", "user__health_profile").all()

        # 2. Build user -> locations mapping and deduplicate users
        user_map = {}         # user_id -> User instance (with profile already loaded)
        user_locations = {}   # user_id -> list of Location instances
        for location in locations:
            if not location.user:
                continue
            uid = location.user_id
            if uid not in user_map:
                user_map[uid] = location.user
                user_locations[uid] = []
            user_locations[uid].append(location)

        if not user_map:
            return 0

        user_ids = list(user_map.keys())

        # 3. Batch-check daily limits: which users had notifications sent today? (2 queries total)
        users_with_migraine_today = set(
            MigrainePrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).values_list("user_id", flat=True).distinct()
        )
        users_with_sinusitis_today = set(
            SinusitisPrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).values_list("user_id", flat=True).distinct()
        )
        users_with_hayfever_today = set(
            HayFeverPrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).values_list("user_id", flat=True).distinct()
        )

        # 4. Batch-check frequency: most recent notification time per user (2 queries total)
        migraine_recent_times = dict(
            MigrainePrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=now - timedelta(hours=24),  # generous window
            ).values("user_id").annotate(latest=Max("prediction_time")).values_list("user_id", "latest")
        )
        sinusitis_recent_times = dict(
            SinusitisPrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=now - timedelta(hours=24),
            ).values("user_id").annotate(latest=Max("prediction_time")).values_list("user_id", "latest")
        )
        hayfever_recent_times = dict(
            HayFeverPrediction.objects.filter(
                user_id__in=user_ids,
                notification_sent=True,
                prediction_time__gte=now - timedelta(hours=24),
            ).values("user_id").annotate(latest=Max("prediction_time")).values_list("user_id", "latest")
        )

        # --- Per-user filtering (no additional queries) ---
        user_predictions = {}  # user_id -> {"migraine": [...], "sinusitis": [...]}

        for uid, user in user_map.items():
            # Get health profile (already loaded via select_related)
            profile = getattr(user, "health_profile", None)

            # Skip DIGEST mode users
            if profile and profile.notification_mode == "DIGEST":
                logger.debug(f"Skipping DIGEST mode user {user.username} (predictions run via digest task)")
                continue

            # Check daily limit
            limit = int(profile.daily_notification_limit) if profile else 1
            if limit <= 0:
                logger.debug(f"Notifications disabled for user {user.username} (limit={limit})")
                continue

            emails_sent_today = 1 if (
                uid in users_with_migraine_today
                or uid in users_with_sinusitis_today
                or uid in users_with_hayfever_today
            ) else 0
            if emails_sent_today >= limit:
                logger.debug(f"User {user.username} has reached daily limit ({limit})")
                continue

            # Check frequency
            notification_frequency_hours = int(profile.notification_frequency_hours) if profile else 3
            frequency_cutoff = now - timedelta(hours=notification_frequency_hours)

            latest_times = [
                t for t in (
                    migraine_recent_times.get(uid),
                    sinusitis_recent_times.get(uid),
                    hayfever_recent_times.get(uid),
                ) if t is not None
            ]
            most_recent_time = max(latest_times) if latest_times else None

            if most_recent_time and most_recent_time >= frequency_cutoff:
                hours_since = (now - most_recent_time).total_seconds() / 3600
                logger.debug(
                    f"User {user.username} was notified {hours_since:.1f} hours ago, "
                    f"minimum frequency is {notification_frequency_hours} hours"
                )
                continue

            # Check email notifications enabled
            if profile and not profile.email_notifications_enabled:
                logger.info(f"Skipping notifications for user {user.username}: Email notifications disabled")
                continue

            # Collect predictions for ALL locations for this user (no queries — uses cached locations)
            user_migraine_preds = []
            user_sinusitis_preds = []
            user_hayfever_preds = []
            migraine_enabled = profile.migraine_predictions_enabled if profile else True
            sinusitis_enabled = profile.sinusitis_predictions_enabled if profile else True
            hayfever_enabled = profile.hay_fever_predictions_enabled if profile else True

            for loc in user_locations[uid]:
                # Migraine predictions
                if migraine_enabled:
                    migraine_data = migraine_predictions.get(loc.id)
                    if migraine_data:
                        prob_level = migraine_data.get("probability")
                        pred = migraine_data.get("prediction")
                        if prob_level in ["HIGH", "MEDIUM"] and pred and not pred.notification_sent:
                            user_migraine_preds.append(pred)

                # Sinusitis predictions
                if sinusitis_enabled:
                    sinusitis_data = sinusitis_predictions.get(loc.id)
                    if sinusitis_data:
                        prob_level = sinusitis_data.get("probability")
                        pred = sinusitis_data.get("prediction")
                        if prob_level in ["HIGH", "MEDIUM"] and pred and not pred.notification_sent:
                            user_sinusitis_preds.append(pred)

                # Hay fever predictions
                if hayfever_enabled:
                    hayfever_data = hayfever_predictions.get(loc.id)
                    if hayfever_data:
                        prob_level = hayfever_data.get("probability")
                        pred = hayfever_data.get("prediction")
                        if prob_level in ["HIGH", "MEDIUM"] and pred and not pred.notification_sent:
                            user_hayfever_preds.append(pred)

            if user_migraine_preds or user_sinusitis_preds or user_hayfever_preds:
                user_predictions[uid] = {
                    "migraine": user_migraine_preds,
                    "sinusitis": user_sinusitis_preds,
                    "hayfever": user_hayfever_preds,
                }

        # --- Send one email per user ---
        notifications_sent = 0

        for uid, predictions in user_predictions.items():
            migraine_preds = predictions["migraine"]
            sinusitis_preds = predictions["sinusitis"]
            hayfever_preds = predictions.get("hayfever", [])

            if not migraine_preds and not sinusitis_preds and not hayfever_preds:
                continue

            user = user_map[uid]  # already cached, no query needed

            if self.send_combined_alert(
                migraine_predictions=migraine_preds,
                sinusitis_predictions=sinusitis_preds,
                hayfever_predictions=hayfever_preds,
            ):
                # Batch-update notification_sent
                all_preds_to_update = []
                for pred in migraine_preds:
                    pred.notification_sent = True
                    all_preds_to_update.append(pred)
                for pred in sinusitis_preds:
                    pred.notification_sent = True
                    all_preds_to_update.append(pred)
                for pred in hayfever_preds:
                    pred.notification_sent = True
                    all_preds_to_update.append(pred)

                if migraine_preds:
                    MigrainePrediction.objects.filter(
                        id__in=[p.id for p in migraine_preds]
                    ).update(notification_sent=True)
                if sinusitis_preds:
                    SinusitisPrediction.objects.filter(
                        id__in=[p.id for p in sinusitis_preds]
                    ).update(notification_sent=True)
                if hayfever_preds:
                    HayFeverPrediction.objects.filter(
                        id__in=[p.id for p in hayfever_preds]
                    ).update(notification_sent=True)

                notifications_sent += 1

                location_count = len(set(
                    p.location_id for p in migraine_preds + sinusitis_preds + hayfever_preds
                ))
                logger.info(
                    f"Sent combined alert to {user.email} covering {location_count} location(s) "
                    f"({len(migraine_preds)} migraine, {len(sinusitis_preds)} sinusitis, "
                    f"{len(hayfever_preds)} hay fever)"
                )

        logger.info(f"Sent {notifications_sent} combined alert notifications")
        return notifications_sent

    def _get_detailed_sinusitis_factors(self, prediction):
        """Get detailed sinusitis weather factors. Delegates to _get_detailed_factors."""
        return self._get_detailed_factors(prediction, "sinusitis")
