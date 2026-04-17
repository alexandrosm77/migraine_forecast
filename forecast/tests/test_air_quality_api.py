from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch, MagicMock

from forecast.models import Location, AirQualityForecast
from forecast.air_quality_api import OpenMeteoAirQualityClient
from forecast.weather_service import WeatherService


def _future_iso(hours):
    """Return an ISO-formatted timestamp `hours` in the future (UTC, naive)."""
    dt = (timezone.now() + timedelta(hours=hours)).replace(microsecond=0, tzinfo=None)
    return dt.isoformat()


class OpenMeteoAirQualityClientParseTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="aquser", email="aq@example.com", password="pw")
        self.location = Location.objects.create(
            user=self.user, city="Athens", country="Greece", latitude=37.98, longitude=23.72
        )
        self.client = OpenMeteoAirQualityClient()

    def test_parse_eu_location_all_fields(self):
        t1, t2 = _future_iso(1), _future_iso(2)
        forecast_data = {
            "hourly": {
                "time": [t1, t2],
                "alder_pollen": [0.5, 0.6],
                "birch_pollen": [1.0, 1.1],
                "grass_pollen": [2.0, 2.1],
                "mugwort_pollen": [0.1, 0.2],
                "olive_pollen": [3.0, 3.1],
                "ragweed_pollen": [0.0, 0.0],
                "pm10": [10.0, 11.0],
                "pm2_5": [5.0, 5.5],
                "ozone": [60.0, 62.0],
                "nitrogen_dioxide": [20.0, 21.0],
                "dust": [1.0, 1.2],
                "uv_index": [3.0, 4.0],
                "european_aqi": [40, 45],
                "us_aqi": [50, 55],
            }
        }
        parsed = self.client.parse_forecast_data(forecast_data, self.location)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["alder_pollen"], 0.5)
        self.assertEqual(parsed[0]["grass_pollen"], 2.0)
        self.assertEqual(parsed[0]["ragweed_pollen"], 0.0)
        self.assertEqual(parsed[0]["pm10"], 10.0)
        self.assertEqual(parsed[1]["us_aqi"], 55)

    def test_parse_non_eu_location_pollen_is_none(self):
        """Non-EU locations: pollen arrays may be absent or contain nulls — must store None, not 0."""
        t1 = _future_iso(1)
        forecast_data = {
            "hourly": {
                "time": [t1],
                "alder_pollen": [None],
                "birch_pollen": [None],
                "grass_pollen": [None],
                "mugwort_pollen": [None],
                "olive_pollen": [None],
                "ragweed_pollen": [None],
                "pm10": [12.0],
                "pm2_5": [6.0],
                "ozone": [55.0],
                "nitrogen_dioxide": [15.0],
                "dust": [0.5],
                "uv_index": [5.0],
                "european_aqi": [35],
                "us_aqi": [42],
            }
        }
        parsed = self.client.parse_forecast_data(forecast_data, self.location)
        self.assertEqual(len(parsed), 1)
        for pollen in ["alder_pollen", "birch_pollen", "grass_pollen",
                       "mugwort_pollen", "olive_pollen", "ragweed_pollen"]:
            self.assertIsNone(parsed[0][pollen], f"{pollen} should be None for non-EU")
        self.assertEqual(parsed[0]["pm10"], 12.0)

    def test_parse_missing_pollen_arrays_entirely(self):
        """If API omits pollen variables entirely, each maps to None."""
        t1 = _future_iso(1)
        forecast_data = {
            "hourly": {
                "time": [t1],
                "pm10": [12.0], "pm2_5": [6.0], "ozone": [55.0],
                "nitrogen_dioxide": [15.0], "dust": [0.5], "uv_index": [5.0],
                "european_aqi": [35], "us_aqi": [42],
            }
        }
        parsed = self.client.parse_forecast_data(forecast_data, self.location)
        self.assertEqual(len(parsed), 1)
        self.assertIsNone(parsed[0]["alder_pollen"])
        self.assertIsNone(parsed[0]["birch_pollen"])
        self.assertEqual(parsed[0]["pm10"], 12.0)

    def test_parse_skips_past_timestamps(self):
        past = (timezone.now() - timedelta(hours=5)).replace(microsecond=0, tzinfo=None).isoformat()
        future = _future_iso(2)
        forecast_data = {
            "hourly": {
                "time": [past, future],
                **{p: [1.0, 2.0] for p in OpenMeteoAirQualityClient.HOURLY_PARAMS},
            }
        }
        parsed = self.client.parse_forecast_data(forecast_data, self.location)
        self.assertEqual(len(parsed), 1)

    def test_parse_invalid_data_returns_empty(self):
        self.assertEqual(self.client.parse_forecast_data(None, self.location), [])
        self.assertEqual(self.client.parse_forecast_data({}, self.location), [])


class OpenMeteoAirQualityClientFetchTest(TestCase):
    @patch("forecast.air_quality_api.requests.Session.get")
    def test_get_forecast_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "hourly": {"time": [_future_iso(1)], "pm10": [10.0]}
        }
        mock_get.return_value = mock_response

        client = OpenMeteoAirQualityClient()
        result = client.get_forecast(37.98, 23.72)

        mock_get.assert_called_once()
        call_kwargs = mock_get.call_args[1]
        self.assertEqual(call_kwargs["params"]["latitude"], 37.98)
        self.assertEqual(call_kwargs["params"]["longitude"], 23.72)
        self.assertEqual(call_kwargs["params"]["forecast_days"], 4)
        self.assertEqual(call_kwargs["params"]["timezone"], "UTC")
        # All expected hourly params requested
        hourly_requested = call_kwargs["params"]["hourly"].split(",")
        for p in OpenMeteoAirQualityClient.HOURLY_PARAMS:
            self.assertIn(p, hourly_requested)
        self.assertIn("pm10", result["hourly"])

    @patch("forecast.air_quality_api.requests.Session.get")
    def test_get_forecast_http_error_returns_none(self, mock_get):
        import requests as req
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = req.exceptions.HTTPError(response=MagicMock(status_code=500))
        mock_get.return_value = mock_response

        client = OpenMeteoAirQualityClient()
        self.assertIsNone(client.get_forecast(37.98, 23.72))


class OpenMeteoAirQualityClientBatchTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="bu", email="bu@example.com", password="pw")
        self.loc_eu = Location.objects.create(
            user=self.user, city="Athens", country="Greece", latitude=37.98, longitude=23.72
        )
        self.loc_us = Location.objects.create(
            user=self.user, city="NYC", country="USA", latitude=40.71, longitude=-74.00
        )

    @patch("forecast.air_quality_api.requests.Session.get")
    def test_get_forecast_batch_success(self, mock_get):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {"hourly": {"time": [_future_iso(1)], "pm10": [10.0]}},
            {"hourly": {"time": [_future_iso(1)], "pm10": [11.0]}},
        ]
        mock_get.return_value = mock_response

        client = OpenMeteoAirQualityClient()
        results = client.get_forecast_batch([self.loc_eu, self.loc_us])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["location"], self.loc_eu)
        self.assertEqual(results[1]["location"], self.loc_us)

    def test_get_forecast_batch_enforces_size_limit(self):
        client = OpenMeteoAirQualityClient()
        too_many = [self.loc_eu] * 51
        with self.assertRaises(ValueError):
            client.get_forecast_batch(too_many)


class WeatherServiceAirQualityTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="wsu", email="wsu@example.com", password="pw")
        self.location = Location.objects.create(
            user=self.user, city="Athens", country="Greece", latitude=37.98, longitude=23.72
        )
        self.service = WeatherService()

    @patch("forecast.air_quality_api.OpenMeteoAirQualityClient.get_forecast")
    def test_update_air_quality_for_location_upsert(self, mock_get):
        """Second call with same target_time updates existing row rather than creating a new one."""
        t1 = _future_iso(1)
        mock_get.return_value = {
            "hourly": {
                "time": [t1],
                **{p: [None] for p in OpenMeteoAirQualityClient.POLLEN_PARAMS},
                **{p: [1.0] for p in OpenMeteoAirQualityClient.AIR_QUALITY_PARAMS},
            }
        }

        created, updated = self.service.update_air_quality_for_location(self.location)
        self.assertEqual(created, 1)
        self.assertEqual(updated, 0)
        self.assertEqual(AirQualityForecast.objects.filter(location=self.location).count(), 1)

        # Second call with new value should update, not create
        mock_get.return_value = {
            "hourly": {
                "time": [t1],
                **{p: [None] for p in OpenMeteoAirQualityClient.POLLEN_PARAMS},
                **{p: [2.0] for p in OpenMeteoAirQualityClient.AIR_QUALITY_PARAMS},
            }
        }
        created, updated = self.service.update_air_quality_for_location(self.location)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 1)
        row = AirQualityForecast.objects.get(location=self.location)
        self.assertEqual(row.pm10, 2.0)
        # Pollen remains NULL, not 0
        self.assertIsNone(row.alder_pollen)

    @patch("forecast.air_quality_api.OpenMeteoAirQualityClient.get_forecast")
    def test_update_air_quality_api_failure(self, mock_get):
        mock_get.return_value = None
        created, updated = self.service.update_air_quality_for_location(self.location)
        self.assertEqual(created, 0)
        self.assertEqual(updated, 0)
        self.assertEqual(AirQualityForecast.objects.count(), 0)

    @patch("forecast.air_quality_api.OpenMeteoAirQualityClient.get_forecast_batch")
    def test_update_air_quality_batch(self, mock_batch):
        t1 = _future_iso(1)
        mock_batch.return_value = [
            {
                "location": self.location,
                "data": {
                    "hourly": {
                        "time": [t1],
                        **{p: [None] for p in OpenMeteoAirQualityClient.POLLEN_PARAMS},
                        **{p: [3.0] for p in OpenMeteoAirQualityClient.AIR_QUALITY_PARAMS},
                    }
                },
            }
        ]
        result = self.service.update_air_quality_for_locations_batch([self.location])
        self.assertEqual(result["total_created"], 1)
        self.assertEqual(result["total_updated"], 0)
        self.assertEqual(AirQualityForecast.objects.filter(location=self.location).count(), 1)
