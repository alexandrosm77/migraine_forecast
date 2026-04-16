# Test package - imports all test classes for Django test discovery
from forecast.tests.test_models import *  # noqa: F401, F403
from forecast.tests.test_weather import *  # noqa: F401, F403
from forecast.tests.test_prediction_service import *  # noqa: F401, F403
from forecast.tests.test_llm_client import *  # noqa: F401, F403
from forecast.tests.test_forms import *  # noqa: F401, F403
from forecast.tests.test_tools import *  # noqa: F401, F403
from forecast.tests.test_notification_service import *  # noqa: F401, F403
from forecast.tests.test_views import *  # noqa: F401, F403
from forecast.tests.test_llm_context import *  # noqa: F401, F403
