from django.core.management.base import BaseCommand
from django.utils import timezone

from forecast.models import Location
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

    def handle(self, *args, **options):
        """
        Django management command to check migraine and sinusitis probability and send notifications.
        This can be run as a scheduled task (e.g., cron job) to:
        1. Update weather forecasts for all locations
        2. Generate migraine and sinusitis predictions
        3. Send email notifications for high-risk predictions
        """
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

                # Generate migraine prediction
                self.stdout.write(f"Generating migraine prediction for {location}...")
                probability, prediction = migraine_prediction_service.predict_migraine_probability(
                    location=location,
                    user=location.user
                )
                migraine_predictions[location.id] = {
                    'probability': probability,
                    'prediction': prediction
                }
                if prediction:
                    self.stdout.write(f"Migraine Prediction: {probability} probability for {location}")
                else:
                    self.stdout.write(self.style.WARNING(f"No migraine prediction could be made for {location}"))

                # Generate sinusitis prediction
                self.stdout.write(f"Generating sinusitis prediction for {location}...")
                sin_probability, sin_prediction = sinusitis_prediction_service.predict_sinusitis_probability(
                    location=location,
                    user=location.user
                )
                sinusitis_predictions[location.id] = {
                    'probability': sin_probability,
                    'prediction': sin_prediction
                }
                if sin_prediction:
                    self.stdout.write(f"Sinusitis Prediction: {sin_probability} probability for {location}")
                else:
                    self.stdout.write(self.style.WARNING(f"No sinusitis prediction could be made for {location}"))

        # Send notifications
        self.stdout.write("Checking and sending migraine notifications...")
        migraine_notifications_sent = notification_service.check_and_send_notifications(migraine_predictions)
        self.stdout.write(f"Sent {migraine_notifications_sent} migraine notifications")

        self.stdout.write("Checking and sending sinusitis notifications...")
        sinusitis_notifications_sent = notification_service.check_and_send_sinusitis_notifications(sinusitis_predictions)
        self.stdout.write(f"Sent {sinusitis_notifications_sent} sinusitis notifications")

        total_notifications = migraine_notifications_sent + sinusitis_notifications_sent
        self.stdout.write(self.style.SUCCESS(f"[{timezone.now()}] Check completed. Total notifications sent: {total_notifications}"))
