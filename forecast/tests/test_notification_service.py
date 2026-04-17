from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch

from forecast.models import (
    Location,
    WeatherForecast,
    MigrainePrediction,
    HayFeverPrediction,
    NotificationLog,
    UserHealthProfile,
)
from forecast.notification_service import NotificationService


class NotificationServiceTest(TestCase):
    """Test cases for NotificationService"""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.location = Location.objects.create(
            user=self.user, city="Austin", country="USA", latitude=30.2672, longitude=-97.7431
        )
        self.service = NotificationService()

    def test_notification_service_initialization(self):
        """Test NotificationService initializes correctly"""
        self.assertIsNotNone(self.service.prediction_service)
        self.assertIsNotNone(self.service.sinusitis_prediction_service)
        self.assertIsNotNone(self.service.weather_service)

    @patch("forecast.notification_service.send_mail")
    def test_send_migraine_alert_email(self, mock_send_mail):
        """Test sending migraine alert email"""
        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=25.0,
            humidity=70.0,
            pressure=1010.0,
            wind_speed=15.0,
            precipitation=2.0,
            cloud_cover=80.0,
        )

        prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8},
        )

        # Call the public method
        result = self.service.send_migraine_alert(prediction)

        # Verify email was sent
        self.assertTrue(result)
        mock_send_mail.assert_called_once()

    def test_get_detailed_weather_factors(
        self,
    ):
        """Test getting detailed weather factors for a prediction"""
        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=30.0,
            humidity=75.0,
            pressure=1005.0,
            wind_speed=15.0,
            precipitation=5.0,
            cloud_cover=90.0,
        )

        prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8, "humidity_score": 0.7, "pressure_score": 0.9},
        )

        detailed = self.service._get_detailed_weather_factors(prediction)

        self.assertIsNotNone(detailed)
        self.assertIn("factors", detailed)

    @patch("forecast.notification_service.send_mail")
    def test_notification_frequency_respected(self, mock_send_mail):
        """Test that notification frequency preference is respected"""
        # Create user profile with 4-hour notification frequency
        UserHealthProfile.objects.create(
            user=self.user,
            notification_frequency_hours=4,
            email_notifications_enabled=True,
        )

        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=25.0,
            humidity=70.0,
            pressure=1010.0,
            wind_speed=15.0,
            precipitation=2.0,
            cloud_cover=80.0,
        )

        # Create a prediction that was sent 2 hours ago (within 4-hour window)
        old_prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now - timedelta(hours=2) + timedelta(hours=3),
            target_time_end=now - timedelta(hours=2) + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8},
            notification_sent=True,
        )
        # Manually set prediction_time to 2 hours ago
        old_prediction.prediction_time = now - timedelta(hours=2)
        old_prediction.save()

        # Create a new HIGH prediction
        new_prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.9},
            notification_sent=False,
        )

        # Try to send notifications
        migraine_predictions = {
            self.location.id: {
                "probability": "HIGH",
                "prediction": new_prediction,
            }
        }
        sinusitis_predictions = {}

        result = self.service.check_and_send_combined_notifications(migraine_predictions, sinusitis_predictions)

        # Should NOT send because last notification was only 2 hours ago (< 4 hour minimum)
        self.assertEqual(result, 0)
        mock_send_mail.assert_not_called()

    @patch("forecast.notification_service.send_mail")
    def test_notification_sent_after_frequency_window(self, mock_send_mail):
        """Test that notification is sent after frequency window has passed"""
        # Create user profile with 3-hour notification frequency
        UserHealthProfile.objects.create(
            user=self.user,
            notification_frequency_hours=3,
            email_notifications_enabled=True,
            daily_notification_limit=5,  # Allow multiple notifications
        )

        now = timezone.now()

        # Create forecasts for the prediction window
        for i in range(3, 7):
            WeatherForecast.objects.create(
                location=self.location,
                forecast_time=now,
                target_time=now + timedelta(hours=i),
                temperature=25.0,
                humidity=70.0,
                pressure=1010.0,
                wind_speed=15.0,
                precipitation=2.0,
                cloud_cover=80.0,
            )

        forecast = WeatherForecast.objects.filter(location=self.location).first()

        # Create a prediction that was sent 4 hours ago (outside 3-hour window)
        old_prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now - timedelta(hours=4) + timedelta(hours=3),
            target_time_end=now - timedelta(hours=4) + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8, "total_score": 0.8},
            notification_sent=True,
        )
        # Manually set prediction_time to 4 hours ago
        old_prediction.prediction_time = now - timedelta(hours=4)
        old_prediction.save()

        # Create a new HIGH prediction
        new_prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.9, "total_score": 0.9},
            notification_sent=False,
        )

        # Try to send notifications
        migraine_predictions = {
            self.location.id: {
                "probability": "HIGH",
                "prediction": new_prediction,
            }
        }
        sinusitis_predictions = {}

        result = self.service.check_and_send_combined_notifications(migraine_predictions, sinusitis_predictions)

        # Should send because last notification was 4 hours ago (> 3 hour minimum)
        self.assertEqual(result, 1)
        mock_send_mail.assert_called_once()

    @patch("forecast.notification_service.send_mail")
    def test_digest_user_skipped_in_check_and_send_combined(self, mock_send_mail):
        """Test that DIGEST mode users are skipped in check_and_send_combined_notifications"""
        # Create user profile in DIGEST mode
        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
        )

        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=25.0,
            humidity=70.0,
            pressure=1010.0,
            wind_speed=15.0,
            precipitation=2.0,
            cloud_cover=80.0,
        )

        prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8},
            notification_sent=False,
        )

        migraine_predictions = {
            self.location.id: {
                "probability": "HIGH",
                "prediction": prediction,
            }
        }
        sinusitis_predictions = {}

        result = self.service.check_and_send_combined_notifications(migraine_predictions, sinusitis_predictions)

        # Should NOT send because user is in DIGEST mode
        self.assertEqual(result, 0)
        mock_send_mail.assert_not_called()

    def test_should_send_notification_blocks_digest_users(self):
        """Test that _should_send_notification blocks DIGEST mode users for immediate notifications"""
        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
        )

        should_send, reason = self.service._should_send_notification(self.user, "HIGH", "migraine")

        self.assertFalse(should_send)
        self.assertIn("digest", reason.lower())

    def test_should_send_notification_allows_digest_when_is_digest(self):
        """Test that _should_send_notification allows DIGEST mode users when is_digest=True"""
        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
        )

        should_send, reason = self.service._should_send_notification(
            self.user, "HIGH", "general", is_digest=True
        )

        self.assertTrue(should_send)
        self.assertEqual(reason, "All checks passed")

    @patch("forecast.notification_service.send_mail")
    def test_send_combined_alert_with_is_digest_bypasses_digest_block(self, mock_send_mail):
        """Test that send_combined_alert with is_digest=True works for DIGEST mode users"""
        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
        )

        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=25.0,
            humidity=70.0,
            pressure=1010.0,
            wind_speed=15.0,
            precipitation=2.0,
            cloud_cover=80.0,
        )

        prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8},
        )

        # Without is_digest, should be blocked
        result_blocked = self.service.send_combined_alert(
            migraine_predictions=[prediction], is_digest=False
        )
        self.assertFalse(result_blocked)
        mock_send_mail.assert_not_called()

        # With is_digest=True, should send
        result_sent = self.service.send_combined_alert(
            migraine_predictions=[prediction], is_digest=True
        )
        self.assertTrue(result_sent)
        mock_send_mail.assert_called_once()

    @patch("forecast.notification_service.send_mail")
    def test_send_migraine_alert_blocked_for_digest_user(self, mock_send_mail):
        """Test that individual migraine alerts are blocked for DIGEST mode users"""
        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
        )

        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=25.0,
            humidity=70.0,
            pressure=1010.0,
            wind_speed=15.0,
            precipitation=2.0,
            cloud_cover=80.0,
        )

        prediction = MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability="HIGH",
            weather_factors={"temperature_score": 0.8},
        )

        result = self.service.send_migraine_alert(prediction)

        # Should NOT send because user is in DIGEST mode
        self.assertFalse(result)
        mock_send_mail.assert_not_called()

    def _make_hayfever_prediction(self, probability="HIGH"):
        """Helper to create a HayFeverPrediction with the required related objects."""
        now = timezone.now()
        forecast = WeatherForecast.objects.create(
            location=self.location,
            forecast_time=now,
            target_time=now + timedelta(hours=3),
            temperature=22.0,
            humidity=55.0,
            pressure=1015.0,
            wind_speed=10.0,
            precipitation=0.0,
            cloud_cover=20.0,
        )
        return HayFeverPrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=forecast,
            target_time_start=now + timedelta(hours=3),
            target_time_end=now + timedelta(hours=6),
            probability=probability,
            weather_factors={"pollen_available": True, "tree_pollen": 4.0},
        )

    @patch("forecast.notification_service.send_mail")
    def test_send_hayfever_alert_email(self, mock_send_mail):
        """send_hayfever_alert sends an email when user has hay fever enabled."""
        UserHealthProfile.objects.create(
            user=self.user,
            email_notifications_enabled=True,
            hay_fever_predictions_enabled=True,
        )
        prediction = self._make_hayfever_prediction(probability="HIGH")

        result = self.service.send_hayfever_alert(prediction)

        self.assertTrue(result)
        mock_send_mail.assert_called_once()

    @patch("forecast.notification_service.send_mail")
    def test_send_hayfever_alert_blocked_for_digest_user(self, mock_send_mail):
        """Individual hay fever alerts are blocked for DIGEST mode users."""
        UserHealthProfile.objects.create(
            user=self.user,
            notification_mode="DIGEST",
            email_notifications_enabled=True,
            hay_fever_predictions_enabled=True,
        )
        prediction = self._make_hayfever_prediction(probability="HIGH")

        result = self.service.send_hayfever_alert(prediction)

        self.assertFalse(result)
        mock_send_mail.assert_not_called()

    @patch("forecast.notification_service.send_mail")
    def test_send_combined_alert_includes_hayfever(self, mock_send_mail):
        """send_combined_alert accepts hayfever_predictions and logs them."""
        UserHealthProfile.objects.create(
            user=self.user,
            email_notifications_enabled=True,
            hay_fever_predictions_enabled=True,
        )
        prediction = self._make_hayfever_prediction(probability="HIGH")

        result = self.service.send_combined_alert(hayfever_predictions=[prediction])

        self.assertTrue(result)
        mock_send_mail.assert_called_once()
        log = NotificationLog.objects.get(user=self.user, notification_type="combined")
        self.assertEqual(log.hayfever_predictions.count(), 1)
        self.assertEqual(log.hayfever_predictions.first(), prediction)
