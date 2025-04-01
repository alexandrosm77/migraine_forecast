import os

from django.conf import settings

# Add email settings to Django settings
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', '192.168.0.5')
EMAIL_PORT = os.getenv('EMAIL_PORT', 25)
EMAIL_USE_TLS = False
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', 'alexandrosm77@gmail.com')
DEFAULT_FROM_EMAIL = 'Migraine Forecast <alexandrosm77@gmail.com>'

# For development/testing, you can use the console backend
# if settings.DEBUG:
#     EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
