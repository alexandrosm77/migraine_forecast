from io import StringIO
from unittest.mock import patch
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from forecast.models import (
    HayFeverPrediction,
    Location,
    MigrainePrediction,
    NotificationLog,
    UserHealthProfile,
    WeatherForecast,
)
from forecast.notification_intake import RUN_OVERRIDE_LIMITS, RUN_REPLAY, NotificationIntake


class NotificationIntakeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="intake", email="intake@example.com", password="pw")
        self.profile = UserHealthProfile.objects.create(
            user=self.user,
            email_notifications_enabled=True,
            daily_notification_limit=5,
            daily_migraine_notification_limit=5,
            daily_sinusitis_notification_limit=5,
            daily_hay_fever_notification_limit=5,
            notification_frequency_hours=0,
        )
        self.location = Location.objects.create(
            user=self.user, city="Athens", country="GR", latitude=37.9838, longitude=23.7275
        )
        now = timezone.now()
        self.forecast = WeatherForecast.objects.create(
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

    def make_migraine(self, probability="HIGH", sent=False):
        return MigrainePrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=self.forecast,
            target_time_start=timezone.now() + timedelta(hours=3),
            target_time_end=timezone.now() + timedelta(hours=6),
            probability=probability,
            weather_factors={"temperature_score": 0.8, "total_score": 0.8},
            notification_sent=sent,
        )

    def make_hayfever(self, probability="HIGH", sent=False):
        return HayFeverPrediction.objects.create(
            user=self.user,
            location=self.location,
            forecast=self.forecast,
            target_time_start=timezone.now() + timedelta(hours=3),
            target_time_end=timezone.now() + timedelta(hours=6),
            probability=probability,
            weather_factors={"pollen_available": True, "tree_pollen": 4.0},
            notification_sent=sent,
        )

    @patch("forecast.email_sender.send_mail")
    def test_immediate_dry_run_returns_send_plan_without_writes(self, mock_send_mail):
        prediction = self.make_migraine()

        plan = NotificationIntake().run_immediate(dry_run=True)

        self.assertEqual(plan.summary["send"], 1)
        self.assertEqual(plan.items[0].included_conditions, ["migraine"])
        self.assertEqual(NotificationLog.objects.count(), 0)
        prediction.refresh_from_db()
        self.assertFalse(prediction.notification_sent)
        mock_send_mail.assert_not_called()

    @patch("forecast.email_sender.send_mail")
    def test_immediate_send_logs_metadata_and_marks_predictions(self, mock_send_mail):
        migraine = self.make_migraine()
        hayfever = self.make_hayfever()

        plan = NotificationIntake().run_immediate()

        self.assertEqual(plan.summary["sent"], 1)
        mock_send_mail.assert_called_once()
        log = NotificationLog.objects.get(user=self.user, notification_type="combined")
        self.assertEqual(log.status, "sent")
        self.assertCountEqual(log.metadata["included_conditions"], ["migraine", "hayfever"])
        self.assertEqual(log.metadata["limit_consumption"], {"overall": 1, "migraine": 1, "hayfever": 1})
        self.assertEqual(log.migraine_predictions.get(), migraine)
        self.assertEqual(log.hayfever_predictions.get(), hayfever)
        migraine.refresh_from_db()
        hayfever.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertTrue(migraine.notification_sent)
        self.assertTrue(hayfever.notification_sent)
        self.assertIsNotNone(self.profile.last_migraine_notification_sent_at)
        self.assertIsNone(self.profile.last_sinusitis_notification_sent_at)
        self.assertIsNotNone(self.profile.last_hay_fever_notification_sent_at)

    @patch("forecast.email_sender.send_mail")
    def test_limits_read_from_notification_log_metadata(self, mock_send_mail):
        self.profile.daily_migraine_notification_limit = 1
        self.profile.save()
        sent_log = NotificationLog.objects.create(
            user=self.user,
            notification_type="combined",
            status="sent",
            recipient=self.user.email,
            metadata={"included_conditions": ["migraine"], "limit_consumption": {"overall": 1, "migraine": 1}},
        )
        sent_log.mark_sent()
        self.make_migraine()

        plan = NotificationIntake().run_immediate(dry_run=True)

        self.assertEqual(plan.summary["skipped"], 1)
        self.assertIn("migraine daily notification limit", plan.items[0].reason)
        mock_send_mail.assert_not_called()

    @patch("forecast.email_sender.send_mail")
    def test_replay_respects_limits_but_override_limits_bypasses_them(self, mock_send_mail):
        self.profile.daily_notification_limit = 1
        self.profile.save()
        prediction = self.make_migraine(sent=True)
        sent_log = NotificationLog.objects.create(
            user=self.user,
            notification_type="combined",
            status="sent",
            recipient=self.user.email,
            metadata={"included_conditions": ["migraine"], "limit_consumption": {"overall": 1, "migraine": 1}},
        )
        sent_log.migraine_predictions.set([prediction])
        sent_log.mark_sent()

        replay_plan = NotificationIntake().run_immediate(dry_run=True, run_mode=RUN_REPLAY)
        override_plan = NotificationIntake().run_immediate(dry_run=True, run_mode=RUN_OVERRIDE_LIMITS)

        self.assertEqual(replay_plan.items[0].verdict, "skip")
        self.assertEqual(override_plan.items[0].verdict, "send")
        mock_send_mail.assert_not_called()

    @patch("forecast.email_sender.send_mail")
    def test_digest_send_uses_intake_without_generating_predictions(self, mock_send_mail):
        self.profile.notification_mode = "DIGEST"
        self.profile.save()
        prediction = self.make_migraine()

        plan = NotificationIntake().send_digest(self.user, migraine_predictions=[prediction])

        self.assertEqual(plan.summary["sent"], 1)
        mock_send_mail.assert_called_once()
        log = NotificationLog.objects.get(user=self.user, notification_type="digest")
        self.assertEqual(log.status, "sent")
        self.assertEqual(log.migraine_predictions.get(), prediction)
        prediction.refresh_from_db()
        self.assertTrue(prediction.notification_sent)


class ProcessNotificationsAdapterTest(TestCase):
    @patch("forecast.management.commands.process_notifications.NotificationIntake")
    def test_process_notifications_calls_notification_intake(self, mock_intake_cls):
        mock_plan = mock_intake_cls.return_value.run_immediate.return_value
        mock_plan.items = []
        mock_plan.summary = {"by_condition": {}, "sent": 0, "send": 0, "skipped": 0, "failed": 0, "users_considered": 0}
        mock_plan.dry_run = True
        mock_plan.run_mode = "normal"

        call_command("process_notifications", "--dry-run", stdout=StringIO(), stderr=StringIO())

        mock_intake_cls.return_value.run_immediate.assert_called_once_with(
            dry_run=True,
            run_mode="normal",
            lookback_hours=None,
        )

    @patch("forecast.management.commands.process_notifications.NotificationIntake")
    def test_process_notifications_direct_handle_defaults_new_options(self, mock_intake_cls):
        from forecast.management.commands.process_notifications import Command

        mock_plan = mock_intake_cls.return_value.run_immediate.return_value
        mock_plan.items = []
        mock_plan.summary = {"by_condition": {}, "sent": 0, "send": 0, "skipped": 0, "failed": 0, "users_considered": 0}
        mock_plan.dry_run = False
        mock_plan.run_mode = "normal"

        Command().handle(dry_run=False, force=False)

        mock_intake_cls.return_value.run_immediate.assert_called_once_with(
            dry_run=False,
            run_mode="normal",
            lookback_hours=None,
        )


class SendDigestNotificationsAdapterTest(TestCase):
    @patch("forecast.management.commands.send_digest_notifications.NotificationIntake")
    def test_send_digest_email_uses_notification_intake(self, mock_intake_cls):
        from forecast.management.commands.send_digest_notifications import Command

        user = User.objects.create_user(username="digest", email="digest@example.com", password="pw")
        mock_plan = mock_intake_cls.return_value.send_digest.return_value
        mock_plan.summary = {"sent": 1}
        mock_plan.items = []

        result = Command().send_digest_email(user, [], [], [])

        self.assertTrue(result)
        mock_intake_cls.return_value.send_digest.assert_called_once_with(
            user,
            migraine_predictions=[],
            sinusitis_predictions=[],
            hayfever_predictions=[],
        )
