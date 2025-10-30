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

            # Enforce per-location daily notification limit
            try:
                limit = int(getattr(location, 'daily_notification_limit', 1))
            except (TypeError, ValueError):
                limit = 1
            if limit is None:
                limit = 1
            if limit <= 0:
                # Notifications disabled for this location
                continue

            from django.utils import timezone
            now = timezone.now()
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = start_of_day + timedelta(days=1)

            sent_today = MigrainePrediction.objects.filter(
                user=location.user,
                location=location,
                notification_sent=True,
                prediction_time__gte=start_of_day,
                prediction_time__lt=end_of_day,
            ).count()

            if sent_today >= limit:
                # Already reached today's limit for this location
                continue

            location_prediction = predictions.get(location.id, None)

            if location_prediction is None:
                continue

            probability_level = location_prediction.get("probability", None)
            prediction = location_prediction.get("prediction", None)
            
            if probability_level is not None and prediction is not None:
                # Check if notification should be sent (HIGH/MEDIUM probability and not already sent)
                if probability_level == 'HIGH' or probability_level == 'MEDIUM':
                    if not prediction.notification_sent and sent_today < limit:
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

        # Get additional context for human-friendly explanations
        detailed_factors = self._get_detailed_weather_factors(prediction)

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
            'detailed_factors': detailed_factors,
        }
        
        # Render email content
        factor_count = detailed_factors.get('contributing_factors_count', 0)
        if factor_count > 0:
            subject = f"{probability_level} Migraine Alert for {location.city} - {factor_count} Weather Factor{'s' if factor_count != 1 else ''}"
        else:
            subject = f"{probability_level} Migraine Alert for {location.city}"
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
        from django.utils import timezone
        from datetime import timedelta
        from .models import WeatherForecast
        import numpy as np

        # Get forecasts for the prediction window
        forecasts = WeatherForecast.objects.filter(
            location=prediction.location,
            target_time__gte=prediction.target_time_start,
            target_time__lte=prediction.target_time_end
        ).order_by('target_time')

        # Get previous forecasts for comparison
        previous_forecasts = WeatherForecast.objects.filter(
            location=prediction.location,
            target_time__lt=prediction.target_time_start
        ).order_by('-target_time')[:6]

        if not forecasts:
            return {'factors': detailed_factors, 'total_score': 0}

        # Temperature change analysis
        if weather_factors.get('temperature_change', 0) > 0 and previous_forecasts:
            avg_prev_temp = np.mean([f.temperature for f in previous_forecasts])
            avg_forecast_temp = np.mean([f.temperature for f in forecasts])
            temp_change = abs(avg_forecast_temp - avg_prev_temp)

            if temp_change >= thresholds['temperature_change']:
                direction = "increase" if avg_forecast_temp > avg_prev_temp else "decrease"
                detailed_factors.append({
                    'name': 'Temperature Change',
                    'score': weather_factors['temperature_change'],
                    'weight': weights['temperature_change'],
                    'explanation': f"Temperature will {direction} by {temp_change:.1f}°C (from {avg_prev_temp:.1f}°C to {avg_forecast_temp:.1f}°C). Changes of {thresholds['temperature_change']}°C or more can trigger migraines.",
                    'severity': 'high' if temp_change >= thresholds['temperature_change'] * 2 else 'medium'
                })

        # Humidity analysis
        if weather_factors.get('humidity_extreme', 0) > 0:
            avg_humidity = np.mean([f.humidity for f in forecasts])

            if avg_humidity >= thresholds['humidity_high']:
                detailed_factors.append({
                    'name': 'High Humidity',
                    'score': weather_factors['humidity_extreme'],
                    'weight': weights['humidity_extreme'],
                    'explanation': f"Humidity will be {avg_humidity:.1f}%, which is above the {thresholds['humidity_high']}% threshold. High humidity can increase migraine risk.",
                    'severity': 'high' if avg_humidity >= 85 else 'medium'
                })
            elif avg_humidity <= thresholds['humidity_low']:
                detailed_factors.append({
                    'name': 'Low Humidity',
                    'score': weather_factors['humidity_extreme'],
                    'weight': weights['humidity_extreme'],
                    'explanation': f"Humidity will be {avg_humidity:.1f}%, which is below the {thresholds['humidity_low']}% threshold. Very dry air can trigger migraines.",
                    'severity': 'high' if avg_humidity <= 20 else 'medium'
                })

        # Pressure change analysis
        if weather_factors.get('pressure_change', 0) > 0 and previous_forecasts:
            avg_prev_pressure = np.mean([f.pressure for f in previous_forecasts])
            avg_forecast_pressure = np.mean([f.pressure for f in forecasts])
            pressure_change = abs(avg_forecast_pressure - avg_prev_pressure)

            if pressure_change >= thresholds['pressure_change']:
                direction = "increase" if avg_forecast_pressure > avg_prev_pressure else "drop"
                detailed_factors.append({
                    'name': 'Barometric Pressure Change',
                    'score': weather_factors['pressure_change'],
                    'weight': weights['pressure_change'],
                    'explanation': f"Barometric pressure will {direction} by {pressure_change:.1f} hPa (from {avg_prev_pressure:.1f} to {avg_forecast_pressure:.1f} hPa). Pressure changes of {thresholds['pressure_change']} hPa or more are strong migraine triggers.",
                    'severity': 'high' if pressure_change >= thresholds['pressure_change'] * 2 else 'medium'
                })

        # Low pressure analysis
        if weather_factors.get('pressure_low', 0) > 0:
            avg_pressure = np.mean([f.pressure for f in forecasts])
            detailed_factors.append({
                'name': 'Low Barometric Pressure',
                'score': weather_factors['pressure_low'],
                'weight': weights['pressure_low'],
                'explanation': f"Barometric pressure will be {avg_pressure:.1f} hPa, which is below the {thresholds['pressure_low']} hPa threshold. Low pressure systems are associated with increased migraine frequency.",
                'severity': 'high' if avg_pressure <= 995 else 'medium'
            })

        # Precipitation analysis
        if weather_factors.get('precipitation', 0) > 0:
            max_precipitation = max([f.precipitation for f in forecasts], default=0)
            detailed_factors.append({
                'name': 'Heavy Precipitation',
                'score': weather_factors['precipitation'],
                'weight': weights['precipitation'],
                'explanation': f"Expected precipitation of {max_precipitation:.1f} mm, which exceeds the {thresholds['precipitation_high']} mm threshold. Heavy rain or storms can trigger migraines.",
                'severity': 'high' if max_precipitation >= 10 else 'medium'
            })

        # Cloud cover analysis
        if weather_factors.get('cloud_cover', 0) > 0:
            avg_cloud_cover = np.mean([f.cloud_cover for f in forecasts])
            detailed_factors.append({
                'name': 'Heavy Cloud Cover',
                'score': weather_factors['cloud_cover'],
                'weight': weights['cloud_cover'],
                'explanation': f"Cloud cover will be {avg_cloud_cover:.1f}%, which is above the {thresholds['cloud_cover_high']}% threshold. Overcast conditions can affect some migraine sufferers.",
                'severity': 'medium'
            })

        # Calculate total weighted score
        total_score = sum(factor['score'] * factor['weight'] for factor in detailed_factors)

        # Sort factors by their weighted contribution (score * weight)
        detailed_factors.sort(key=lambda x: x['score'] * x['weight'], reverse=True)

        return {
            'factors': detailed_factors,
            'total_score': round(total_score, 2),
            'contributing_factors_count': len(detailed_factors)
        }
