from django.conf import settings

# Add email settings to Django settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'  # Example for Gmail
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@gmail.com'  # Replace with actual email in production
EMAIL_HOST_PASSWORD = 'your-app-password'  # Replace with actual app password in production
DEFAULT_FROM_EMAIL = 'Migraine Forecast <your-email@gmail.com>'

# For development/testing, you can use the console backend
if settings.DEBUG:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
