"""
Context processors for the forecast app.

Context processors add variables to the template context globally.
"""

from forecast.__version__ import __version__


def version_context(request):
    """
    Add version information and display preferences to all template contexts.

    This makes APP_VERSION and THEME available in all templates.
    """
    theme = "light"

    if request.user.is_authenticated:
        try:
            theme = request.user.health_profile.theme
        except Exception:
            pass

    return {
        "APP_VERSION": __version__,
        "THEME": theme,
    }
