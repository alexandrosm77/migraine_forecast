"""
Seed the database with initial data for local development.

Idempotent – safe to run multiple times; existing objects are skipped.
"""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from forecast.models import (
    LLMConfiguration,
    Location,
    UserHealthProfile,
)


class Command(BaseCommand):
    help = "Create initial dev data: admin user, sample location, health profile, LLM config"

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-password",
            default="admin",
            help="Password for the admin superuser (default: admin)",
        )

    def handle(self, *args, **options):
        password = options["admin_password"]

        # ── 1. Superuser ──────────────────────────────────────────────
        user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@localhost",
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created superuser 'admin' (password: {password})"))
        else:
            self.stdout.write("Superuser 'admin' already exists – skipped")

        # ── 2. Health profile ─────────────────────────────────────────
        profile, created = UserHealthProfile.objects.get_or_create(
            user=user,
            defaults={
                "sensitivity_preset": "NORMAL",
                "email_notifications_enabled": False,  # off for dev
                "migraine_predictions_enabled": True,
                "sinusitis_predictions_enabled": True,
                "notification_mode": "IMMEDIATE",
                "language": "en",
                "ui_version": "v2",
                "theme": "light",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created health profile for admin"))
        else:
            self.stdout.write("Health profile for admin already exists – skipped")

        # ── 3. Sample location (Athens, Greece) ───────────────────────
        location, created = Location.objects.get_or_create(
            user=user,
            city="Athens",
            defaults={
                "country": "Greece",
                "latitude": 37.9838,
                "longitude": 23.7275,
                "timezone": "Europe/Athens",
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created sample location: Athens, Greece"))
        else:
            self.stdout.write("Location 'Athens' already exists – skipped")

        # ── 4. LLM configuration (disabled by default for dev) ───────
        llm_config, created = LLMConfiguration.objects.get_or_create(
            name="Local Dev",
            defaults={
                "is_active": True,
                "base_url": "http://host.docker.internal:11434",
                "model": "ibm/granite4:3b-h",
                "api_key": "",
                "timeout": 240.0,
                "confidence_threshold": 0.8,
            },
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created LLM configuration 'Local Dev'"))
        else:
            self.stdout.write("LLM configuration 'Local Dev' already exists – skipped")

        self.stdout.write(self.style.SUCCESS("\n✓ Seed data complete. Log in at http://localhost:8889/admin/ with admin / " + password))  # noqa
