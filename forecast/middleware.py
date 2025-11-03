from django.utils import translation
from django.utils.deprecation import MiddlewareMixin


class UserLanguageMiddleware(MiddlewareMixin):
    """
    Middleware to activate the user's preferred language from their profile.
    This should be placed after AuthenticationMiddleware in MIDDLEWARE settings.
    """

    def process_request(self, request):
        if request.user.is_authenticated:
            try:
                # Get the user's language preference from their health profile
                language = request.user.health_profile.language
                if language:
                    translation.activate(language)
                    request.LANGUAGE_CODE = language
            except Exception:
                # If the user doesn't have a health profile yet, use default language
                pass
