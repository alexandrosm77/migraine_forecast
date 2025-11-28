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
        self.llm_patcher = patch("forecast.models.LLMConfiguration.get_config", return_value=mock_config)
        self.llm_patcher.start()
        # Create test user
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")

        # Create test location
        self.location = Location.objects.create(
            user=self.user, city="New York", country="USA", latitude=40.7128, longitude=-74.0060
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
            cloud_cover=30.0,
        )

        # Create test prediction
        self.prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=self.forecast,
            prediction_time=now,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="MEDIUM",
        )

        # Set up client
        self.client = Client()

    def test_index_view(self):
        response = self.client.get(reverse("forecast:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "forecast/index.html")

    def test_dashboard_view_authenticated(self):
        # Login
        self.client.login(username="testuser", password="testpassword")

        # Access dashboard
        response = self.client.get(reverse("forecast:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "forecast/dashboard.html")

        # Check context
        self.assertIn("locations", response.context)
        self.assertIn("recent_predictions", response.context)
        self.assertEqual(len(response.context["locations"]), 1)

    def test_dashboard_view_unauthenticated(self):
        response = self.client.get(reverse("forecast:dashboard"))
        # Should redirect to login page
        self.assertEqual(response.status_code, 302)

    def test_location_detail_view(self):
        # Login
        self.client.login(username="testuser", password="testpassword")

        # Access location detail
        response = self.client.get(reverse("forecast:location_detail", args=[self.location.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "forecast/location_detail.html")

        # Check context
        self.assertIn("location", response.context)
        self.assertIn("forecasts", response.context)
        self.assertIn("predictions", response.context)
        self.assertEqual(response.context["location"], self.location)

    def test_prediction_detail_view(self):
        # Login
        self.client.login(username="testuser", password="testpassword")

        # Access prediction detail
        response = self.client.get(reverse("forecast:prediction_detail", args=[self.prediction.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "forecast/prediction_detail.html")

        # Check context
        self.assertIn("prediction", response.context)
        self.assertEqual(response.context["prediction"], self.prediction)

    def test_location_add_view(self):
        # Login
        self.client.login(username="testuser", password="testpassword")

        # Get the form page
        response = self.client.get(reverse("forecast:location_add"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "forecast/location_add.html")

        # Test form submission
        with patch("forecast.views.weather_service.update_forecast_for_location") as mock_update:
            mock_update.return_value = []

            response = self.client.post(
                reverse("forecast:location_add"),
                {"city": "Boston", "country": "USA", "latitude": "42.3601", "longitude": "-71.0589"},
            )

            # Should redirect to location list
            self.assertEqual(response.status_code, 302)

            # Check if location was created
            self.assertTrue(Location.objects.filter(city="Boston").exists())

    def test_location_delete_view(self):
        # Login
        self.client.login(username="testuser", password="testpassword")

        # Get the confirmation page
        response = self.client.get(reverse("forecast:location_delete", args=[self.location.id]))
        self.assertEqual(response.status_code, 200)

        # Test deletion
        response = self.client.post(reverse("forecast:location_delete", args=[self.location.id]))

        # Should redirect to location list
        self.assertEqual(response.status_code, 302)

        # Check if location was deleted
        self.assertFalse(Location.objects.filter(id=self.location.id).exists())

    def test_prediction_list_pagination(self):
        # Login
        self.client.login(username="testuser", password="testpassword")

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
                probability="LOW",
            )

        # Test first page
        response = self.client.get(reverse("forecast:prediction_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "forecast/prediction_list.html")

        # Check pagination context
        self.assertIn("predictions", response.context)
        predictions = response.context["predictions"]
        self.assertTrue(predictions.has_other_pages())
        self.assertEqual(len(predictions), 20)  # First page should have 20 items
        self.assertTrue(predictions.has_next())
        self.assertFalse(predictions.has_previous())

        # Test second page
        response = self.client.get(reverse("forecast:prediction_list") + "?page=2")
        self.assertEqual(response.status_code, 200)

    def tearDown(self):
        """Stop LLM mocking patches"""
        self.llm_patcher.stop()


class EndToEndWorkflowTest(TestCase):
    """
    Comprehensive end-to-end test that simulates the full application workflow.
    This test verifies the entire pipeline from user registration to receiving notifications.
    """

    def setUp(self):
        """Set up test environment with mocked external dependencies"""
        # Mock LLM to prevent API calls
        mock_config = MagicMock()
        mock_config.is_active = False
        self.llm_patcher = patch("forecast.models.LLMConfiguration.get_config", return_value=mock_config)
        self.llm_patcher.start()

        # Mock weather API to prevent external API calls
        # We need to mock both get_forecast and parse_forecast_data
        self.weather_api_get_patcher = patch("forecast.weather_api.OpenMeteoClient.get_forecast")
        self.weather_api_parse_patcher = patch("forecast.weather_api.OpenMeteoClient.parse_forecast_data")
        self.mock_weather_get = self.weather_api_get_patcher.start()
        self.mock_weather_parse = self.weather_api_parse_patcher.start()

        # Mock email sending
        self.email_patcher = patch("forecast.notification_service.send_mail")
        self.mock_send_mail = self.email_patcher.start()

        self.client = Client()

    def tearDown(self):
        """Clean up mocking patches"""
        self.llm_patcher.stop()
        self.weather_api_get_patcher.stop()
        self.weather_api_parse_patcher.stop()
        self.email_patcher.stop()

    def test_large_prediction_window(self):
        """
        Test that large prediction windows (e.g., 0-23 hours) work correctly.

        This test verifies:
        1. Weather data is collected for the full 72-hour forecast period
        2. Predictions can use custom large windows (0-23 hours)
        3. Temperature changes throughout the day are captured and analyzed
        """

        # ============================================================
        # STEP 1: Create User with Large Prediction Window
        # ============================================================
        user = User.objects.create_user(
            username="large_window_user", email="large_window@example.com", password="testpass123"
        )

        # Create profile with 0-23 hour prediction window
        from .models import UserHealthProfile

        UserHealthProfile.objects.create(
            user=user,
            prediction_window_start_hours=0,
            prediction_window_end_hours=23,
            notification_frequency_hours=24,
        )

        # ============================================================
        # STEP 2: Create Location
        # ============================================================
        location = Location.objects.create(
            user=user,
            city="Test City",
            country="Test Country",
            latitude=40.0,
            longitude=-74.0,
        )

        # ============================================================
        # STEP 3: Mock Weather API with 24 Hours of Data
        # ============================================================
        now = timezone.now()

        # Mock get_forecast to return 24 hours of data with temperature variations
        self.mock_weather_get.return_value = {
            "hourly": {
                "time": [(now + timedelta(hours=i)).isoformat() for i in range(24)],
                # Simulate temperature changes throughout the day
                "temperature_2m": [15.0 + 10 * abs((i - 12) / 12) for i in range(24)],  # Varies from 15-25°C
                "relative_humidity_2m": [60.0 + i for i in range(24)],
                "surface_pressure": [1013.0 - i * 0.3 for i in range(24)],  # Pressure drop
                "wind_speed_10m": [10.0 + i * 0.5 for i in range(24)],
                "precipitation": [0.0] * 24,
                "cloud_cover": [30.0 + i * 2 for i in range(24)],
            }
        }

        # Mock parse_forecast_data to return all 24 hours
        def mock_parse_large_window(forecast_data, location_obj):
            """Mock parser that returns 24 hours of forecast entries"""
            parsed = []
            for i in range(24):
                parsed.append(
                    {
                        "location": location_obj,
                        "target_time": now + timedelta(hours=i),
                        "forecast_time": now,
                        "temperature": 15.0 + 10 * abs((i - 12) / 12),
                        "humidity": 60.0 + i,
                        "pressure": 1013.0 - i * 0.3,
                        "wind_speed": 10.0 + i * 0.5,
                        "precipitation": 0.0,
                        "cloud_cover": 30.0 + i * 2,
                    }
                )
            return parsed

        self.mock_weather_parse.side_effect = mock_parse_large_window

        # ============================================================
        # STEP 4: Collect Weather Data
        # ============================================================
        from .management.commands.collect_weather_data import Command as CollectWeatherCommand

        collect_cmd = CollectWeatherCommand()
        collect_cmd.handle(cleanup_days=2, skip_cleanup=False)

        # Verify we have forecasts for the full 24-hour window
        forecasts = WeatherForecast.objects.filter(location=location)
        self.assertEqual(forecasts.count(), 24, "Should have 24 hours of forecast data")

        # Verify forecasts span the full time range
        forecast_times = [f.target_time for f in forecasts.order_by("target_time")]
        time_span_hours = (forecast_times[-1] - forecast_times[0]).total_seconds() / 3600
        self.assertGreaterEqual(time_span_hours, 23, "Forecasts should span at least 23 hours")

        # ============================================================
        # STEP 5: Generate Predictions with Large Window
        # ============================================================
        from .management.commands.generate_predictions import Command as GeneratePredictionsCommand

        predict_cmd = GeneratePredictionsCommand()
        predict_cmd.handle(cleanup_days=7, skip_cleanup=False, location=None)

        # Verify prediction was created
        from .models import MigrainePrediction

        predictions = MigrainePrediction.objects.filter(user=user, location=location)
        self.assertGreater(predictions.count(), 0, "Should have created at least one prediction")

        prediction = predictions.first()

        # Verify prediction uses the large 0-23 hour window
        time_diff_start = (prediction.target_time_start - now).total_seconds() / 3600
        time_diff_end = (prediction.target_time_end - now).total_seconds() / 3600
        self.assertLess(time_diff_start, 1, "Start should be close to 0 hours")
        self.assertGreater(time_diff_end, 22, "End should be close to 23 hours")

        # ============================================================
        # STEP 6: Verify Temperature Changes Are Captured
        # ============================================================
        # Get forecasts used in the prediction
        prediction_forecasts = WeatherForecast.objects.filter(
            location=location,
            target_time__gte=prediction.target_time_start,
            target_time__lte=prediction.target_time_end,
        ).order_by("target_time")

        self.assertGreater(prediction_forecasts.count(), 10, "Should have many forecast points in 23-hour window")

        # Verify temperature variation is captured
        temps = [f.temperature for f in prediction_forecasts]
        temp_range = max(temps) - min(temps)
        self.assertGreater(temp_range, 5, "Should capture significant temperature variation throughout the day")

        # Verify pressure changes are captured
        pressures = [f.pressure for f in prediction_forecasts]
        pressure_range = max(pressures) - min(pressures)
        self.assertGreater(pressure_range, 3, "Should capture pressure changes throughout the day")

    def test_complete_user_journey(self):
        """
        Test the complete user journey from registration to receiving notifications.

        This test covers:
        1. User registration
        2. User login
        3. Profile configuration with custom notification preferences
        4. Location creation
        5. Weather data collection
        6. Prediction generation
        7. Notification processing
        """

        # ============================================================
        # STEP 1: User Registration
        # ============================================================
        registration_data = {
            "username": "e2e_testuser",
            "password1": "SecureTestPass123!",
            "password2": "SecureTestPass123!",
        }

        response = self.client.post(reverse("forecast:register"), registration_data)
        self.assertEqual(response.status_code, 302)  # Redirect after successful registration

        # Verify user was created and add email
        user = User.objects.get(username="e2e_testuser")
        self.assertIsNotNone(user)
        user.email = "e2e_test@example.com"
        user.save()

        # ============================================================
        # STEP 2: User Login
        # ============================================================
        login_successful = self.client.login(username="e2e_testuser", password="SecureTestPass123!")
        self.assertTrue(login_successful)

        # Verify dashboard is accessible
        response = self.client.get(reverse("forecast:dashboard"))
        self.assertEqual(response.status_code, 200)

        # ============================================================
        # STEP 3: Configure User Health Profile with Custom Preferences
        # ============================================================
        profile_data = {
            "language": "en",
            "age": 35,
            "prior_conditions": "Occasional migraines, sensitive to weather changes",
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 3,
            "daily_migraine_notification_limit": 2,
            "daily_sinusitis_notification_limit": 2,
            "notification_frequency_hours": 4,  # Custom: 4 hours between notifications
            "quiet_hours_enabled": False,
            "prediction_window_start_hours": 2,  # Custom: Check 2-8 hours ahead
            "prediction_window_end_hours": 8,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "sensitivity_overall": 1.5,
            "sensitivity_temperature": 1.8,
            "sensitivity_humidity": 1.2,
            "sensitivity_pressure": 2.0,
            "sensitivity_cloud_cover": 1.0,
            "sensitivity_precipitation": 1.3,
        }

        response = self.client.post(reverse("forecast:profile"), profile_data)
        self.assertEqual(response.status_code, 302)  # Redirect after successful save

        # Verify profile was created with custom preferences
        user.refresh_from_db()
        profile = user.health_profile
        self.assertEqual(profile.notification_frequency_hours, 4)
        self.assertEqual(profile.prediction_window_start_hours, 2)
        self.assertEqual(profile.prediction_window_end_hours, 8)
        self.assertEqual(profile.sensitivity_pressure, 2.0)

        # ============================================================
        # STEP 4: Add Location
        # ============================================================
        # Mock weather API response
        now = timezone.now()

        # Mock get_forecast to return raw API data
        self.mock_weather_get.return_value = {
            "hourly": {
                "time": [(now + timedelta(hours=i)).isoformat() for i in range(1, 10)],
                "temperature_2m": [20.0 + i for i in range(9)],
                "relative_humidity_2m": [65.0 - i for i in range(9)],
                "surface_pressure": [1013.0 - i * 0.5 for i in range(9)],
                "wind_speed_10m": [10.0 + i * 0.5 for i in range(9)],
                "precipitation": [0.0] * 9,
                "cloud_cover": [30.0 + i * 5 for i in range(9)],
            }
        }

        location_data = {
            "city": "San Francisco",
            "country": "USA",
            "latitude": "37.7749",
            "longitude": "-122.4194",
        }

        response = self.client.post(reverse("forecast:location_add"), location_data)
        self.assertEqual(response.status_code, 302)  # Redirect after successful creation

        # Verify location was created
        location = Location.objects.get(city="San Francisco", user=user)
        self.assertIsNotNone(location)
        self.assertEqual(location.latitude, 37.7749)

        # Mock parse_forecast_data to return parsed forecast entries
        # This will be used by the collect_weather_data command
        def mock_parse_data(forecast_data, location_obj):
            """Mock parser that returns forecast entries"""
            parsed = []
            for i in range(1, 10):
                parsed.append(
                    {
                        "location": location_obj,
                        "target_time": now + timedelta(hours=i),
                        "forecast_time": now,
                        "temperature": 20.0 + i,
                        "humidity": 65.0 - i,
                        "pressure": 1013.0 - i * 0.5,
                        "wind_speed": 10.0 + i * 0.5,
                        "precipitation": 0.0,
                        "cloud_cover": 30.0 + i * 5,
                    }
                )
            return parsed

        self.mock_weather_parse.side_effect = mock_parse_data

        # ============================================================
        # STEP 5: Simulate Weather Data Collection (Cron Job Task 1)
        # ============================================================
        from .weather_service import WeatherService
        from .management.commands.collect_weather_data import Command as CollectWeatherCommand

        # Run the collect_weather_data command with options
        collect_cmd = CollectWeatherCommand()
        collect_cmd.handle(cleanup_days=2, skip_cleanup=False)

        # Verify weather forecasts were created
        forecasts = WeatherForecast.objects.filter(location=location)
        self.assertGreater(forecasts.count(), 0)

        # Verify forecasts are in the user's custom time window (2-8 hours ahead)
        forecast_in_window = forecasts.filter(
            target_time__gte=now + timedelta(hours=2), target_time__lte=now + timedelta(hours=8)
        )
        self.assertGreater(forecast_in_window.count(), 0)

        # ============================================================
        # STEP 6: Simulate Prediction Generation (Cron Job Task 2)
        # ============================================================
        from .management.commands.generate_predictions import Command as GeneratePredictionsCommand

        # Run the generate_predictions command with options
        predict_cmd = GeneratePredictionsCommand()
        predict_cmd.handle(cleanup_days=7, skip_cleanup=False, location=None)

        # Verify predictions were created
        migraine_predictions = MigrainePrediction.objects.filter(user=user, location=location)
        self.assertGreater(migraine_predictions.count(), 0)

        # Verify prediction uses custom time window
        prediction = migraine_predictions.first()
        self.assertIsNotNone(prediction)

        # Check that prediction window matches user preferences (2-8 hours)
        time_diff_start = (prediction.target_time_start - now).total_seconds() / 3600
        time_diff_end = (prediction.target_time_end - now).total_seconds() / 3600
        self.assertGreaterEqual(time_diff_start, 1.5)  # Allow some tolerance
        self.assertLessEqual(time_diff_end, 8.5)

        # ============================================================
        # STEP 7: Simulate Notification Processing (Cron Job Task 3)
        # ============================================================
        from .management.commands.process_notifications import Command as ProcessNotificationsCommand

        # Manually set a prediction to HIGH to trigger notification
        prediction.probability = "HIGH"
        prediction.notification_sent = False
        prediction.weather_factors = {"total_score": 0.85, "pressure_score": 0.9}
        prediction.save()

        # Run the process_notifications command with options
        notify_cmd = ProcessNotificationsCommand()
        notify_cmd.handle(dry_run=False, force=False)

        # Verify notification was sent
        self.mock_send_mail.assert_called()

        # Verify prediction was marked as sent
        prediction.refresh_from_db()
        self.assertTrue(prediction.notification_sent)

        # ============================================================
        # STEP 8: Test Notification Frequency Enforcement
        # ============================================================
        # Create another HIGH prediction immediately
        forecast = forecasts.first()
        new_prediction = MigrainePrediction.objects.create(
            user=user,
            location=location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=2),
            target_time_end=now + timedelta(hours=8),
            probability="HIGH",
            weather_factors={"total_score": 0.90},
            notification_sent=False,
        )

        # Reset mock to track new calls
        self.mock_send_mail.reset_mock()

        # Try to send notification again
        notify_cmd.handle(dry_run=False, force=False)

        # Should NOT send because last notification was sent less than 4 hours ago
        # (user's notification_frequency_hours is 4)
        new_prediction.refresh_from_db()
        self.assertFalse(new_prediction.notification_sent)

        # ============================================================
        # STEP 9: Verify Dashboard Shows Predictions
        # ============================================================
        response = self.client.get(reverse("forecast:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("recent_predictions", response.context)
        self.assertGreater(len(response.context["recent_predictions"]), 0)

        # ============================================================
        # STEP 10: Verify Location Detail Page
        # ============================================================
        response = self.client.get(reverse("forecast:location_detail", args=[location.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("forecasts", response.context)
        self.assertIn("predictions", response.context)
        self.assertGreater(len(response.context["forecasts"]), 0)
        self.assertGreater(len(response.context["predictions"]), 0)

        # ============================================================
        # STEP 11: Verify Prediction Detail Page
        # ============================================================
        response = self.client.get(reverse("forecast:prediction_detail", args=[prediction.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["prediction"], prediction)

        # ============================================================
        # STEP 12: Test Profile Update
        # ============================================================
        # Update notification frequency
        profile_data["notification_frequency_hours"] = 6
        response = self.client.post(reverse("forecast:profile"), profile_data)
        self.assertEqual(response.status_code, 302)

        user.refresh_from_db()
        self.assertEqual(user.health_profile.notification_frequency_hours, 6)

        # ============================================================
        # STEP 13: Test Location Deletion
        # ============================================================
        response = self.client.post(reverse("forecast:location_delete", args=[location.id]))
        self.assertEqual(response.status_code, 302)

        # Verify location and associated data were deleted
        self.assertFalse(Location.objects.filter(id=location.id).exists())

        # ============================================================
        # SUCCESS: Complete workflow executed successfully!
        # ============================================================
