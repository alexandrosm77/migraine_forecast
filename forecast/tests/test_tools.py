from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from forecast.tools import ensure_timezone_aware


class ToolsTest(TestCase):
    """Test cases for utility functions in tools.py"""

    def test_ensure_timezone_aware_with_naive_datetime(self):
        """Test making a naive datetime timezone-aware"""
        naive_dt = datetime(2025, 1, 1, 12, 0, 0)
        aware_dt = ensure_timezone_aware(naive_dt)

        self.assertFalse(timezone.is_naive(aware_dt))
        self.assertTrue(timezone.is_aware(aware_dt))

    def test_ensure_timezone_aware_with_aware_datetime(self):
        """Test that an already aware datetime is returned unchanged"""
        aware_dt = timezone.now()
        result_dt = ensure_timezone_aware(aware_dt)

        self.assertEqual(aware_dt, result_dt)
        self.assertTrue(timezone.is_aware(result_dt))
