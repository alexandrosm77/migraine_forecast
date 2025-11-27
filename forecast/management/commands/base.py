"""Base command class for management commands with JSON logging support."""

import os
from io import StringIO

from django.core.management.base import BaseCommand


class SilentStdoutCommand(BaseCommand):
    """
    Base command that suppresses stdout.write() when LOG_FORMAT=json.

    In production (Kubernetes), we only want structured JSON logs going to Promtail/Loki.
    The self.stdout.write() calls are for interactive terminal use during local development.

    Usage:
        from forecast.management.commands.base import SilentStdoutCommand

        class Command(SilentStdoutCommand):
            def handle(self, *args, **options):
                self.stdout.write("This will be suppressed in production")
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Suppress stdout when LOG_FORMAT=json (production/Kubernetes)
        if os.environ.get("LOG_FORMAT", "text").lower() == "json":
            self.stdout = type(self).NullOutput()

    class NullOutput:
        """A no-op output class that discards all writes."""

        def write(self, msg):
            pass

        def flush(self):
            pass

        # Support Django's style methods
        class style:
            @staticmethod
            def SUCCESS(msg):
                return msg

            @staticmethod
            def WARNING(msg):
                return msg

            @staticmethod
            def ERROR(msg):
                return msg

            @staticmethod
            def NOTICE(msg):
                return msg

            @staticmethod
            def HTTP_INFO(msg):
                return msg

            @staticmethod
            def MIGRATE_HEADING(msg):
                return msg

            @staticmethod
            def MIGRATE_LABEL(msg):
                return msg

