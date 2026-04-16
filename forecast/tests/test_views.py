import logging

from django.test import TestCase
from django.contrib.auth.models import User

from forecast.models import UserHealthProfile
from forecast.forms import UserHealthProfileForm

logger = logging.getLogger(__name__)


class LanguageSwitchingTest(TestCase):
    """Test language switching functionality including middleware and views."""

    def setUp(self):
        """Set up test user and profile."""
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.profile = UserHealthProfile.objects.create(user=self.user, language="en")

    def test_user_health_profile_default_language(self):
        """Test that new profiles default to English."""
        new_user = User.objects.create_user(username="newuser", email="new@example.com", password="testpassword")
        new_profile = UserHealthProfile.objects.create(user=new_user)
        self.assertEqual(new_profile.language, "en")

    def test_user_health_profile_language_choices(self):
        """Test that language field accepts valid choices."""
        self.profile.language = "el"
        self.profile.save()
        self.assertEqual(self.profile.language, "el")

        self.profile.language = "en"
        self.profile.save()
        self.assertEqual(self.profile.language, "en")

    def test_set_language_view_authenticated(self):
        """Test language switching for authenticated users."""
        self.client.login(username="testuser", password="testpassword")

        # Switch to Greek
        response = self.client.get("/set-language/el/", follow=True)
        self.assertEqual(response.status_code, 200)

        # Verify profile was updated
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.language, "el")

        # Switch back to English
        response = self.client.get("/set-language/en/", follow=True)
        self.assertEqual(response.status_code, 200)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.language, "en")

    def test_set_language_view_invalid_code(self):
        """Test that invalid language codes are rejected."""
        self.client.login(username="testuser", password="testpassword")

        # Try to set invalid language
        response = self.client.get("/set-language/invalid/", follow=True)
        self.assertEqual(response.status_code, 200)

        # Profile should remain unchanged
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.language, "en")

    def test_set_language_view_unauthenticated(self):
        """Test that unauthenticated users are redirected to login."""
        response = self.client.get("/set-language/el/")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith("/login/"))

    def test_user_language_middleware(self):
        """Test that middleware activates user's preferred language."""
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser
        from forecast.middleware import UserLanguageMiddleware

        factory = RequestFactory()
        middleware = UserLanguageMiddleware(lambda r: None)

        # Test with authenticated user who has Greek preference
        self.profile.language = "el"
        self.profile.save()

        request = factory.get("/")
        request.user = self.user
        middleware.process_request(request)

        # Language should be activated
        self.assertEqual(request.LANGUAGE_CODE, "el")

        # Test with anonymous user
        request = factory.get("/")
        request.user = AnonymousUser()
        middleware.process_request(request)

        # Should not crash, just skip

    def test_language_field_in_profile_form(self):
        """Test that language field is included in UserHealthProfileForm."""
        form = UserHealthProfileForm(instance=self.profile)
        self.assertIn("language", form.fields)

        # Test form submission with language change
        form_data = {
            "language": "el",
            "ui_version": "v2",
            "theme": "light",
            "age": 30,
            "email_notifications_enabled": True,
            "notification_mode": "IMMEDIATE",
            "notification_severity_threshold": "MEDIUM",
            "daily_notification_limit": 1,
            "quiet_hours_enabled": False,
            "migraine_predictions_enabled": True,
            "sinusitis_predictions_enabled": True,
            "sensitivity_preset": "NORMAL",
        }
        form = UserHealthProfileForm(data=form_data, instance=self.profile)
        if not form.is_valid():
            logger.debug("Form errors: %s", form.errors)
        self.assertTrue(form.is_valid())

        saved_profile = form.save()
        self.assertEqual(saved_profile.language, "el")

    def test_language_persistence_across_sessions(self):
        """Test that language preference persists across sessions."""
        self.client.login(username="testuser", password="testpassword")

        # Set language to Greek
        self.client.get("/set-language/el/", follow=True)

        # Logout and login again
        self.client.logout()
        self.client.login(username="testuser", password="testpassword")

        # Profile should still have Greek
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.language, "el")

    def test_profile_view_updates_language(self):
        """Test that updating profile through the view updates language."""
        self.client.login(username="testuser", password="testpassword")

        # Update profile with new language
        response = self.client.post(
            "/accounts/profile/",
            {
                "language": "el",
                "ui_version": "v2",
                "theme": "light",
                "age": 35,
                "email_notifications_enabled": True,
                "notification_mode": "IMMEDIATE",
                "notification_severity_threshold": "MEDIUM",
                "daily_notification_limit": 1,
                "quiet_hours_enabled": False,
                "migraine_predictions_enabled": True,
                "sinusitis_predictions_enabled": True,
                "sensitivity_preset": "NORMAL",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.language, "el")
        self.assertEqual(self.profile.age, 35)

    def test_llm_receives_user_language_preference(self):
        """Test that LLM client receives user's language preference in the profile."""
        from forecast.llm_client import LLMClient

        # Set user language to Greek
        self.profile.language = "el"
        self.profile.save()

        # Create a mock LLM client
        client = LLMClient(base_url="http://localhost:8000", model="test-model")

        # Mock the chat_complete method to capture the system prompt
        captured_messages = []

        def mock_chat_complete(messages, **kwargs):
            captured_messages.extend(messages)
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"probability_level": "LOW", "confidence": 0.5, "rationale": "Test", "analysis_text": "Test", "prevention_tips": []}'  # noqa
                        }
                    }
                ]
            }

        client.chat_complete = mock_chat_complete

        # Call predict_probability with user profile including language
        user_profile = {
            "sensitivity_preset": "NORMAL",
            "language": "el",
        }

        scores = {
            "temperature_change": 0.3,
            "humidity_extreme": 0.2,
            "pressure_change": 0.4,
        }

        level, detail = client.predict_probability(
            scores=scores, location_label="Athens, Greece", user_profile=user_profile
        )

        # Verify that the system prompt includes Greek language instruction
        self.assertTrue(len(captured_messages) > 0)
        system_message = captured_messages[0]
        self.assertEqual(system_message["role"], "system")
        self.assertIn("Greek", system_message["content"])
        self.assertIn("Ελληνικά", system_message["content"])
