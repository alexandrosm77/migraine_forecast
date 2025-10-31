from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from .models import Location, WeatherForecast, MigrainePrediction

class ViewsIntegrationTest(TestCase):
    def setUp(self):
        # Mock LLM to prevent API calls during integration tests
        mock_config = MagicMock()
        mock_config.is_active = False
        self.llm_patcher = patch('forecast.models.LLMConfiguration.get_config', return_value=mock_config)
        self.llm_patcher.start()
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpassword'
        )
        
        # Create test location
        self.location = Location.objects.create(
            user=self.user,
            city='New York',
            country='USA',
            latitude=40.7128,
            longitude=-74.0060
        )
        
        # Create test forecast
        now = timezone.now()
        self.forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=25.5,
            humidity=65.0,
            pressure=1013.2,
            wind_speed=10.5,
            precipitation=0.0,
            cloud_cover=30.0
        )
        
        # Create test prediction
        self.prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=self.forecast,
            prediction_time=now,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability='MEDIUM'
        )
        
        # Set up client
        self.client = Client()
        
    def test_index_view(self):
        response = self.client.get(reverse('forecast:index'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'forecast/index.html')
    
    def test_dashboard_view_authenticated(self):
        # Login
        self.client.login(username='testuser', password='testpassword')
        
        # Access dashboard
        response = self.client.get(reverse('forecast:dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'forecast/dashboard.html')
        
        # Check context
        self.assertIn('locations', response.context)
        self.assertIn('recent_predictions', response.context)
        self.assertEqual(len(response.context['locations']), 1)
        
    def test_dashboard_view_unauthenticated(self):
        response = self.client.get(reverse('forecast:dashboard'))
        # Should redirect to login page
        self.assertEqual(response.status_code, 302)
        
    def test_location_detail_view(self):
        # Login
        self.client.login(username='testuser', password='testpassword')
        
        # Access location detail
        response = self.client.get(reverse('forecast:location_detail', args=[self.location.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'forecast/location_detail.html')
        
        # Check context
        self.assertIn('location', response.context)
        self.assertIn('forecasts', response.context)
        self.assertIn('predictions', response.context)
        self.assertEqual(response.context['location'], self.location)
        
    def test_prediction_detail_view(self):
        # Login
        self.client.login(username='testuser', password='testpassword')
        
        # Access prediction detail
        response = self.client.get(reverse('forecast:prediction_detail', args=[self.prediction.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'forecast/prediction_detail.html')
        
        # Check context
        self.assertIn('prediction', response.context)
        self.assertEqual(response.context['prediction'], self.prediction)
        
    def test_location_add_view(self):
        # Login
        self.client.login(username='testuser', password='testpassword')
        
        # Get the form page
        response = self.client.get(reverse('forecast:location_add'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'forecast/location_add.html')
        
        # Test form submission
        with patch('forecast.views.weather_service.update_forecast_for_location') as mock_update:
            mock_update.return_value = []
            
            response = self.client.post(reverse('forecast:location_add'), {
                'city': 'Boston',
                'country': 'USA',
                'latitude': '42.3601',
                'longitude': '-71.0589'
            })
            
            # Should redirect to location list
            self.assertEqual(response.status_code, 302)
            
            # Check if location was created
            self.assertTrue(Location.objects.filter(city='Boston').exists())
            
    def test_location_delete_view(self):
        # Login
        self.client.login(username='testuser', password='testpassword')

        # Get the confirmation page
        response = self.client.get(reverse('forecast:location_delete', args=[self.location.id]))
        self.assertEqual(response.status_code, 200)

        # Test deletion
        response = self.client.post(reverse('forecast:location_delete', args=[self.location.id]))

        # Should redirect to location list
        self.assertEqual(response.status_code, 302)

        # Check if location was deleted
        self.assertFalse(Location.objects.filter(id=self.location.id).exists())

    def test_prediction_list_pagination(self):
        # Login
        self.client.login(username='testuser', password='testpassword')

        # Create 25 predictions to test pagination (page size is 20)
        now = timezone.now()
        for i in range(24):  # We already have 1 from setUp
            MigrainePrediction.objects.create(
                user=self.user,
                location=self.location,
                forecast=self.forecast,
                prediction_time=now - timedelta(hours=i),
                target_time_start=now + timedelta(hours=3),
                target_time_end=now + timedelta(hours=6),
                probability='LOW'
            )

        # Test first page
        response = self.client.get(reverse('forecast:prediction_list'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'forecast/prediction_list.html')

        # Check pagination context
        self.assertIn('predictions', response.context)
        predictions = response.context['predictions']
        self.assertTrue(predictions.has_other_pages())
        self.assertEqual(len(predictions), 20)  # First page should have 20 items
        self.assertTrue(predictions.has_next())
        self.assertFalse(predictions.has_previous())

        # Test second page
        response = self.client.get(reverse('forecast:prediction_list') + '?page=2')
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        """Stop LLM mocking patches"""
        self.llm_patcher.stop()
