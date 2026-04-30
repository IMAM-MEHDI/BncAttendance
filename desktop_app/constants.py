# Desktop Application Constants
from utils.config import settings

CURRENT_VERSION = settings.VERSION
BASE_URL = settings.BACKEND_BASE_URL
VERSION_CHECK_URL = f"{BASE_URL}/api/v1/version"
