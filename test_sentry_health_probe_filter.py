#!/usr/bin/env python
"""
Test script to verify that Kubernetes health probe requests are filtered from Sentry.
This script tests the sentry_traces_sampler and sentry_before_send functions.

Usage:
    python test_sentry_health_probe_filter.py
"""
import os
import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "migraine_project.settings")
django.setup()

from migraine_project.settings import sentry_traces_sampler, sentry_before_send


def test_traces_sampler():
    """Test that the traces sampler filters out Kubernetes health probes."""
    print("Testing sentry_traces_sampler...")
    
    # Test 1: Kubernetes health probe should return 0.0 (no sampling)
    kube_probe_context = {
        "wsgi_environ": {
            "PATH_INFO": "/",
            "HTTP_USER_AGENT": "kube-probe/1.33",
        }
    }
    result = sentry_traces_sampler(kube_probe_context)
    assert result == 0.0, f"Expected 0.0 for kube-probe, got {result}"
    print("✓ Kubernetes health probe filtered (sample rate: 0.0)")
    
    # Test 2: Normal browser request should use configured sample rate
    browser_context = {
        "wsgi_environ": {
            "PATH_INFO": "/",
            "HTTP_USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
    }
    result = sentry_traces_sampler(browser_context)
    assert result > 0.0, f"Expected > 0.0 for browser request, got {result}"
    print(f"✓ Normal browser request sampled (sample rate: {result})")
    
    # Test 3: Request to different path should use configured sample rate
    other_path_context = {
        "wsgi_environ": {
            "PATH_INFO": "/dashboard/",
            "HTTP_USER_AGENT": "kube-probe/1.33",
        }
    }
    result = sentry_traces_sampler(other_path_context)
    assert result > 0.0, f"Expected > 0.0 for non-root path, got {result}"
    print(f"✓ Non-root path sampled even with kube-probe UA (sample rate: {result})")
    
    print("\nAll traces_sampler tests passed! ✓\n")


def test_before_send():
    """Test that the before_send hook filters out Kubernetes health probes."""
    print("Testing sentry_before_send...")
    
    # Test 1: Transaction from Kubernetes health probe should be dropped
    kube_probe_transaction = {
        "type": "transaction",
        "transaction": "GET /",
        "request": {
            "headers": {
                "User-Agent": "kube-probe/1.33",
            }
        }
    }
    result = sentry_before_send(kube_probe_transaction, {})
    assert result is None, f"Expected None for kube-probe transaction, got {result}"
    print("✓ Kubernetes health probe transaction dropped")
    
    # Test 2: Normal transaction should pass through
    normal_transaction = {
        "type": "transaction",
        "transaction": "GET /",
        "request": {
            "headers": {
                "User-Agent": "Mozilla/5.0",
            }
        }
    }
    result = sentry_before_send(normal_transaction, {})
    assert result is not None, "Expected transaction to pass through"
    print("✓ Normal transaction passed through")
    
    # Test 3: Error from Kubernetes health probe should be dropped
    kube_probe_error = {
        "type": "error",
        "request": {
            "headers": {
                "User-Agent": "kube-probe/1.33",
            }
        }
    }
    result = sentry_before_send(kube_probe_error, {})
    assert result is None, f"Expected None for kube-probe error, got {result}"
    print("✓ Kubernetes health probe error dropped")
    
    # Test 4: Normal error should pass through
    normal_error = {
        "type": "error",
        "request": {
            "headers": {
                "User-Agent": "Mozilla/5.0",
            }
        }
    }
    result = sentry_before_send(normal_error, {})
    assert result is not None, "Expected error to pass through"
    print("✓ Normal error passed through")
    
    print("\nAll before_send tests passed! ✓\n")


def main():
    print("=" * 60)
    print("Sentry Health Probe Filter Test")
    print("=" * 60)
    print()
    
    test_traces_sampler()
    test_before_send()
    
    print("=" * 60)
    print("All tests passed! ✓")
    print("=" * 60)
    print("\nKubernetes health probes will now be filtered from Sentry.")
    print("Deploy your application and check Sentry to verify.")


if __name__ == "__main__":
    main()

