"""
Context processors for the forecast app.

Context processors add variables to the template context globally.
"""

from forecast.__version__ import __version__


def version_context(request):
    """
    Add version information and UI preferences to all template contexts.

    This makes the APP_VERSION and UI_VERSION variables available in all templates.
    """
    ui_version = "v2"
    theme = "light"

    if request.user.is_authenticated:
        try:
            ui_version = request.user.health_profile.ui_version
            theme = request.user.health_profile.theme
        except Exception:
            pass

    return {
        "APP_VERSION": __version__,
        "UI_VERSION": ui_version,
        "THEME": theme,
    }
