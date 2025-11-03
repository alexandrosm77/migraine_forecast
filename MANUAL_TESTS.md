# Manual Test Scripts

This directory contains manual test scripts that are **excluded from automatic test discovery** to prevent them from running during normal unit test execution.

## Available Manual Tests

### 1. `manual_test_sentry.py`

**Purpose**: Verify Sentry/GlitchTip integration is working correctly.

**Usage**:
```bash
python manual_test_sentry.py
```

**What it tests**:
- Basic message capture
- Error logging integration
- Exception handling
- Context and tags
- Breadcrumbs
- Performance monitoring

**When to run**:
- After setting up or modifying Sentry/GlitchTip configuration
- When troubleshooting error tracking issues
- To verify alerts are being sent correctly

---

### 2. `manual_test_sentry_alerts.py`

**Purpose**: Trigger various types of alerts to test your GlitchTip alert configuration.

**Usage**:
```bash
python manual_test_sentry_alerts.py
```

**What it tests**:
- Cron job error alerts
- API failure alerts
- Database error alerts
- High error rate scenarios
- Performance degradation alerts
- Custom business logic alerts

**When to run**:
- After configuring alert rules in GlitchTip
- To verify alert notifications (email, webhooks, etc.)
- When testing alert thresholds

---

## Why These Are Excluded from Automatic Tests

These files are named with the `manual_test_` prefix instead of `test_` to prevent Django's test discovery from automatically running them during:

```bash
python manage.py test
```

**Reasons for exclusion**:
1. **External Dependencies**: They require a running GlitchTip/Sentry instance
2. **Side Effects**: They send real alerts and create events in your monitoring dashboard
3. **Manual Verification**: They require human verification of the results in the GlitchTip UI
4. **Not Unit Tests**: They are integration/smoke tests, not unit tests

---

## Running Automatic Unit Tests

To run the actual unit test suite (which excludes these manual tests):

```bash
# Run all unit tests
python manage.py test

# Run specific app tests
python manage.py test forecast.tests

# Run with verbose output
python manage.py test --verbosity=2

# Run specific test class
python manage.py test forecast.tests.NotificationServiceTest
```

The unit test suite currently contains **58 tests** covering:
- Models (Location, WeatherForecast, Predictions, UserHealthProfile, etc.)
- Services (Weather, Prediction, Notification, LLM)
- Forms (UserHealthProfileForm validation)
- API clients (OpenMeteo, LLM)
- Utility functions

---

## Best Practices

1. **Always run unit tests** before committing code:
   ```bash
   python manage.py test
   ```

2. **Run manual tests** only when needed:
   - After configuration changes
   - When troubleshooting specific issues
   - During initial setup

3. **Check GlitchTip dashboard** after running manual tests to verify events were captured

4. **Don't commit** manual test results or temporary test data

---

## Related Documentation

- `SENTRY_INTEGRATION.md` - Sentry/GlitchTip setup and configuration
- `SENTRY_EXAMPLES.md` - Code examples for using Sentry in the application
- `SENTRY_QUICK_REFERENCE.md` - Quick reference for common Sentry operations
- `SENTRY_USE_CASES.md` - Real-world use cases and scenarios

