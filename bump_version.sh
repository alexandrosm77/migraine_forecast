#!/bin/bash
# Version bumping script for Migraine Forecast
# 
# Usage:
#   ./bump_version.sh patch   # Bump patch version (0.1.0 -> 0.1.1)
#   ./bump_version.sh minor   # Bump minor version (0.1.0 -> 0.2.0)
#   ./bump_version.sh major   # Bump major version (0.1.0 -> 1.0.0)
#
# This script uses bump-my-version to manage semantic versioning.
# The version is stored in forecast/__version__.py and automatically
# synced to git tags.

set -e

# Check if bump-my-version is installed
if ! command -v bump-my-version &> /dev/null; then
    echo "Error: bump-my-version is not installed"
    echo "Install it with: pip install bump-my-version"
    exit 1
fi

# Check if argument is provided
if [ $# -eq 0 ]; then
    echo "Error: No version part specified"
    echo "Usage: $0 [major|minor|patch]"
    exit 1
fi

VERSION_PART=$1

# Validate version part
if [[ ! "$VERSION_PART" =~ ^(major|minor|patch)$ ]]; then
    echo "Error: Invalid version part '$VERSION_PART'"
    echo "Valid options are: major, minor, patch"
    exit 1
fi

# Show current version
CURRENT_VERSION=$(grep -oP '__version__ = "\K[^"]+' forecast/__version__.py)
echo "Current version: $CURRENT_VERSION"

# Bump version
echo "Bumping $VERSION_PART version..."
bump-my-version bump "$VERSION_PART"

# Show new version
NEW_VERSION=$(grep -oP '__version__ = "\K[^"]+' forecast/__version__.py)
echo "New version: $NEW_VERSION"

echo ""
echo "Version bumped successfully!"
echo "Don't forget to push the changes and tags:"
echo "  git push && git push --tags"

