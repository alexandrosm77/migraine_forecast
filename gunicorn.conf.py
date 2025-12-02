# Gunicorn configuration file
import os
import json
import logging
from gunicorn.glogging import Logger


class JsonLogger(Logger):
    """
    Custom Gunicorn logger that outputs access logs in JSON format.
    This is used when LOG_FORMAT=json for structured logging.
    """
    def access(self, resp, req, environ, request_time):
        """Override access log to output JSON format."""
        if not self.cfg.accesslog:
            return

        # Build JSON log entry
        log_data = {
            'timestamp': self.now(),
            'level': 'info',
            'logger': 'gunicorn.access',
            'remote_addr': environ.get('REMOTE_ADDR', '-'),
            'request_method': environ.get('REQUEST_METHOD', '-'),
            'request_path': environ.get('PATH_INFO', '-'),
            'request_querystring': environ.get('QUERY_STRING', '-'),
            'request_protocol': environ.get('SERVER_PROTOCOL', '-'),
            'status_code': resp.status.split()[0] if resp.status else '-',
            'response_length': getattr(resp, 'sent', '-'),
            'referer': environ.get('HTTP_REFERER', '-'),
            'user_agent': environ.get('HTTP_USER_AGENT', '-'),
            'request_time_ms': int(request_time * 1000),
        }

        # Filter out health probe requests
        if 'kube-probe/' in log_data.get('user_agent', ''):
            return

        # Output JSON
        self.access_log.info(json.dumps(log_data))


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

if LOG_FORMAT == "json":
    # JSON format for structured logging (Promtail/Loki)
    # Use custom logger class for JSON access logs
    logger_class = JsonLogger

    # Configure error logs to use JSON format
    logconfig_dict = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'json': {
                '()': 'pythonjsonlogger.jsonlogger.JsonFormatter',
                'format': '%(asctime)s %(levelname)s %(name)s %(message)s %(process)d %(thread)d',
                'datefmt': '%Y-%m-%dT%H:%M:%S%z',
            },
        },
        'handlers': {
            'error_console': {
                'class': 'logging.StreamHandler',
                'formatter': 'json',
                'stream': 'ext://sys.stderr',
            },
        },
        'loggers': {
            'gunicorn.error': {
                'handlers': ['error_console'],
                'level': loglevel.upper(),
                'propagate': False,
            },
        },
    }
else:
    # Text format for human-readable logs (default)
    logger_class = 'gunicorn.glogging.Logger'
    access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
    logconfig_dict = None

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
