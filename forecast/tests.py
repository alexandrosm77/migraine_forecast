from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from .models import Location, WeatherForecast, ActualWeather, MigrainePrediction
from .weather_api import OpenMeteoClient
from .weather_service import WeatherService
from .prediction_service import MigrainePredictionService
from .comparison_service import DataComparisonService

class LocationModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword'
        )
        
    def test_location_creation(self):
        location = Location.objects.create(
            user=self.user,
            city='New York',
            country='USA',
            latitude=40.7128,
            longitude=-74.0060
        )
        self.assertEqual(location.city, 'New York')
        self.assertEqual(location.country, 'USA')
        self.assertEqual(location.latitude, 40.7128)
        self.assertEqual(location.longitude, -74.0060)
        self.assertEqual(location.user, self.user)
        
    def test_location_string_representation(self):
        location = Location.objects.create(
            user=self.user,
            city='New York',
            country='USA',
            latitude=40.7128,
            longitude=-74.0060
        )
        self.assertEqual(str(location), 'New York, USA')

class WeatherForecastModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword'
        )
        self.location = Location.objects.create(
            user=self.user,
            city='New York',
            country='USA',
            latitude=40.7128,
            longitude=-74.0060
        )
        
    def test_weather_forecast_creation(self):
        forecast_time = timezone.now()
        target_time = forecast_time + timedelta(hours=3)
        
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=forecast_time,
            target_time=target_time,
            temperature=25.5,
            humidity=65.0,
            pressure=1013.2,
            wind_speed=10.5,
            precipitation=0.0,
            cloud_cover=30.0
        )
        
        self.assertEqual(forecast.location, self.location)
        self.assertEqual(forecast.temperature, 25.5)
        self.assertEqual(forecast.humidity, 65.0)
        self.assertEqual(forecast.pressure, 1013.2)
        
    def test_weather_forecast_string_representation(self):
        forecast_time = timezone.now()
        target_time = forecast_time + timedelta(hours=3)
        
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=forecast_time,
            target_time=target_time,
            temperature=25.5,
            humidity=65.0,
            pressure=1013.2,
            wind_speed=10.5,
            precipitation=0.0,
            cloud_cover=30.0
        )
        
        expected_str = f"Forecast for {self.location} at {target_time}"
        self.assertEqual(str(forecast), expected_str)

class OpenMeteoClientTest(TestCase):
    @patch('forecast.weather_api.requests.get')
    def test_get_forecast(self, mock_get):
        # Mock the API response
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'hourly': {
                'time': ['2025-03-31T12:00:00Z', '2025-03-31T13:00:00Z'],
                'temperature_2m': [25.5, 26.0],
                'relative_humidity_2m': [65.0, 64.0],
                'precipitation_probability': [10, 5],
                'precipitation': [0.0, 0.0],
                'surface_pressure': [1013.2, 1013.0],
                'cloud_cover': [30.0, 25.0],
                'visibility': [20000, 20000],
                'wind_speed_10m': [10.5, 11.0]
            }
        }
        mock_get.return_value = mock_response
        
        client = OpenMeteoClient()
        result = client.get_forecast(40.7128, -74.0060)
        
        # Verify the API was called with correct parameters
        mock_get.assert_called_once()
        call_args = mock_get.call_args[1]
        self.assertEqual(call_args['params']['latitude'], 40.7128)
        self.assertEqual(call_args['params']['longitude'], -74.0060)
        
        # Verify the result
        self.assertIn('hourly', result)
        self.assertEqual(len(result['hourly']['time']), 2)

class MigrainePredictionServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword'
        )
        self.location = Location.objects.create(
            user=self.user,
            city='New York',
            country='USA',
            latitude=40.7128,
            longitude=-74.0060
        )
        
        # Create forecasts for testing
        now = timezone.now()
        
        # Previous forecasts (for comparison)
        for i in range(6):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now - timedelta(hours=12),
                target_time=now - timedelta(hours=6-i),
                temperature=25.0,
                humidity=65.0,
                pressure=1013.0,
                wind_speed=10.0,
                precipitation=0.0,
                cloud_cover=30.0
            )
        
        # Forecasts for the prediction window (3-6 hours ahead)
        for i in range(4):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=3+i),
                temperature=30.0,  # Significant temperature change
                humidity=75.0,     # High humidity
                pressure=1000.0,   # Low pressure
                wind_speed=15.0,
                precipitation=5.0, # Heavy precipitation
                cloud_cover=90.0   # Heavy cloud cover
            )
    
    def test_predict_migraine_probability_high(self):
        service = MigrainePredictionService()
        probability, prediction = service.predict_migraine_probability(self.location, self.user)
        
        self.assertEqual(probability, 'HIGH')
        self.assertIsNotNone(prediction)
        self.assertEqual(prediction.user, self.user)
        self.assertEqual(prediction.location, self.location)
        self.assertEqual(prediction.probability, 'HIGH')

class DataComparisonServiceTest(TestCase):
    @patch('forecast.comparison_service.requests.get')
    def test_collect_actual_weather(self, mock_get):
        # Setup
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword'
        )
        location = Location.objects.create(
            user=user,
            city='New York',
            country='USA',
            latitude=40.7128,
            longitude=-74.0060
        )
        
        # Mock API response
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'current': {
                'time': '2025-03-31T12:00:00Z',
                'temperature_2m': 25.5,
                'relative_humidity_2m': 65.0,
                'surface_pressure': 1013.2,
                'precipitation': 0.0,
                'cloud_cover': 30.0,
                'wind_speed_10m': 10.5
            }
        }
        mock_get.return_value = mock_response
        
        # Test
        service = DataComparisonService()
        actual_weather = service.collect_actual_weather(location)
        
        # Verify
        self.assertIsNotNone(actual_weather)
        self.assertEqual(actual_weather.location, location)
        self.assertEqual(actual_weather.temperature, 25.5)
        self.assertEqual(actual_weather.humidity, 65.0)
        self.assertEqual(actual_weather.pressure, 1013.2)
