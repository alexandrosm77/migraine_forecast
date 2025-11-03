#!/usr/bin/env python
"""
Manual test script to trigger various Sentry/GlitchTip alerts.
This helps verify that your alert configuration is working correctly.

This file is excluded from automatic test discovery (does not match test*.py pattern).

Usage:
    python manual_test_sentry_alerts.py
"""

import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "migraine_project.settings")
django.setup()

import sentry_sdk  # noqa: E402
from sentry_sdk import capture_exception, capture_message, set_context, set_tag, add_breadcrumb  # noqa: E402


def test_cron_job_error():
    """Simulate a cron job error"""
    print("\n1. Testing Cron Job Error Alert...")

    set_tag("cron_job", "test_job")
    set_tag("task", "test")

    add_breadcrumb(category="cron", message="Starting test cron job", level="info")

    try:
        # Simulate a critical error in a cron job
        raise Exception("Simulated cron job failure - database connection lost")
    except Exception as e:
        set_context("cron_error", {"job_name": "test_job", "error_type": "database_connection", "severity": "critical"})
        capture_exception(e)
        print("   ✓ Cron job error sent to GlitchTip")


def test_weather_api_error():
    """Simulate weather API errors"""
    print("\n2. Testing Weather API Error Alert...")

    set_tag("api", "weather")
    set_tag("operation", "fetch_forecast")

    # Simulate multiple API failures
    for i in range(3):
        add_breadcrumb(category="http", message=f"Weather API call attempt {i+1}", level="info")

        try:
            raise ConnectionError(f"Weather API timeout - attempt {i+1}")
        except Exception as e:
            set_context(
                "weather_api_error",
                {
                    "attempt": i + 1,
                    "api_endpoint": "https://api.open-meteo.com/v1/forecast",
                    "timeout": 10,
                    "status_code": None,
                },
            )
            capture_exception(e)

    print("   ✓ Weather API errors sent to GlitchTip (3 events)")


def test_llm_prediction_error():
    """Simulate LLM prediction errors"""
    print("\n3. Testing LLM Prediction Error Alert...")

    set_tag("llm_model", "granite-3.0-8b-instruct")
    set_tag("prediction_type", "migraine")

    add_breadcrumb(category="llm", message="Attempting LLM prediction", level="info")

    try:
        raise TimeoutError("LLM API timeout after 30 seconds")
    except Exception as e:
        set_context(
            "llm_error",
            {
                "model": "granite-3.0-8b-instruct",
                "base_url": "http://192.168.0.11:8000/v1",
                "timeout": 30,
                "prediction_type": "migraine",
            },
        )
        capture_exception(e)
        print("   ✓ LLM prediction error sent to GlitchTip")


def test_email_notification_error():
    """Simulate email sending errors"""
    print("\n4. Testing Email Notification Error Alert...")

    set_tag("email_type", "migraine_alert")
    set_tag("risk_level", "HIGH")

    add_breadcrumb(category="email", message="Attempting to send migraine alert", level="info")

    try:
        raise ConnectionRefusedError("SMTP connection refused - server not responding")
    except Exception as e:
        set_context(
            "email_error",
            {
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "recipient": "user@example.com",
                "subject": "Migraine Alert: HIGH Risk Forecast",
                "error_type": "connection_refused",
            },
        )
        capture_exception(e)
        print("   ✓ Email notification error sent to GlitchTip")


def test_high_error_rate():
    """Simulate a high error rate (error spike)"""
    print("\n5. Testing High Error Rate Alert...")

    # Generate 15 errors in quick succession
    for i in range(15):
        try:
            raise RuntimeError(f"Simulated application error #{i+1}")
        except Exception as e:
            set_context("error_spike", {"error_number": i + 1, "total_errors": 15, "time_window": "1 minute"})
            capture_exception(e)

    print("   ✓ High error rate simulation sent to GlitchTip (15 events)")


def test_performance_issue():
    """Simulate performance degradation"""
    print("\n6. Testing Performance Issue Alert...")

    capture_message("Slow API response detected: Weather API took 45 seconds to respond", level="warning")

    set_context(
        "performance_issue",
        {"operation": "weather_api_call", "duration_seconds": 45, "threshold_seconds": 30, "location": "London, UK"},
    )

    print("   ✓ Performance issue sent to GlitchTip")


def test_invalid_llm_response():
    """Simulate invalid LLM response"""
    print("\n7. Testing Invalid LLM Response Alert...")

    set_tag("llm_model", "granite-3.0-8b-instruct")
    set_tag("prediction_type", "migraine")

    capture_message("LLM returned invalid probability level: EXTREME (expected: LOW, MEDIUM, HIGH)", level="warning")

    set_context(
        "invalid_llm_response",
        {
            "model": "granite-3.0-8b-instruct",
            "expected_values": ["LOW", "MEDIUM", "HIGH"],
            "received_value": "EXTREME",
            "location": "London, UK",
        },
    )

    print("   ✓ Invalid LLM response sent to GlitchTip")


def test_database_error():
    """Simulate database errors"""
    print("\n8. Testing Database Error Alert...")

    try:
        raise Exception("Database query timeout: SELECT * FROM forecast_weatherforecast")
    except Exception as e:
        set_context(
            "database_error",
            {
                "query": "SELECT * FROM forecast_weatherforecast",
                "timeout": 30,
                "database": "SQLite",
                "operation": "fetch_forecasts",
            },
        )
        capture_exception(e)
        print("   ✓ Database error sent to GlitchTip")


def test_high_risk_prediction_alert():
    """Simulate high-risk prediction alert"""
    print("\n9. Testing High-Risk Prediction Alert...")

    set_tag("cron_job", "generate_predictions")
    set_tag("high_risk_predictions", 5)

    capture_message("Generated 5 HIGH risk prediction(s) - unusual spike detected", level="info")

    set_context(
        "high_risk_alert",
        {"high_risk_count": 5, "medium_risk_count": 2, "low_risk_count": 1, "total_predictions": 8, "threshold": 3},
    )

    print("   ✓ High-risk prediction alert sent to GlitchTip")


def main():
    print("=" * 60)
    print("GlitchTip Alert Testing Script")
    print("=" * 60)
    print("\nThis script will trigger various alerts to test your")
    print("GlitchTip alert configuration.")
    print("\nWARNING: This will generate test errors in your GlitchTip")
    print("dashboard. Make sure you're ready to receive test alerts.")
    print("=" * 60)

    response = input("\nContinue? (yes/no): ")
    if response.lower() not in ["yes", "y"]:
        print("Aborted.")
        return

    # Run all tests
    test_cron_job_error()
    test_weather_api_error()
    test_llm_prediction_error()
    test_email_notification_error()
    test_high_error_rate()
    test_performance_issue()
    test_invalid_llm_response()
    test_database_error()
    test_high_risk_prediction_alert()

    print("\n" + "=" * 60)
    print("All test alerts sent!")
    print("=" * 60)
    print("\nCheck your GlitchTip dashboard at:")
    print("http://192.168.0.11:8001")
    print("\nYou should see:")
    print("  - 9 different types of events")
    print("  - Multiple errors and warnings")
    print("  - Rich context data for each event")
    print("\nIf you configured email alerts, you should receive")
    print("notifications for the triggered conditions.")
    print("=" * 60)

    # Flush events
    print("\nFlushing events to GlitchTip...")
    sentry_sdk.flush(timeout=5)
    print("Done!")


if __name__ == "__main__":
    main()
