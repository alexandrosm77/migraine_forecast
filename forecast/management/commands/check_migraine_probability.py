from django.core.management.base import BaseCommand
from django.utils import timezone

from forecast.models import Location
from forecast.weather_service import WeatherService
from forecast.prediction_service import MigrainePredictionService
from forecast.notification_service import NotificationService

class Command(BaseCommand):
    help = 'Check migraine probability and send notifications'

    def add_arguments(self, parser):
        parser.add_argument(
            '--notify-only',
            action='store_true',
            help='Only send notifications without updating forecasts',
        )

    def handle(self, *args, **options):
        """
        Django management command to check migraine probability and send notifications.
        This can be run as a scheduled task (e.g., cron job) to:
        1. Update weather forecasts for all locations
        2. Generate migraine predictions
        3. Send email notifications for high-risk predictions
        """
        self.stdout.write(self.style.SUCCESS(f"[{timezone.now()}] Starting migraine probability check..."))
        
        # Initialize services
        weather_service = WeatherService()
        prediction_service = MigrainePredictionService()
        notification_service = NotificationService()
        
        # Get all locations
        locations = Location.objects.all()
        self.stdout.write(f"Found {len(locations)} locations to check")

        predictions = {}
        
        if not options['notify_only']:
            # Update forecasts for all locations
            for location in locations:
                self.stdout.write(f"Updating forecast for {location}...")
                forecasts = weather_service.update_forecast_for_location(location)
                self.stdout.write(f"Created {len(forecasts)} forecast entries")
                
                # Generate prediction
                self.stdout.write(f"Generating prediction for {location}...")
                probability, prediction = prediction_service.predict_migraine_probability(
                    location=location,
                    user=location.user
                )
                predictions[location.id] = {
                    'probability': probability,
                    'prediction': prediction
                }
                if prediction:
                    self.stdout.write(f"Prediction: {probability} probability for {location}")
                else:
                    self.stdout.write(self.style.WARNING(f"No prediction could be made for {location}"))
        
        # Send notifications
        self.stdout.write("Checking and sending notifications...")
        notifications_sent = notification_service.check_and_send_notifications(predictions)
        self.stdout.write(f"Sent {notifications_sent} notifications")
        
        self.stdout.write(self.style.SUCCESS(f"[{timezone.now()}] Migraine probability check completed"))
