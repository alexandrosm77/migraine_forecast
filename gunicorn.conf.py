# Gunicorn configuration file
import os

# Server socket
bind = "0.0.0.0:8889"
backlog = 2048

# Worker processes
workers = int(os.getenv("GUNICORN_WORKERS", "2"))
worker_class = "sync"
worker_connections = 1000
timeout = 300  # Important for LLM inference - 5 minutes to handle slow model responses
keepalive = 5

# Restart workers after this many requests to prevent memory leaks
max_requests = 1000
max_requests_jitter = 50

# Logging
accesslog = "-"  # Log to stdout
errorlog = "-"  # Log to stderr
loglevel = os.getenv("LOG_LEVEL", "info").lower()

# Configure log format based on LOG_FORMAT environment variable
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()

# For now, keep it simple - just use text format
# JSON logging for Gunicorn access logs is complex and can cause startup issues
# Django and Celery will still use JSON format when LOG_FORMAT=json
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Process naming
proc_name = "migraine_forecast"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (if needed in the future)
# keyfile = None
# certfile = None
