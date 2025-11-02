from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from forecast.models import Location, WeatherForecast
from forecast.weather_service import WeatherService

import logging
from sentry_sdk import capture_exception, capture_message, set_context, add_breadcrumb, start_transaction, set_tag

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
        # Start transaction for cron job monitoring
        with start_transaction(op="cron.job", name="collect_weather_data"):
            set_tag("cron_job", "collect_weather_data")
            set_tag("task", "weather_collection")

            start_time = timezone.now()

            # Log to both stdout and logger for consistent ordering
            start_msg = f"Starting weather data collection..."
            self.stdout.write(self.style.SUCCESS(f"[{start_time}] {start_msg}"))
            logger.info(start_msg)

            add_breadcrumb(
                category="cron",
                message="Weather data collection started",
                level="info",
                data={"start_time": str(start_time)}
            )

            # Initialize weather service
            weather_service = WeatherService()

            # Get all locations
            locations = Location.objects.all()
            if not locations:
                self.stdout.write(self.style.WARNING("No locations found in database"))
                capture_message("No locations found for weather data collection", level="warning")
                return

            self.stdout.write(f"Found {len(locations)} location(s) to update")

            add_breadcrumb(
                category="cron",
                message=f"Processing {len(locations)} locations",
                level="info",
                data={"location_count": len(locations)}
            )

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

                    # Capture exception with context
                    set_context("weather_collection_error", {
                        "location": str(location),
                        "location_id": location.id,
                        "user": location.user.username
                    })
                    capture_exception(e)

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

            # Send summary to Sentry
            summary_data = {
                "locations_processed": len(locations),
                "forecasts_created": total_forecasts_created,
                "forecasts_updated": total_forecasts_updated,
                "errors": len(errors),
                "duration_seconds": duration,
                "completed_at": str(end_time)
            }

            add_breadcrumb(
                category="cron",
                message="Weather data collection completed",
                level="info",
                data=summary_data
            )

            if errors:
                self.stdout.write("\nErrors encountered:")
                for error in errors:
                    self.stdout.write(self.style.ERROR(f"  - {error}"))

                # Capture summary message with errors
                capture_message(
                    f"Weather data collection completed with {len(errors)} error(s)",
                    level="error" if len(errors) > len(locations) / 2 else "warning"
                )
            else:
                # Capture successful completion
                capture_message(
                    f"Weather data collection completed successfully: {total_forecasts_created} created, {total_forecasts_updated} updated",
                    level="info"
                )

            self.stdout.write("=" * 60)
