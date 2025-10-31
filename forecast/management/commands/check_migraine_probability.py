from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from forecast.models import Location, WeatherForecast, MigrainePrediction, SinusitisPrediction
from forecast.weather_service import WeatherService
from forecast.prediction_service import MigrainePredictionService
from forecast.prediction_service_sinusitis import SinusitisPredictionService
from forecast.notification_service import NotificationService

class Command(BaseCommand):
    help = 'Check migraine and sinusitis probability and send notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--notify-only',
            action='store_true',
            help='Only send notifications without updating forecasts',
        )
        parser.add_argument(
            '--test-notification',
            type=str,
            choices=['high', 'medium', 'low', 'none'],
            help='Send a test notification with fake prediction (high/medium/low/none)',
        )
        parser.add_argument(
            '--test-type',
            type=str,
            choices=['migraine', 'sinusitis', 'both'],
            default='both',
            help='Type of test notification to send (migraine/sinusitis/both)',
        )

    def handle(self, *args, **options):
        """
        Django management command to check migraine and sinusitis probability and send notifications.
        This can be run as a scheduled task (e.g., cron job) to:
        1. Update weather forecasts for all locations
        2. Generate migraine and sinusitis predictions
        3. Send email notifications for high-risk predictions
        """
        # Handle test notification mode
        if options.get('test_notification'):
            self._handle_test_notification(options)
            return

        self.stdout.write(self.style.SUCCESS(f"[{timezone.now()}] Starting migraine and sinusitis probability check..."))

        # Initialize services
        weather_service = WeatherService()
        migraine_prediction_service = MigrainePredictionService()
        sinusitis_prediction_service = SinusitisPredictionService()
        notification_service = NotificationService()

        # Get all locations
        locations = Location.objects.all()
        self.stdout.write(f"Found {len(locations)} locations to check")

        migraine_predictions = {}
        sinusitis_predictions = {}

        if not options['notify_only']:
            # Update forecasts for all locations
            for location in locations:
                self.stdout.write(f"Updating forecast for {location}...")
                forecasts = weather_service.update_forecast_for_location(location)
                self.stdout.write(f"Created {len(forecasts)} forecast entries")

                # Check user preferences for which predictions to generate
                user = location.user
                user_profile = None
                migraine_enabled = True  # Default to enabled
                sinusitis_enabled = True  # Default to enabled

                try:
                    user_profile = user.health_profile
                    migraine_enabled = user_profile.migraine_predictions_enabled
                    sinusitis_enabled = user_profile.sinusitis_predictions_enabled
                except Exception:
                    # If no health profile exists, default to both enabled
                    pass

                # Generate migraine prediction if enabled
                if migraine_enabled:
                    self.stdout.write(f"Generating migraine prediction for {location}...")
                    probability, prediction = migraine_prediction_service.predict_migraine_probability(
                        location=location,
                        user=user
                    )
                    migraine_predictions[location.id] = {
                        'probability': probability,
                        'prediction': prediction
                    }
                    if prediction:
                        self.stdout.write(f"Migraine Prediction: {probability} probability for {location}")
                    else:
                        self.stdout.write(self.style.WARNING(f"No migraine prediction could be made for {location}"))
                else:
                    self.stdout.write(self.style.WARNING(f"Migraine predictions disabled for user {user.username}"))

                # Generate sinusitis prediction if enabled
                if sinusitis_enabled:
                    self.stdout.write(f"Generating sinusitis prediction for {location}...")
                    sin_probability, sin_prediction = sinusitis_prediction_service.predict_sinusitis_probability(
                        location=location,
                        user=user
                    )
                    sinusitis_predictions[location.id] = {
                        'probability': sin_probability,
                        'prediction': sin_prediction
                    }
                    if sin_prediction:
                        self.stdout.write(f"Sinusitis Prediction: {sin_probability} probability for {location}")
                    else:
                        self.stdout.write(self.style.WARNING(f"No sinusitis prediction could be made for {location}"))
                else:
                    self.stdout.write(self.style.WARNING(f"Sinusitis predictions disabled for user {user.username}"))

        # Send notifications
        self.stdout.write("Checking and sending migraine notifications...")
        migraine_notifications_sent = notification_service.check_and_send_notifications(migraine_predictions)
        self.stdout.write(f"Sent {migraine_notifications_sent} migraine notifications")

        self.stdout.write("Checking and sending sinusitis notifications...")
        sinusitis_notifications_sent = notification_service.check_and_send_sinusitis_notifications(sinusitis_predictions)
        self.stdout.write(f"Sent {sinusitis_notifications_sent} sinusitis notifications")

        total_notifications = migraine_notifications_sent + sinusitis_notifications_sent
        self.stdout.write(self.style.SUCCESS(f"[{timezone.now()}] Check completed. Total notifications sent: {total_notifications}"))

    def _handle_test_notification(self, options):
        """
        Handle test notification mode - create fake predictions and send test emails.

        Args:
            options: Command options containing test_notification and test_type
        """
        test_level = options['test_notification'].upper()
        test_type = options.get('test_type', 'both')

        self.stdout.write(self.style.WARNING(f"[{timezone.now()}] TEST MODE: Creating fake {test_level} risk notification(s)"))

        # Get all locations
        locations = Location.objects.all()
        if not locations:
            self.stdout.write(self.style.ERROR("No locations found. Please create at least one location first."))
            return

        notification_service = NotificationService()
        total_sent = 0

        for location in locations:
            user = location.user
            self.stdout.write(f"Creating test notification for {user.username} at {location}")

            # Get or create a dummy forecast for this location
            now = timezone.now()
            forecast, created = WeatherForecast.objects.get_or_create(
                location=location,
                target_time=now + timedelta(hours=3),
                defaults={
                    'forecast_time': now,
                    'temperature': 20.0,
                    'humidity': 65.0,
                    'pressure': 1013.0,
                    'wind_speed': 10.0,
                    'precipitation': 0.0,
                    'cloud_cover': 50.0,
                }
            )

            # Create fake weather factors based on test level
            weather_factors = {
                'test_mode': True,
                'test_level': test_level,
                'temperature_change': 0.5 if test_level == 'LOW' else (0.7 if test_level == 'MEDIUM' else 0.9),
                'humidity_extreme': 0.3 if test_level == 'LOW' else (0.6 if test_level == 'MEDIUM' else 0.8),
                'pressure_change': 0.4 if test_level == 'LOW' else (0.7 if test_level == 'MEDIUM' else 0.95),
                'llm_analysis_text': f'This is a TEST {test_level} risk notification. Weather conditions are simulated for testing purposes.',
                'llm_prevention_tips': [
                    'This is a test notification',
                    'No real weather analysis was performed',
                    f'Test level: {test_level}'
                ]
            }

            # Create migraine test prediction if requested
            if test_type in ['migraine', 'both'] and test_level != 'NONE':
                migraine_prediction = MigrainePrediction.objects.create(
                    user=user,
                    location=location,
                    forecast=forecast,
                    target_time_start=now + timedelta(hours=3),
                    target_time_end=now + timedelta(hours=6),
                    probability=test_level,
                    weather_factors=weather_factors,
                    notification_sent=False
                )

                # Send the test notification
                if notification_service.send_migraine_alert(migraine_prediction):
                    self.stdout.write(self.style.SUCCESS(f"✓ Sent test MIGRAINE {test_level} notification to {user.email}"))
                    migraine_prediction.notification_sent = True
                    migraine_prediction.save()
                    total_sent += 1
                else:
                    self.stdout.write(self.style.WARNING(f"✗ Failed to send test MIGRAINE notification to {user.email}"))

            # Create sinusitis test prediction if requested
            if test_type in ['sinusitis', 'both'] and test_level != 'NONE':
                sinusitis_prediction = SinusitisPrediction.objects.create(
                    user=user,
                    location=location,
                    forecast=forecast,
                    target_time_start=now + timedelta(hours=3),
                    target_time_end=now + timedelta(hours=6),
                    probability=test_level,
                    weather_factors=weather_factors,
                    notification_sent=False
                )

                # Send the test notification
                if notification_service.send_sinusitis_alert(sinusitis_prediction):
                    self.stdout.write(self.style.SUCCESS(f"✓ Sent test SINUSITIS {test_level} notification to {user.email}"))
                    sinusitis_prediction.notification_sent = True
                    sinusitis_prediction.save()
                    total_sent += 1
                else:
                    self.stdout.write(self.style.WARNING(f"✗ Failed to send test SINUSITIS notification to {user.email}"))

        if test_level == 'NONE':
            self.stdout.write(self.style.SUCCESS(f"[{timezone.now()}] TEST MODE: No notifications sent (test level = NONE)"))
        else:
            self.stdout.write(self.style.SUCCESS(f"[{timezone.now()}] TEST MODE completed. Total test notifications sent: {total_sent}"))
