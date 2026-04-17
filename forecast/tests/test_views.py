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



class ProfileEmailEditTests(TestCase):
    """Tests for the email-editing capability on the profile view."""

    PROFILE_URL = "/accounts/profile/"

    def _valid_profile_post(self, **overrides):
        """Minimal valid POST body for the profile form; override fields as needed."""
        data = {
            "language": "en",
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
        }
        data.update(overrides)
        return data

    def setUp(self):
        self.user = User.objects.create_user(
            username="owner", email="user@example.com", password="testpassword"
        )
        self.other_user = User.objects.create_user(
            username="other", email="other@example.com", password="testpassword"
        )
        self.profile = UserHealthProfile.objects.create(user=self.user)
        self.client.login(username="owner", password="testpassword")

    def test_get_profile_renders_email_form(self):
        """GET profile returns 200 with email_form in context and current email visible."""
        response = self.client.get(self.PROFILE_URL)
        self.assertEqual(response.status_code, 200)
        self.assertIn("email_form", response.context)
        body = response.content.decode()
        self.assertTrue(
            "user@example.com" in body or 'name="email"' in body,
            "Expected current email or email input to be rendered in profile page",
        )

    def test_post_updates_email(self):
        """POST with a new email + valid health fields redirects and updates User.email."""
        response = self.client.post(
            self.PROFILE_URL,
            self._valid_profile_post(email="new@example.com"),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "new@example.com")

    def test_post_empty_email_clears_email(self):
        """POST with empty email redirects and clears User.email."""
        response = self.client.post(
            self.PROFILE_URL,
            self._valid_profile_post(email=""),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "")

    def test_post_duplicate_email_rejected(self):
        """POST with an email already used by another account shows a form error and does not change email."""
        response = self.client.post(
            self.PROFILE_URL,
            self._valid_profile_post(email="other@example.com"),
        )
        self.assertEqual(response.status_code, 200)
        email_form = response.context["email_form"]
        self.assertTrue(email_form.errors, "Expected email_form to have errors for duplicate email")
        self.assertIn("email", email_form.errors)
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "user@example.com")

    def test_post_email_is_normalized(self):
        """POST with whitespace/mixed case email is stored trimmed and lowercased."""
        response = self.client.post(
            self.PROFILE_URL,
            self._valid_profile_post(email="  NEW@Example.COM  "),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(pk=self.user.pk).email, "new@example.com")

    def test_admin_viewing_other_user_cannot_edit_email(self):
        """Admin GET for another user's profile shows no editable email input and POST does not change it."""
        admin = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpassword"
        )
        self.client.logout()
        self.client.login(username="admin", password="adminpassword")

        other_url = f"/accounts/profile/{self.other_user.id}/"

        get_response = self.client.get(other_url)
        self.assertEqual(get_response.status_code, 200)
        self.assertTrue(get_response.context.get("is_viewing_other"))
        self.assertNotIn(
            'name="email"',
            get_response.content.decode(),
            "Admin viewing another user's profile should not render an editable email input",
        )

        post_response = self.client.post(
            other_url,
            self._valid_profile_post(email="hacked@example.com"),
        )
        self.assertIn(post_response.status_code, (200, 302))
        self.assertEqual(
            User.objects.get(pk=self.other_user.pk).email,
            "other@example.com",
            "Admin POST to another user's profile must not change that user's email",
        )
        self.assertEqual(
            User.objects.get(pk=admin.pk).email,
            "admin@example.com",
            "Admin's own email must not be changed when POSTing to another user's profile",
        )
