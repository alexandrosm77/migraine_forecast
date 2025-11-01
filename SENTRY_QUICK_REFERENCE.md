# Sentry/GlitchTip Quick Reference

## Configuration

**GlitchTip Dashboard:** http://192.168.0.11:8001  
**DSN:** `http://da3f96ceb002454e85ac49a5f1916cd0@192.168.0.11:8001/1`

## Common Imports

```python
from sentry_sdk import (
    capture_message,      # Send custom messages
    capture_exception,    # Capture exceptions
    set_context,         # Add structured context
    set_tag,            # Add searchable tags
    set_user,           # Set user information
    add_breadcrumb,     # Add event trail
    start_transaction,  # Start performance transaction
    start_span,         # Start performance span
)
import logging
logger = logging.getLogger(__name__)
```

## Quick Commands

### Capture a Message
```python
capture_message("Something happened", level="info")  # info, warning, error
```

### Capture an Exception
```python
try:
    risky_operation()
except Exception as e:
    capture_exception(e)
```

### Add Context
```python
set_context("operation", {
    "type": "weather_update",
    "location": "Athens",
    "timestamp": datetime.now()
})
```

### Add Tags (for filtering)
```python
set_tag("environment", "production")
set_tag("feature", "predictions")
```

### Set User
```python
set_user({
    "id": user.id,
    "username": user.username,
    "email": user.email
})
```

### Add Breadcrumb
```python
add_breadcrumb(
    category="weather",
    message="Fetching weather data",
    level="info",
    data={"location_id": 123}
)
```

### Performance Monitoring
```python
# Transaction (top-level operation)
with start_transaction(op="task", name="generate_predictions"):
    # Your code here
    pass

# Span (sub-operation)
with start_span(op="db.query", description="Fetch user data"):
    users = User.objects.all()
```

## Common Patterns

### Pattern 1: API Call with Error Handling
```python
try:
    add_breadcrumb(category="api", message="Calling weather API")
    response = requests.get(api_url, timeout=30)
    response.raise_for_status()
except requests.RequestException as e:
    set_context("api_error", {
        "url": api_url,
        "timeout": 30,
        "status_code": getattr(e.response, 'status_code', None)
    })
    capture_exception(e)
    raise
```

### Pattern 2: Database Operation with Performance Tracking
```python
with start_span(op="db.query", description="Fetch predictions"):
    predictions = Prediction.objects.filter(
        user=user,
        timestamp__gte=start_date
    ).select_related('location')
```

### Pattern 3: Background Task Monitoring
```python
def handle(self, *args, **options):
    set_tag("cron_job", "collect_weather")
    
    try:
        result = perform_task()
        capture_message(f"Task completed: {result}", level="info")
    except Exception as e:
        capture_exception(e)
        raise
```

### Pattern 4: User Action Tracking
```python
@login_required
def my_view(request):
    set_user({
        "id": request.user.id,
        "username": request.user.username
    })
    
    add_breadcrumb(
        category="user_action",
        message="User performed action",
        level="info"
    )
    # Your view logic
```

### Pattern 5: Data Quality Check
```python
if abs(forecast - actual) > threshold:
    set_tag("data_quality", "anomaly")
    capture_message(
        f"Data anomaly detected: {abs(forecast - actual)}",
        level="warning"
    )
```

## Log Levels

- `debug` - Detailed information for debugging
- `info` - General informational messages
- `warning` - Warning messages (potential issues)
- `error` - Error messages (sent to Sentry automatically)
- `critical` - Critical issues (sent to Sentry automatically)

## Environment Variables

```bash
# Enable/disable Sentry
export SENTRY_ENABLED=true

# Set environment name
export SENTRY_ENVIRONMENT=production

# Adjust sample rates (0.0 to 1.0)
export SENTRY_TRACES_SAMPLE_RATE=0.1  # 10% of transactions
export SENTRY_PROFILES_SAMPLE_RATE=0.1  # 10% of transactions
```

## Testing

```bash
# Run test script
python test_sentry.py

# Check Django configuration
python manage.py check

# View logs
tail -f migraine_forecast.log
```

## GlitchTip Dashboard

1. **Issues** - View all errors and exceptions
2. **Performance** - View transaction performance
3. **Releases** - Track issues by release
4. **Alerts** - Configure alert rules

## Filtering in GlitchTip

Use tags to filter events:
- `cron_job:collect_weather` - Specific cron job
- `environment:production` - Production events only
- `user.id:123` - Events for specific user
- `data_quality:anomaly` - Data quality issues

## Best Practices

✅ **DO:**
- Add context to all manual captures
- Use tags for filtering
- Add breadcrumbs for complex flows
- Set user context in views
- Monitor critical paths
- Use appropriate log levels

❌ **DON'T:**
- Log sensitive data (passwords, tokens)
- Over-log (too many info messages)
- Ignore exceptions silently
- Forget to add context
- Use generic error messages

## Common Use Cases

| Use Case | Method | Example |
|----------|--------|---------|
| API failure | `capture_exception()` | Weather API timeout |
| Slow query | `start_span()` | Database query > 1s |
| User action | `add_breadcrumb()` | User created location |
| Data anomaly | `capture_message()` | Temperature > 50°C |
| Task completion | `capture_message()` | Cron job finished |
| Error with context | `set_context()` + `capture_exception()` | LLM prediction failed |

## Troubleshooting

**Events not appearing?**
1. Check `SENTRY_ENABLED=true`
2. Verify DSN is correct
3. Check network connectivity to GlitchTip
4. Look for errors in logs

**Too many events?**
1. Reduce sample rates
2. Filter out noisy errors
3. Adjust log levels
4. Use `before_send` hook

**Missing context?**
1. Add `set_context()` before capture
2. Add breadcrumbs throughout flow
3. Set user context early
4. Use tags for filtering

## Support

- **Documentation:** See `SENTRY_INTEGRATION.md`
- **Examples:** See `SENTRY_EXAMPLES.md`
- **Use Cases:** See `SENTRY_USE_CASES.md`
- **GlitchTip Docs:** https://glitchtip.com/documentation
- **Sentry SDK Docs:** https://docs.sentry.io/platforms/python/

## Quick Test

```python
# Test in Django shell
python manage.py shell

from sentry_sdk import capture_message
capture_message("Test from Django shell", level="info")

# Check GlitchTip dashboard
# http://192.168.0.11:8001
```

