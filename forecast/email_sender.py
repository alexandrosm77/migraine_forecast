import logging

from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import translation

from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, set_tag

from .notification_preferences import NotificationPreferences
from .weather_factor_explainer import WeatherFactorExplainer

logger = logging.getLogger(__name__)


class EmailSender:
    """
    Handles rendering and sending condition-specific alert emails
    (migraine, sinusitis, hay fever) and combined multi-condition alerts.
    """

    _ALERT_CONFIG = {
        "migraine": {
            "notification_type": "migraine",
            "condition_display": "Migraine",
            "template": "forecast/email/migraine_alert.html",
            "log_preds_kwarg": "migraine_preds",
            "detailed_factors_method": "get_detailed_weather_factors",
        },
        "sinusitis": {
            "notification_type": "sinusitis",
            "condition_display": "Sinusitis",
            "template": "forecast/email/sinusitis_alert.html",
            "log_preds_kwarg": "sinusitis_preds",
            "detailed_factors_method": "get_detailed_sinusitis_factors",
        },
        "hayfever": {
            "notification_type": "hayfever",
            "condition_display": "Hay Fever",
            "template": "forecast/email/hayfever_alert.html",
            "log_preds_kwarg": "hayfever_preds",
            "detailed_factors_method": None,
        },
    }

    def __init__(self):
        self._prefs = NotificationPreferences()
        self._explainer = WeatherFactorExplainer()

    # ------------------------------------------------------------------
    # Single-condition alerts
    # ------------------------------------------------------------------

    def send_migraine_alert(self, prediction):
        """Send migraine alert email for a specific prediction."""
        return self._send_condition_alert(prediction, "migraine")

    def send_sinusitis_alert(self, prediction):
        """Send sinusitis alert email for a specific prediction."""
        return self._send_condition_alert(prediction, "sinusitis")

    def send_hayfever_alert(self, prediction):
        """Send hay fever alert email for a specific prediction."""
        return self._send_condition_alert(prediction, "hayfever")

    def _send_condition_alert(self, prediction, condition_type):
        """
        Send an alert email for any condition type.

        Args:
            prediction: Prediction model instance
            condition_type: One of "migraine", "sinusitis", "hayfever"

        Returns:
            bool: True if email was sent successfully, False otherwise
        """
        cfg = self._ALERT_CONFIG[condition_type]
        user = prediction.user
        location = prediction.location
        forecast = prediction.forecast
        probability_level = prediction.probability
        weather_factors = prediction.weather_factors or {}

        add_breadcrumb(
            category="email",
            message=f"Sending {cfg['condition_display'].lower()} alert email",
            level="info",
            data={"user": user.username, "location": str(location), "probability": probability_level},
        )

        set_tag("email_type", f"{condition_type}_alert")
        set_tag("risk_level", probability_level)

        notification_log = self._prefs.create_notification_log(
            user, cfg["notification_type"], **{cfg["log_preds_kwarg"]: [prediction]}
        )

        if not user.email:
            logger.warning(f"Cannot send {condition_type} alert to user {user.username}: No email address")
            notification_log.mark_skipped("No email address")
            capture_message(
                f"Cannot send {condition_type} alert: User {user.username} has no email address",
                level="warning",
            )
            return False

        should_send, reason = self._prefs.should_send_notification(
            user, probability_level, cfg["notification_type"]
        )
        if not should_send:
            logger.info(f"Skipping {condition_type} alert for user {user.username}: {reason}")
            notification_log.mark_skipped(reason)
            return False

        # Get detailed factors if applicable
        detailed_factors = {}
        if cfg["detailed_factors_method"]:
            detailed_factors = getattr(self._explainer, cfg["detailed_factors_method"])(prediction)

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
            "llm_analysis_text": weather_factors.get("llm_analysis_text"),
            "llm_rationale": (weather_factors.get("llm", {}) or {}).get("detail", {}).get("raw", {}).get("rationale"),
            "llm_prevention_tips": weather_factors.get("llm_prevention_tips") or [],
        }

        if condition_type == "hayfever":
            context["pollen_available"] = weather_factors.get("pollen_available", True)

        user_language = self._prefs.get_user_language(user)
        if user_language:
            translation.activate(user_language)

        try:
            factor_count = detailed_factors.get("contributing_factors_count", 0)
            if factor_count > 0:
                factor_word = "Factor" if factor_count == 1 else "Factors"
                subject = (
                    f"{probability_level} {cfg['condition_display']} Alert for {location.city} - "
                    f"{factor_count} Weather {factor_word}"
                )
            else:
                subject = f"{probability_level} {cfg['condition_display']} Alert for {location.city}"

            html_message = render_to_string(cfg["template"], context)
            plain_message = strip_tags(html_message)
        finally:
            translation.deactivate()

        notification_log.subject = subject
        notification_log.save()

        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False,
            )
            logger.info(f"Sent {condition_type} alert email to {user.email}")

            add_breadcrumb(
                category="email",
                message=f"{cfg['condition_display']} alert email sent successfully",
                level="info",
                data={"recipient": user.email},
            )

            notification_log.mark_sent()
            self._prefs.update_last_notification_timestamp(user, cfg["notification_type"])

            return True
        except Exception as e:
            logger.error(f"Failed to send {condition_type} alert email: {e}")

            notification_log.mark_failed(str(e))

            set_context(
                "email_send_error",
                {
                    "email_type": f"{condition_type}_alert",
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

    # ------------------------------------------------------------------
    # Combined multi-condition alert
    # ------------------------------------------------------------------

    def send_combined_alert(self, migraine_predictions=None, sinusitis_predictions=None,
                            hayfever_predictions=None, is_digest=False):
        """
        Send a combined alert email for migraine/sinusitis/hay fever predictions across multiple locations.

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

        if not migraine_predictions and not sinusitis_predictions and not hayfever_predictions:
            logger.error("send_combined_alert called with no predictions")
            capture_message("send_combined_alert called with no predictions", level="error")
            return False

        all_predictions = (
            (migraine_predictions or []) + (sinusitis_predictions or []) + (hayfever_predictions or [])
        )
        if not all_predictions:
            logger.error("send_combined_alert called with empty prediction lists")
            capture_message("send_combined_alert called with empty prediction lists", level="error")
            return False

        user = all_predictions[0].user

        notification_log = self._prefs.create_notification_log(
            user, "combined",
            migraine_preds=migraine_predictions,
            sinusitis_preds=sinusitis_predictions,
            hayfever_preds=hayfever_predictions,
        )

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

        if not user.email:
            logger.warning(f"Cannot send combined alert to user {user.username}: No email address")
            notification_log.mark_skipped("No email address")
            capture_message(f"Cannot send combined alert: User {user.username} has no email address", level="warning")
            return False

        all_severities = [p.probability for p in all_predictions]
        severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
        highest_severity = max(all_severities, key=lambda x: severity_order.get(x, 0))

        should_send, reason = self._prefs.should_send_notification(
            user, highest_severity, "general", is_digest=is_digest
        )
        if not should_send:
            logger.info(f"Skipping combined alert for user {user.username}: {reason}")
            notification_log.mark_skipped(reason)
            return False

        # Build location data
        location_data = self._build_combined_location_data(
            migraine_predictions, sinusitis_predictions, hayfever_predictions
        )

        # Determine what types are present
        has_migraine = any(loc.get("migraine_prediction") for loc in location_data)
        has_sinusitis = any(loc.get("sinusitis_prediction") for loc in location_data)
        has_hayfever = any(loc.get("hayfever_prediction") for loc in location_data)

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

        user_language = self._prefs.get_user_language(user)
        if user_language:
            translation.activate(user_language)

        try:
            location_names = [loc["location"].city for loc in location_data]
            if len(location_names) == 1:
                location_str = location_names[0]
            elif len(location_names) == 2:
                location_str = f"{location_names[0]} & {location_names[1]}"
            else:
                location_str = f"{len(location_names)} locations"

            subject = f"Health Alert for {location_str}"
            html_message = render_to_string("forecast/email/combined_alert.html", context)
            plain_message = strip_tags(html_message)
        finally:
            translation.deactivate()

        notification_log.subject = subject
        notification_log.save()

        try:
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

            notification_log.mark_sent()
            self._prefs.update_last_notification_timestamp(user, "combined")

            return True
        except Exception as e:
            logger.error(f"Failed to send combined alert email: {e}")

            notification_log.mark_failed(str(e))

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

    def _build_combined_location_data(self, migraine_predictions, sinusitis_predictions,
                                      hayfever_predictions):
        """Group predictions by location and build template-ready data."""
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

        location_data = []
        for loc_id, preds in location_predictions.items():
            location = preds["location"]
            migraine_pred = preds["migraine"]
            sinusitis_pred = preds["sinusitis"]
            hayfever_pred = preds["hayfever"]

            any_pred = migraine_pred or sinusitis_pred or hayfever_pred
            forecast = any_pred.forecast

            loc_data = {
                "location": location,
                "forecast": forecast,
                "start_time": any_pred.target_time_start,
                "end_time": any_pred.target_time_end,
            }

            if migraine_pred:
                migraine_detailed_factors = self._explainer.get_detailed_weather_factors(migraine_pred)
                migraine_weather_factors = migraine_pred.weather_factors or {}
                loc_data.update({
                    "migraine_prediction": migraine_pred,
                    "migraine_probability_level": migraine_pred.probability,
                    "migraine_detailed_factors": migraine_detailed_factors,
                    "migraine_llm_analysis_text": migraine_weather_factors.get("llm_analysis_text"),
                    "migraine_llm_rationale": migraine_weather_factors.get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),  # noqa
                    "migraine_llm_prevention_tips": migraine_weather_factors.get("llm_prevention_tips") or [],
                })

            if sinusitis_pred:
                sinusitis_detailed_factors = self._explainer.get_detailed_sinusitis_factors(sinusitis_pred)
                sinusitis_weather_factors = sinusitis_pred.weather_factors or {}
                loc_data.update({
                    "sinusitis_prediction": sinusitis_pred,
                    "sinusitis_probability_level": sinusitis_pred.probability,
                    "sinusitis_detailed_factors": sinusitis_detailed_factors,
                    "sinusitis_llm_analysis_text": sinusitis_weather_factors.get("llm_analysis_text"),
                    "sinusitis_llm_rationale": sinusitis_weather_factors.get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),  # noqa
                    "sinusitis_llm_prevention_tips": sinusitis_weather_factors.get("llm_prevention_tips") or [],
                })

            if hayfever_pred:
                hayfever_weather_factors = hayfever_pred.weather_factors or {}
                loc_data.update({
                    "hayfever_prediction": hayfever_pred,
                    "hayfever_probability_level": hayfever_pred.probability,
                    "hayfever_weather_factors": hayfever_weather_factors,
                    "hayfever_pollen_available": hayfever_weather_factors.get("pollen_available", True),
                    "hayfever_llm_analysis_text": hayfever_weather_factors.get("llm_analysis_text"),
                    "hayfever_llm_rationale": hayfever_weather_factors.get("llm", {}).get("detail", {}).get("raw", {}).get("rationale"),  # noqa
                    "hayfever_llm_prevention_tips": hayfever_weather_factors.get("llm_prevention_tips") or [],
                })

            location_data.append(loc_data)

        return location_data

    # ------------------------------------------------------------------
    # Test email
    # ------------------------------------------------------------------

    @staticmethod
    def send_test_email(user_email):
        """
        Send a test email to verify email configuration.

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
