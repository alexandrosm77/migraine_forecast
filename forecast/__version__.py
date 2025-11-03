"""
Version information for Migraine Forecast application.

This file serves as the single source of truth for version information.
Version follows Semantic Versioning (SemVer): MAJOR.MINOR.PATCH

- MAJOR: Incompatible API changes or major feature overhauls
- MINOR: New features in a backwards-compatible manner
- PATCH: Backwards-compatible bug fixes
"""

__version__ = "0.1.3"
__version_info__ = tuple(int(x) for x in __version__.split("."))

# Version metadata
VERSION_MAJOR = __version_info__[0]
VERSION_MINOR = __version_info__[1]
VERSION_PATCH = __version_info__[2]


def get_version():
    """Return the current version string."""
    return __version__


def get_version_info():
    """Return the version as a tuple of integers (major, minor, patch)."""
    return __version_info__
