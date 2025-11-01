from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from forecast.models import Location, WeatherForecast
from forecast.weather_service import WeatherService

import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Collect and store weather forecast data for all locations (Task 1 of decoupled pipeline)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--cleanup-hours",
            type=int,
            default=48,
            help="Delete forecasts older than this many hours (default: 48)",
        )
        parser.add_argument(
            "--skip-cleanup",
            action="store_true",
            help="Skip cleanup of old forecast data",
        )

    def handle(self, *args, **options):
        """
        Collect weather forecast data for all locations.

        This command:
        1. Fetches weather forecasts from the API for all locations
        2. Stores/updates forecast data in the database
        3. Cleans up old forecast data to prevent database bloat
        
        This is Task 1 of the decoupled pipeline architecture.
        Recommended schedule: Every 1-2 hours
        """
        start_time = timezone.now()
        self.stdout.write(
            self.style.SUCCESS(f"[{start_time}] Starting weather data collection...")
        )

        # Initialize weather service
        weather_service = WeatherService()

        # Get all locations
        locations = Location.objects.all()
        if not locations:
            self.stdout.write(self.style.WARNING("No locations found in database"))
            return

        self.stdout.write(f"Found {len(locations)} location(s) to update")

        # Collect forecasts for each location
        total_forecasts_created = 0
        total_forecasts_updated = 0
        errors = []

        for location in locations:
            try:
                self.stdout.write(f"\nProcessing location: {location} (User: {location.user.username})")
                
                # Fetch and store forecasts
                created, updated = weather_service.update_forecast_for_location_upsert(location)
                
                total_forecasts_created += created
                total_forecasts_updated += updated
                
                self.stdout.write(
                    f"  ✓ Created {created} new forecast(s), updated {updated} existing forecast(s)"
                )
                
            except Exception as e:
                error_msg = f"Error processing location {location}: {str(e)}"
                errors.append(error_msg)
                self.stdout.write(self.style.ERROR(f"  ✗ {error_msg}"))
                logger.error(error_msg, exc_info=True)

        # Cleanup old forecasts
        if not options["skip_cleanup"]:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Cleaning up old forecast data...")
            
            cleanup_hours = options["cleanup_hours"]
            cutoff_time = timezone.now() - timedelta(hours=cleanup_hours)
            
            old_forecasts = WeatherForecast.objects.filter(forecast_time__lt=cutoff_time)
            count = old_forecasts.count()
            
            if count > 0:
                old_forecasts.delete()
                self.stdout.write(
                    self.style.SUCCESS(f"  ✓ Deleted {count} forecast(s) older than {cleanup_hours} hours")
                )
            else:
                self.stdout.write("  No old forecasts to delete")

        # Summary
        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()
        
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("WEATHER DATA COLLECTION SUMMARY"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Locations processed: {len(locations)}")
        self.stdout.write(f"Forecasts created: {total_forecasts_created}")
        self.stdout.write(f"Forecasts updated: {total_forecasts_updated}")
        self.stdout.write(f"Errors: {len(errors)}")
        self.stdout.write(f"Duration: {duration:.2f} seconds")
        self.stdout.write(f"Completed at: {end_time}")
        
        if errors:
            self.stdout.write("\nErrors encountered:")
            for error in errors:
                self.stdout.write(self.style.ERROR(f"  - {error}"))
        
        self.stdout.write("=" * 60)
