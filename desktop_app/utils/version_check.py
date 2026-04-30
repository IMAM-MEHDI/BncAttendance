import requests
import packaging.version
from constants import CURRENT_VERSION, VERSION_CHECK_URL

def get_latest_version_info():
    """
    Fetches version info from the backend.
    Returns a dict or None if request fails.
    """
    try:
        response = requests.get(VERSION_CHECK_URL, timeout=5)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"Version check failed: {e}")
    return None

def is_update_available(latest_info):
    """
    Compares local version with backend version.
    """
    if not latest_info or 'version' not in latest_info:
        return False
    
    try:
        local_v = packaging.version.parse(CURRENT_VERSION)
        latest_v = packaging.version.parse(latest_info['version'])
        return latest_v > local_v
    except Exception as e:
        print(f"Error parsing version: {e}")
        return False
