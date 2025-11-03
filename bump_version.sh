#!/bin/bash
# Version bumping script for Migraine Forecast
#
# Usage:
#   ./bump_version.sh patch   # Bump patch version (0.1.0 -> 0.1.1)
#   ./bump_version.sh minor   # Bump minor version (0.1.0 -> 0.2.0)
#   ./bump_version.sh major   # Bump major version (0.1.0 -> 1.0.0)
#
# This script uses bump-my-version (or bump2version) to manage semantic versioning.
# The version is stored in forecast/__version__.py and automatically
# synced to git tags.

set -e

# Check if bump-my-version or bumpversion is installed
if command -v bump-my-version &> /dev/null; then
    BUMP_CMD="bump-my-version"
elif command -v bumpversion &> /dev/null; then
    BUMP_CMD="bumpversion"
else
    echo "Error: Neither bump-my-version nor bumpversion is installed"
    echo "Install one with: pip install bump-my-version"
    echo "             or: pip install bump2version"
    exit 1
fi

echo "Using: $BUMP_CMD"

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
CURRENT_VERSION=$(python3 -c "import sys; sys.path.insert(0, '.'); from forecast.__version__ import __version__; print(__version__)")
echo "Current version: $CURRENT_VERSION"

# Bump version
echo "Bumping $VERSION_PART version..."
$BUMP_CMD bump "$VERSION_PART"

# Show new version
NEW_VERSION=$(python3 -c "import sys; sys.path.insert(0, '.'); from forecast.__version__ import __version__; print(__version__)")
echo "New version: $NEW_VERSION"

echo ""
echo "Version bumped successfully!"
echo "Don't forget to push the changes and tags:"
echo "  git push && git push --tags"

