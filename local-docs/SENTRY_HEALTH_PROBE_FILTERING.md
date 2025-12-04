# Sentry Health Probe Filtering

This document explains how Kubernetes health probe requests are filtered from Sentry to reduce noise and quota usage.

## Problem

Kubernetes health probes (liveness and readiness) hit your application every 5-10 seconds:
- **Path**: `/` (root path)
- **User Agent**: `kube-probe/1.33` (or similar version)
- **Frequency**: Every 5-10 seconds

These requests were being sent to Sentry as:
- **Transactions** (performance monitoring)
- **Log messages** (Gunicorn access logs)
- **Breadcrumbs** (request tracking)
- **Errors** (if any occurred during health checks)

This created significant noise in Sentry and consumed quota unnecessarily.

## Solution

We implemented **multi-layer filtering** to catch health probe requests at every level:

### 1. Transaction Filtering (`sentry_traces_sampler`)
**Most efficient** - Prevents transactions from being created at all.

```python
def sentry_traces_sampler(sampling_context):
    wsgi_environ = sampling_context.get("wsgi_environ", {})
    path = wsgi_environ.get("PATH_INFO", "")
    user_agent = wsgi_environ.get("HTTP_USER_AGENT", "")
    
    # Don't sample Kubernetes health probes
    if path == "/" and user_agent.startswith("kube-probe/"):
        return 0.0  # 0% sampling rate
    
    return SENTRY_TRACES_SAMPLE_RATE  # Normal sampling for other requests
```

### 2. Log Filtering (`HealthProbeLogFilter`)
**Prevents Gunicorn access logs** from being sent to Sentry.

```python
class HealthProbeLogFilter:
    def filter(self, record):
        message = record.getMessage()
        if "kube-probe/" in message:
            return False  # Don't log
        return True
```

Applied to all log handlers including `gunicorn.access` logger.

### 3. Breadcrumb Filtering (`sentry_before_breadcrumb`)
**Prevents breadcrumbs** from being created for health probe requests.

```python
def sentry_before_breadcrumb(crumb, hint):
    # Check message and data for kube-probe
    if "kube-probe/" in crumb.get("message", ""):
        return None  # Drop breadcrumb
    if "kube-probe/" in str(crumb.get("data", {})):
        return None
    return crumb
```

### 4. Event Filtering (`sentry_before_send`)
**Fallback filter** for any events that slip through the above filters.

```python
def sentry_before_send(event, hint):
    # Filter transactions, errors, and log messages
    # containing kube-probe user agent
    # ...
    return event  # or None to drop
```

## Testing

Run the test script to verify all filters work correctly:

```bash
python test_sentry_health_probe_filter.py
```

This tests:
- ✓ Transaction filtering
- ✓ Error filtering
- ✓ Breadcrumb filtering
- ✓ Log message filtering

## Deployment

After deploying these changes:

1. **Monitor Sentry** - You should see a significant reduction in events
2. **Check logs** - Health probe logs will still appear in your local logs (stdout/file) but won't be sent to Sentry
3. **Verify normal traffic** - Regular user requests should still be tracked normally

## What Gets Filtered

- ✅ Transactions from `kube-probe/` user agent to `/` path
- ✅ Errors from `kube-probe/` user agent
- ✅ Breadcrumbs containing `kube-probe/`
- ✅ Log messages containing `kube-probe/` (including Gunicorn access logs)

## What Still Gets Tracked

- ✅ Normal user requests to `/` or any other path
- ✅ Errors from real users
- ✅ All other application logs and events
- ✅ Performance monitoring for real traffic

## Configuration

All filtering is configured in `migraine_project/settings.py`:
- `HealthProbeLogFilter` class (lines 177-191)
- `LOGGING` configuration with filters (lines 194-252)
- `sentry_traces_sampler()` function
- `sentry_before_breadcrumb()` function
- `sentry_before_send()` function
- Sentry SDK initialization with all hooks

## Notes

- Health probe requests will still appear in your **local logs** (stdout and log files)
- They just won't be sent to **Sentry/GlitchTip**
- This saves quota and reduces noise in your error tracking dashboard
- The filtering is specific to `kube-probe/` user agent, so it won't affect other monitoring tools

