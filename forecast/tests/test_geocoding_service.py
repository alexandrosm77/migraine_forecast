from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from forecast.geocoding_service import GeocodingProviderError, detect_timezone, search_locations


class GeocodingServiceTest(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(GEOCODING_USER_AGENT="TestAgent", GEOCODING_SEARCH_LIMIT=5)
    @patch("forecast.geocoding_service.detect_timezone", return_value="Europe/Athens")
    @patch("forecast.geocoding_service.requests.get")
    def test_search_locations_normalizes_results(self, mock_get, mock_tz):
        response = Mock()
        response.json.return_value = [
            {
                "display_name": "Athens, Attica, Greece",
                "lat": "37.9838",
                "lon": "23.7275",
                "address": {"city": "Athens", "country": "Greece"},
            }
        ]
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        results = search_locations("Athens")

        self.assertEqual(results[0]["label"], "Athens")
        self.assertEqual(results[0]["country"], "Greece")
        self.assertEqual(results[0]["timezone"], "Europe/Athens")
        self.assertEqual(mock_get.call_args.kwargs["headers"]["User-Agent"], "TestAgent")

    @patch("forecast.geocoding_service.requests.get", side_effect=Exception("network"))
    def test_search_locations_wraps_provider_errors(self, mock_get):
        with self.assertRaises(GeocodingProviderError):
            search_locations("Athens")

    def test_detect_timezone_uses_coordinates(self):
        self.assertEqual(detect_timezone(37.9838, 23.7275), "Europe/Athens")
        self.assertEqual(detect_timezone(40.7128, -74.0060), "America/New_York")
