#!/usr/bin/env python
"""
Manual test script to verify Sentry/GlitchTip integration.
Run this script manually to send test events to your GlitchTip instance.

This file is excluded from automatic test discovery (does not match test*.py pattern).

Usage:
    python manual_test_sentry.py
"""
import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "migraine_project.settings")
django.setup()

import logging  # noqa: E402
from sentry_sdk import capture_message, capture_exception, set_tag, set_context  # noqa: E402

logger = logging.getLogger(__name__)


def test_basic_message():
    """Test basic message capture"""
    print("1. Testing basic message capture...")
    capture_message("Test message from migraine_forecast app", level="info")
    print("   ✓ Message sent to Sentry/GlitchTip")


def test_error_logging():
    """Test error logging integration"""
    print("\n2. Testing error logging...")
    logger.error("Test error log from migraine_forecast")
    print("   ✓ Error log sent to Sentry/GlitchTip")


def test_exception_capture():
    """Test exception capture"""
    print("\n3. Testing exception capture...")
    try:
        # Intentionally cause an error
        result = 1 / 0  # noqa: F841
    except ZeroDivisionError as e:
        capture_exception(e)
        print("   ✓ Exception captured and sent to Sentry/GlitchTip")


def test_with_context():
    """Test event with additional context"""
    print("\n4. Testing event with context and tags...")
    
    # Add tags
    set_tag("test_type", "integration_test")
    set_tag("component", "sentry_setup")
    
    # Add context
    set_context("test_info", {
        "test_name": "Sentry Integration Test",
        "app": "migraine_forecast",
        "purpose": "Verify GlitchTip connection"
    })
    
    capture_message("Test message with context and tags", level="info")
    print("   ✓ Message with context sent to Sentry/GlitchTip")


def test_breadcrumbs():
    """Test breadcrumbs (event trail)"""
    print("\n5. Testing breadcrumbs...")
    from sentry_sdk import add_breadcrumb
    
    add_breadcrumb(
        category="test",
        message="Starting breadcrumb test",
        level="info"
    )
    
    add_breadcrumb(
        category="test",
        message="Processing test data",
        level="info"
    )
    
    add_breadcrumb(
        category="test",
        message="About to trigger test event",
        level="info"
    )
    
    capture_message("Test message with breadcrumbs", level="info")
    print("   ✓ Message with breadcrumbs sent to Sentry/GlitchTip")


def main():
    print("=" * 60)
    print("Sentry/GlitchTip Integration Test")
    print("=" * 60)
    print(f"\nDSN: {os.getenv('SENTRY_DSN', 'http://da3f96ceb002454e85ac49a5f1916cd0@192.168.0.11:8001/1')}")
    print(f"Environment: {os.getenv('SENTRY_ENVIRONMENT', 'development')}")
    print("\nRunning tests...\n")
    
    test_basic_message()
    test_error_logging()
    test_exception_capture()
    test_with_context()
    test_breadcrumbs()
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
    print("\nCheck your GlitchTip dashboard at http://192.168.0.11:8001")
    print("to see the captured events.")
    print("\nNote: Events may take a few seconds to appear in the dashboard.")


if __name__ == "__main__":
    main()
