# Sentry Integration Examples for Migraine Forecast

This document provides practical examples of how to integrate Sentry/GlitchTip monitoring into the migraine forecast application.

## Example 1: Enhanced Weather Service with Sentry

Here's how to add comprehensive monitoring to the weather service:

```python
# forecast/weather_service.py
from .models import Location, WeatherForecast
from .weather_api import OpenMeteoClient
import logging
from sentry_sdk import capture_exception, set_context, add_breadcrumb, start_transaction

logger = logging.getLogger(__name__)


class WeatherService:
    """
    Service for fetching and storing weather forecast data.
    """

    def __init__(self):
        """Initialize the weather service with the Open-Meteo client."""
        self.api_client = OpenMeteoClient()

    def update_forecast_for_location(self, location):
        """
        Update weather forecast for a specific location.
        
        Args:
            location (Location): The location model instance
            
        Returns:
            list: List of created WeatherForecast instances
        """
        # Start a transaction for performance monitoring
        with start_transaction(op="weather.update", name=f"update_forecast_{location.name}"):
            logger.info(f"Starting update_forecast_for_location for location: {location}")
            
            # Add breadcrumb for debugging
            add_breadcrumb(
                category="weather",
                message=f"Fetching forecast for {location.name}",
                level="info",
                data={
                    "location_id": location.id,
                    "latitude": location.latitude,
                    "longitude": location.longitude
                }
            )
            
            try:
                # Fetch forecast data from the API
                forecast_data = self.api_client.get_forecast(
                    latitude=location.latitude,
                    longitude=location.longitude,
                    days=3
                )
                
                if not forecast_data:
                    logger.error(f"Failed to fetch forecast data for location: {location}")
                    
                    # Add context for debugging
                    set_context("weather_fetch_failure", {
                        "location": location.name,
                        "latitude": location.latitude,
                        "longitude": location.longitude,
                        "api_client": "OpenMeteo"
                    })
                    
                    return []
                
                # Parse the forecast data
                parsed_data = self.api_client.parse_forecast_data(forecast_data, location)
                
                # Store the forecast data in the database
                created_forecasts = []
                for entry in parsed_data:
                    forecast = WeatherForecast.objects.create(**entry)
                    created_forecasts.append(forecast)
                
                logger.info(f"Created {len(created_forecasts)} forecast entries for {location}")
                return created_forecasts
                
            except Exception as e:
                # Capture the exception with context
                set_context("weather_error", {
                    "location": location.name,
                    "location_id": location.id,
                    "operation": "update_forecast"
                })
                capture_exception(e)
                logger.error(f"Error updating forecast for {location}: {str(e)}")
                raise
```

## Example 2: LLM Prediction Service with Monitoring

```python
# forecast/prediction_service.py
from sentry_sdk import capture_exception, set_tag, add_breadcrumb, start_span
import logging

logger = logging.getLogger(__name__)


def generate_prediction_with_llm(weather_data, user_profile):
    """Generate migraine prediction using LLM with Sentry monitoring."""
    
    # Add breadcrumbs for the prediction flow
    add_breadcrumb(
        category="prediction",
        message="Starting LLM prediction",
        level="info",
        data={
            "user_id": user_profile.user.id,
            "weather_points": len(weather_data)
        }
    )
    
    # Tag this event for filtering
    set_tag("prediction_type", "migraine")
    set_tag("llm_enabled", "true")
    
    try:
        # Get LLM configuration
        llm_config = LLMConfiguration.get_active_config()
        set_tag("llm_model", llm_config.model)
        
        add_breadcrumb(
            category="llm",
            message=f"Using LLM model: {llm_config.model}",
            level="info"
        )
        
        # Create LLM client and generate prediction
        with start_span(op="llm.predict", description="LLM prediction generation"):
            llm_client = LLMClient(llm_config)
            prediction = llm_client.predict(weather_data, user_profile)
        
        add_breadcrumb(
            category="prediction",
            message="LLM prediction completed",
            level="info",
            data={"probability": prediction.get("probability")}
        )
        
        return prediction
        
    except Exception as e:
        set_context("llm_prediction_error", {
            "user_id": user_profile.user.id,
            "model": llm_config.model,
            "base_url": llm_config.base_url,
            "weather_data_points": len(weather_data)
        })
        capture_exception(e)
        logger.error(f"LLM prediction failed: {str(e)}")
        raise
```

## Example 3: Management Command with Monitoring

```python
# forecast/management/commands/collect_weather_data.py
from django.core.management.base import BaseCommand
from forecast.models import Location
from forecast.weather_service import WeatherService
from sentry_sdk import capture_message, capture_exception, set_tag, add_breadcrumb
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Collect weather data for all active locations"

    def handle(self, *args, **options):
        # Tag this as a cron job
        set_tag("cron_job", "collect_weather_data")
        set_tag("command", "management_command")
        
        add_breadcrumb(
            category="cron",
            message="Starting weather data collection",
            level="info"
        )
        
        weather_service = WeatherService()
        locations = Location.objects.filter(is_active=True)
        
        success_count = 0
        error_count = 0
        
        for location in locations:
            try:
                add_breadcrumb(
                    category="weather",
                    message=f"Processing location: {location.name}",
                    level="info",
                    data={"location_id": location.id}
                )
                
                weather_service.update_forecast_for_location(location)
                success_count += 1
                
            except Exception as e:
                error_count += 1
                set_context("location_error", {
                    "location_id": location.id,
                    "location_name": location.name
                })
                capture_exception(e)
                logger.error(f"Failed to update weather for {location.name}: {str(e)}")
        
        # Send summary message
        summary = f"Weather collection completed: {success_count} succeeded, {error_count} failed"
        
        if error_count > 0:
            capture_message(summary, level="warning")
        else:
            capture_message(summary, level="info")
        
        self.stdout.write(self.style.SUCCESS(summary))
```

## Example 4: View with User Context

```python
# forecast/views.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from sentry_sdk import set_user, add_breadcrumb, capture_message
import logging

logger = logging.getLogger(__name__)


@login_required
def create_location(request):
    """Create a new location with Sentry monitoring."""
    
    # Set user context for all events in this request
    set_user({
        "id": request.user.id,
        "username": request.user.username,
        "email": request.user.email
    })
    
    if request.method == "POST":
        form = LocationForm(request.POST)
        
        add_breadcrumb(
            category="user_action",
            message="User submitting location form",
            level="info",
            data={"form_valid": form.is_valid()}
        )
        
        if form.is_valid():
            location = form.save(commit=False)
            location.user = request.user
            location.save()
            
            # Track successful location creation
            capture_message(
                f"New location created: {location.name}",
                level="info"
            )
            
            add_breadcrumb(
                category="user_action",
                message=f"Location created: {location.name}",
                level="info",
                data={
                    "location_id": location.id,
                    "latitude": location.latitude,
                    "longitude": location.longitude
                }
            )
            
            return redirect("forecast:location_detail", pk=location.pk)
    else:
        form = LocationForm()
    
    return render(request, "forecast/location_form.html", {"form": form})
```

## Example 5: Email Notification with Error Tracking

```python
# forecast/notification_service.py
from django.core.mail import send_mail
from django.conf import settings
from sentry_sdk import capture_exception, set_context, add_breadcrumb
import logging

logger = logging.getLogger(__name__)


def send_migraine_alert(user, prediction):
    """Send migraine alert email with Sentry monitoring."""
    
    add_breadcrumb(
        category="notification",
        message="Preparing to send migraine alert",
        level="info",
        data={
            "user_id": user.id,
            "prediction_probability": prediction.probability
        }
    )
    
    subject = f"High Migraine Risk Alert - {prediction.location.name}"
    message = f"""
    Hello {user.username},
    
    Our prediction system has detected a high probability ({prediction.probability}%) 
    of migraine conditions for {prediction.location.name}.
    
    Time: {prediction.timestamp}
    
    Please take necessary precautions.
    """
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False
        )
        
        add_breadcrumb(
            category="notification",
            message="Email sent successfully",
            level="info",
            data={"recipient": user.email}
        )
        
        logger.info(f"Migraine alert sent to {user.email}")
        
    except Exception as e:
        set_context("email_error", {
            "recipient": user.email,
            "subject": subject,
            "smtp_host": settings.EMAIL_HOST,
            "smtp_port": settings.EMAIL_PORT,
            "prediction_id": prediction.id
        })
        capture_exception(e)
        logger.error(f"Failed to send email to {user.email}: {str(e)}")
        raise
```

## Example 6: Data Quality Monitoring

```python
# forecast/comparison_service.py
from sentry_sdk import capture_message, set_tag, add_breadcrumb
import logging

logger = logging.getLogger(__name__)


def compare_forecast_vs_actual(forecast, actual):
    """Compare forecast vs actual data with quality monitoring."""
    
    temp_diff = abs(forecast.temperature - actual.temperature)
    pressure_diff = abs(forecast.pressure - actual.pressure)
    
    # Monitor data quality issues
    if temp_diff > 10:
        set_tag("data_quality", "temperature_anomaly")
        add_breadcrumb(
            category="data_quality",
            message="Large temperature discrepancy detected",
            level="warning",
            data={
                "forecast_temp": forecast.temperature,
                "actual_temp": actual.temperature,
                "difference": temp_diff
            }
        )
        capture_message(
            f"Temperature anomaly: {temp_diff}°C difference",
            level="warning"
        )
    
    if pressure_diff > 50:
        set_tag("data_quality", "pressure_anomaly")
        capture_message(
            f"Pressure anomaly: {pressure_diff} hPa difference",
            level="warning"
        )
    
    return {
        "temperature_diff": temp_diff,
        "pressure_diff": pressure_diff,
        "quality_ok": temp_diff <= 10 and pressure_diff <= 50
    }
```

## Example 7: Performance Monitoring for Database Queries

```python
# forecast/views.py
from sentry_sdk import start_span
from django.db.models import Prefetch


def get_user_predictions_optimized(user, days=7):
    """Get user predictions with performance monitoring."""
    
    with start_span(op="db.query", description="Fetch user predictions"):
        predictions = Prediction.objects.filter(
            location__user=user,
            timestamp__gte=timezone.now() - timedelta(days=days)
        ).select_related(
            'location',
            'weather_forecast'
        ).prefetch_related(
            'location__user'
        ).order_by('-timestamp')
    
    return predictions
```

## Testing These Examples

1. Run the test script to verify basic integration:
   ```bash
   python test_sentry.py
   ```

2. Trigger a weather update to see real monitoring:
   ```bash
   python manage.py collect_weather_data
   ```

3. Check your GlitchTip dashboard at http://192.168.0.11:8001

## Key Takeaways

1. **Always add context** - Use `set_context()` to add relevant data
2. **Use breadcrumbs** - Track the flow of operations with `add_breadcrumb()`
3. **Tag events** - Use `set_tag()` for easy filtering in GlitchTip
4. **Monitor performance** - Use `start_transaction()` and `start_span()` for slow operations
5. **Capture exceptions** - Use `capture_exception()` for handled errors
6. **Track user actions** - Use `set_user()` to associate events with users

