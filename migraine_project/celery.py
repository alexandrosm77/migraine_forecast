"""
Celery configuration for migraine_forecast project.
"""
import os
import logging
from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'migraine_project.settings')

app = Celery('migraine_forecast')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()


@setup_logging.connect
def config_loggers(*args, **kwargs):
    """
    Configure Celery to use Django's logging configuration.
    This ensures Celery logs use the same format (JSON or text) as Django.
    """
    from logging.config import dictConfig
    from django.conf import settings

    # Use Django's LOGGING configuration for Celery
    dictConfig(settings.LOGGING)

# Celery Beat schedule
app.conf.beat_schedule = {
    # Weather data collection - every 2 hours
    'collect-weather-data': {
        'task': 'forecast.tasks.collect_weather_data',
        'schedule': crontab(minute=0, hour='*/2'),
    },
    
    # IMMEDIATE mode predictions - every 2 hours (30 min after weather)
    'schedule-immediate-predictions': {
        'task': 'forecast.tasks.schedule_immediate_predictions',
        'schedule': crontab(minute=30, hour='*/2'),
    },
    
    # DIGEST mode check - every 15 minutes (to catch user digest times)
    'schedule-digest-emails': {
        'task': 'forecast.tasks.schedule_digest_emails',
        'schedule': crontab(minute='*/15'),
    },
    
    # Cleanup old data - daily at 3 AM
    'cleanup-old-data': {
        'task': 'forecast.tasks.cleanup_old_data',
        'schedule': crontab(minute=0, hour=3),
    },
}

# Celery configuration
app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
)


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
