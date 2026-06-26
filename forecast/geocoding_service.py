"""Provider-neutral geocoding helpers for tracked locations."""

import logging

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_TIMEZONE = "UTC"
_timezone_finder = None


class GeocodingProviderError(Exception):
    """Raised when the configured geocoding provider is unavailable."""


def detect_timezone(latitude, longitude):
    """Return an IANA timezone for coordinates, falling back to UTC."""
    global _timezone_finder
    try:
        from timezonefinder import TimezoneFinder
    except ImportError:
        return DEFAULT_TIMEZONE

    try:
        if _timezone_finder is None:
            _timezone_finder = TimezoneFinder()
        return _timezone_finder.timezone_at(lat=float(latitude), lng=float(longitude)) or DEFAULT_TIMEZONE
    except Exception:
        logger.exception("Timezone detection failed")
        return DEFAULT_TIMEZONE


def search_locations(query, limit=None):
    """Search for location candidates and return normalized dictionaries."""
    normalized_query = " ".join((query or "").strip().split())
    if len(normalized_query) < 3:
        raise ValueError("Search query must be at least 3 characters.")

    limit = int(limit or getattr(settings, "GEOCODING_SEARCH_LIMIT", 5))
    cache_key = f"geocoding:search:v1:{limit}:{normalized_query.lower()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response = requests.get(
            NOMINATIM_SEARCH_URL,
            params={"q": normalized_query, "format": "jsonv2", "addressdetails": 1, "limit": limit},
            headers={"User-Agent": getattr(settings, "GEOCODING_USER_AGENT", "Kalliro")},
            timeout=getattr(settings, "GEOCODING_TIMEOUT_SECONDS", 5),
        )
        response.raise_for_status()
        results = [_normalize_nominatim_result(item) for item in response.json()[:limit]]
    except Exception as exc:
        raise GeocodingProviderError("Location search is temporarily unavailable.") from exc

    cache.set(cache_key, results, getattr(settings, "GEOCODING_SEARCH_CACHE_SECONDS", 86400))
    return results


def reverse_geocode(latitude, longitude):
    """Reverse geocode coordinates and return one normalized place dictionary."""
    latitude = float(latitude)
    longitude = float(longitude)
    try:
        response = requests.get(
            NOMINATIM_REVERSE_URL,
            params={"lat": latitude, "lon": longitude, "format": "jsonv2", "addressdetails": 1},
            headers={"User-Agent": getattr(settings, "GEOCODING_USER_AGENT", "Kalliro")},
            timeout=getattr(settings, "GEOCODING_TIMEOUT_SECONDS", 5),
        )
        response.raise_for_status()
        return _normalize_nominatim_result(response.json(), latitude=latitude, longitude=longitude)
    except Exception as exc:
        raise GeocodingProviderError("Reverse geocoding is temporarily unavailable.") from exc


def _normalize_nominatim_result(item, latitude=None, longitude=None):
    address = item.get("address") or {}
    lat = float(latitude if latitude is not None else item.get("lat"))
    lon = float(longitude if longitude is not None else item.get("lon"))
    city = _first_present(address, ["city", "town", "village", "municipality", "suburb", "county"])
    country = address.get("country", "")
    label = city or item.get("name") or (item.get("display_name", "").split(",")[0].strip())
    return {
        "display_name": item.get("display_name", ""),
        "label": label,
        "city": city,
        "country": country,
        "latitude": lat,
        "longitude": lon,
        "timezone": detect_timezone(lat, lon),
    }


def _first_present(mapping, keys):
    for key in keys:
        value = mapping.get(key)
        if value:
            return value
    return ""
