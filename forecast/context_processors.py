"""
Context processors for the forecast app.

Context processors add variables to the template context globally.
"""

from forecast.__version__ import __version__


def version_context(request):
    """
    Add version information to all template contexts.
    
    This makes the APP_VERSION variable available in all templates.
    """
    return {
        'APP_VERSION': __version__,
    }
