# Sentry/GlitchTip Integration Guide

## Overview

This application is configured to use GlitchTip (a Sentry-compatible error tracking system) for comprehensive error monitoring, performance tracking, and application observability.

**GlitchTip Instance:** http://192.168.0.11:8001

## Configuration

### Environment Variables

The following environment variables can be used to configure Sentry/GlitchTip:

```bash
# Required
SENTRY_DSN=http://da3f96ceb002454e85ac49a5f1916cd0@192.168.0.11:8001/1

# Optional (with defaults)
SENTRY_ENABLED=true                    # Enable/disable Sentry (true/false)
SENTRY_ENVIRONMENT=development         # Environment name (development/staging/production)
SENTRY_TRACES_SAMPLE_RATE=1.0         # Performance monitoring sample rate (0.0-1.0)
SENTRY_PROFILES_SAMPLE_RATE=1.0       # Profiling sample rate (0.0-1.0)
```

### Integrations Enabled

1. **Django Integration** - Automatic Django framework monitoring
   - URL transaction tracking
   - Middleware span tracking
   - Django signals monitoring
   - Cache operation tracking

2. **Logging Integration** - Python logging integration
   - Captures ERROR level and above logs automatically
   - Sends them as events to GlitchTip
   - Preserves log context and breadcrumbs

## What Gets Tracked Automatically

### 1. Unhandled Exceptions
All unhandled exceptions in Django views, middleware, and background tasks are automatically captured with full stack traces.

### 2. Error Logs
Any log message at ERROR level or above is automatically sent to GlitchTip:

```python
import logging
logger = logging.getLogger(__name__)

logger.error("Something went wrong")  # Automatically sent to GlitchTip
logger.critical("Critical issue")     # Automatically sent to GlitchTip
```

### 3. Performance Monitoring
- HTTP request/response times
- Database query performance
- Cache operation performance
- Middleware execution times

### 4. User Context
- User ID and username (if authenticated)
- IP address
- User agent
- Request data

## Manual Event Capture

### Capture Custom Messages

```python
from sentry_sdk import capture_message

capture_message("User completed migraine prediction", level="info")
```

### Capture Exceptions Manually

```python
from sentry_sdk import capture_exception

try:
    # Your code
    result = risky_operation()
except Exception as e:
    capture_exception(e)
    # Handle the error gracefully
```

### Add Context to Events

```python
from sentry_sdk import set_context, set_tag, set_user

# Add tags for filtering
set_tag("prediction_type", "migraine")
set_tag("location", "Athens")

# Add structured context
set_context("weather_data", {
    "temperature": 25.5,
    "pressure": 1013,
    "humidity": 65
})

# Add user information
set_user({
    "id": user.id,
    "email": user.email,
    "username": user.username
})
```

### Add Breadcrumbs (Event Trail)

```python
from sentry_sdk import add_breadcrumb

add_breadcrumb(
    category="weather",
    message="Fetching weather data for location",
    level="info",
    data={"location_id": location.id}
)
```

## Use Cases for Migraine Forecast App

### 1. Weather API Failures

Track when weather API calls fail:

```python
# In weather_service.py
import logging
from sentry_sdk import capture_exception, set_context

logger = logging.getLogger(__name__)

try:
    weather_data = fetch_weather_from_api(location)
except requests.RequestException as e:
    set_context("weather_api", {
        "location": location.name,
        "api_url": api_url,
        "timeout": timeout
    })
    capture_exception(e)
    logger.error(f"Weather API failed for {location.name}")
```

### 2. LLM Prediction Failures

Monitor LLM prediction errors:

```python
# In prediction_service.py
from sentry_sdk import capture_exception, set_tag, add_breadcrumb

add_breadcrumb(
    category="llm",
    message="Starting LLM prediction",
    data={"model": llm_config.model}
)

try:
    prediction = llm_client.predict(weather_data)
except Exception as e:
    set_tag("llm_model", llm_config.model)
    set_tag("prediction_failed", "true")
    capture_exception(e)
```

### 3. Email Notification Failures

Track email sending issues:

```python
# In notification_service.py
from sentry_sdk import capture_message, set_context

try:
    send_mail(subject, message, from_email, [user.email])
except Exception as e:
    set_context("email", {
        "recipient": user.email,
        "subject": subject,
        "smtp_host": settings.EMAIL_HOST
    })
    capture_exception(e)
```

### 4. Data Quality Issues

Monitor data quality problems:

```python
# In comparison_service.py
from sentry_sdk import capture_message, set_tag

if abs(forecast_temp - actual_temp) > 10:
    set_tag("data_quality", "anomaly")
    capture_message(
        f"Large temperature discrepancy detected: {abs(forecast_temp - actual_temp)}°C",
        level="warning"
    )
```

### 5. Performance Monitoring

Track slow operations:

```python
from sentry_sdk import start_transaction

with start_transaction(op="task", name="generate_predictions"):
    # Your prediction generation code
    predictions = generate_all_predictions()
```

### 6. Cron Job Monitoring

Monitor scheduled tasks:

```python
# In management commands
from sentry_sdk import capture_message, set_tag

class Command(BaseCommand):
    def handle(self, *args, **options):
        set_tag("cron_job", "collect_weather_data")
        
        try:
            # Your cron job logic
            result = collect_weather_data()
            capture_message(
                f"Weather data collection completed: {result['count']} locations",
                level="info"
            )
        except Exception as e:
            capture_exception(e)
            raise
```

### 7. User Behavior Tracking

Track important user actions:

```python
# In views.py
from sentry_sdk import add_breadcrumb, set_user

def create_location(request):
    set_user({"id": request.user.id, "username": request.user.username})
    
    add_breadcrumb(
        category="user_action",
        message="User creating new location",
        level="info"
    )
    
    # Create location logic
```

### 8. Database Query Performance

Monitor slow queries:

```python
from sentry_sdk import start_span

with start_span(op="db.query", description="Fetch predictions for user"):
    predictions = Prediction.objects.filter(
        location__user=user,
        timestamp__gte=start_date
    ).select_related('location')
```

## Testing the Integration

Run the test script to verify the integration:

```bash
python test_sentry.py
```

This will send test events to your GlitchTip instance. Check the dashboard at http://192.168.0.11:8001 to see the events.

## Viewing Events in GlitchTip

1. Navigate to http://192.168.0.11:8001
2. Log in to your GlitchTip account
3. Select your project
4. View:
   - **Issues**: All errors and exceptions
   - **Performance**: Transaction and performance data
   - **Releases**: Track issues by release version (if configured)

## Filtering and Searching

Use tags to filter events in GlitchTip:
- `prediction_type`: migraine, sinusitis, etc.
- `location`: Location name
- `llm_model`: Which LLM model was used
- `cron_job`: Which scheduled task
- `data_quality`: Data quality issues

## Best Practices

1. **Don't Over-Log**: Only capture ERROR level and above for automatic logging
2. **Add Context**: Always add relevant context to manual captures
3. **Use Tags**: Tag events for easy filtering and searching
4. **Breadcrumbs**: Add breadcrumbs for complex operations to understand the event trail
5. **Sample Rates**: Adjust sample rates in production to control volume and costs
6. **Sensitive Data**: Be careful not to log sensitive user data (passwords, tokens, etc.)

## Disabling Sentry

To disable Sentry/GlitchTip:

```bash
export SENTRY_ENABLED=false
```

Or in your environment configuration file.

## Production Recommendations

For production deployment:

1. Set `SENTRY_ENVIRONMENT=production`
2. Adjust sample rates based on traffic:
   ```bash
   SENTRY_TRACES_SAMPLE_RATE=0.1  # 10% of transactions
   SENTRY_PROFILES_SAMPLE_RATE=0.1  # 10% of transactions
   ```
3. Configure release tracking to track which version caused issues
4. Set up alerts in GlitchTip for critical errors
5. Review and triage issues regularly

## Additional Resources

- [Sentry Python SDK Documentation](https://docs.sentry.io/platforms/python/)
- [GlitchTip Documentation](https://glitchtip.com/documentation)
- [Django Integration Guide](https://docs.sentry.io/platforms/python/guides/django/)

