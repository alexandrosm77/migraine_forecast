from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging
from datetime import datetime, timedelta

from .models import MigrainePrediction, Location
from .prediction_service import MigrainePredictionService
from .weather_service import WeatherService

logger = logging.getLogger(__name__)

class NotificationService:
    """
    Service for sending email notifications about migraine predictions.
    """
    
    def __init__(self):
        """Initialize the notification service."""
        self.prediction_service = MigrainePredictionService()
        self.weather_service = WeatherService()
    
    def check_and_send_notifications(self, predictions: dict):
        """
        Check migraine probability for all users and locations and send notifications if needed.
        
        Returns:
            int: Number of notifications sent
        """
        # Get all locations with associated users
        locations = Location.objects.select_related('user').all()
        
        notifications_sent = 0
        
        for location in locations:
            # Skip if no user associated
            if not location.user:
                continue

            location_prediction = predictions.get(location.id, None)

            if location_prediction is None:
                continue

            probability_level = location_prediction.get("probability", None)
            prediction = location_prediction.get("prediction", None)
            
            if probability_level is not None and prediction is not None:
                # Check if notification should be sent (HIGH/MEDIUM probability and not already sent)
                if probability_level == 'HIGH' or probability_level == 'MEDIUM':
                    if not prediction.notification_sent:
                        self.send_migraine_alert(prediction)

                        prediction.notification_sent = True
                        prediction.save()

                        notifications_sent += 1
        
        logger.info(f"Sent {notifications_sent} migraine alert notifications")
        return notifications_sent
    
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
        
        # Skip if user has no email
        if not user.email:
            logger.warning(f"Cannot send migraine alert to user {user.username}: No email address")
            return False
        
        # Prepare email context
        context = {
            'user': user,
            'location': location,
            'prediction': prediction,
            'forecast': forecast,
            'start_time': prediction.target_time_start,
            'end_time': prediction.target_time_end,
            'temperature': forecast.temperature,
            'humidity': forecast.humidity,
            'pressure': forecast.pressure,
            'precipitation': forecast.precipitation,
            'cloud_cover': forecast.cloud_cover,
            'probability_level': probability_level,
            'weather_factors': weather_factors,
        }
        
        # Render email content
        subject = f"Migraine Alert for {location.city}"
        html_message = render_to_string('forecast/email/migraine_alert.html', context)
        plain_message = strip_tags(html_message)
        
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
            return True
        except Exception as e:
            logger.error(f"Failed to send migraine alert email: {e}")
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
        message = "This is a test email from the Migraine Forecast application. If you received this, email notifications are working correctly."
        
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
