from django.test import TestCase

from forecast.forms import UserHealthProfileForm


class UserHealthProfileFormTest(TestCase):
    """Test cases for UserHealthProfileForm"""

    def test_form_valid_data(self):
        """Test form with valid data"""
        form_data = {
            "language": "en",
            "ui_version": "v2",
            "theme": "light",
            "age": 30,
            "prior_conditions": "Aura, hypertension",
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 2,
            "quiet_hours_enabled": False,
            "daily_hay_fever_notification_limit": 1,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": False,
            "hay_fever_predictions_enabled": False,
            "sensitivity_preset": "NORMAL",
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_form_clamps_sensitivity_values(self):
        """Test that form accepts sensitivity preset values"""
        form_data = {
            "language": "en",
            "ui_version": "v2",
            "theme": "light",
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "quiet_hours_enabled": False,
            "daily_hay_fever_notification_limit": 1,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "hay_fever_predictions_enabled": True,
            "sensitivity_preset": "HIGH",
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

        cleaned = form.cleaned_data
        self.assertEqual(cleaned["sensitivity_preset"], "HIGH")

    def test_form_optional_fields(self):
        """Test that optional fields can be omitted"""
        form_data = {
            "language": "en",
            "ui_version": "v2",
            "theme": "light",
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "quiet_hours_enabled": False,
            "daily_hay_fever_notification_limit": 1,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "hay_fever_predictions_enabled": True,
            "sensitivity_preset": "NORMAL",
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_form_notification_frequency_validation(self):
        """Test notification frequency validation - field removed from form"""
        # notification_frequency_hours is no longer in the form
        # This test is now obsolete but we keep it to verify the field is not required
        form_data = {
            "language": "en",
            "ui_version": "v2",
            "theme": "light",
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "quiet_hours_enabled": False,
            "daily_hay_fever_notification_limit": 1,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "hay_fever_predictions_enabled": True,
            "sensitivity_preset": "NORMAL",
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertTrue(form.is_valid())  # Should be valid without notification_frequency_hours

    def test_form_prediction_window_validation(self):
        """Test prediction window validation - fields removed from form"""
        # prediction_window_start_hours and prediction_window_end_hours are no longer in the form
        # This test is now obsolete but we keep it to verify the fields are not required
        form_data = {
            "language": "en",
            "ui_version": "v2",
            "theme": "light",
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "quiet_hours_enabled": False,
            "daily_hay_fever_notification_limit": 1,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "hay_fever_predictions_enabled": True,
            "sensitivity_preset": "NORMAL",
        }
        form = UserHealthProfileForm(data=form_data)
        self.assertTrue(form.is_valid())  # Should be valid without prediction window fields
