import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

def get_base_path():
    """Get the base path of the application, handles PyInstaller bundles."""
    if getattr(sys, 'frozen', False):
        # If running as a frozen executable, return the directory of the EXE
        return Path(sys.executable).parent
    else:
        # In development, return the project root
        return Path(__file__).resolve().parent.parent.parent

# Base directory for external files (like .env)
BASE_DIR = get_base_path()

# For bundled resources, we need sys._MEIPASS
def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = str(Path(__file__).resolve().parent.parent.parent)
    return os.path.join(base_path, relative_path)

# Load environment variables from the EXE directory (for production config)
load_dotenv(BASE_DIR / ".env")

class Config:
    def __init__(self):
        # Load JSON config (Bundled as a resource)
        config_path = get_resource_path(os.path.join("configs", "app_config.json"))
        try:
            with open(config_path, "r") as f:
                self._data = json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            self._data = {}

        # Environment Variables (Sensitive)
        # Default to SQLite for zero-installation offline support
        if getattr(sys, 'frozen', False):
            # When installed, Program Files is read-only. Use APPDATA.
            appdata_dir = Path(os.getenv('APPDATA', os.path.expanduser('~'))) / 'BncAttendance'
            appdata_dir.mkdir(parents=True, exist_ok=True)
            default_db_path = appdata_dir / "local_attendance.db"
        else:
            default_db_path = BASE_DIR / "local_attendance.db"
            
        self.DATABASE_URL = os.getenv("LOCAL_DATABASE_URL", f"sqlite:///{default_db_path}")
        
        self.BACKEND_SYNC_URL = os.getenv("BACKEND_SYNC_URL")
        self.DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD")
        self.CLOUD_ADMIN_ENROLLMENT = os.getenv("CLOUD_ADMIN_ENROLLMENT", "admin")
        self.CLOUD_ADMIN_PASSWORD = os.getenv("CLOUD_ADMIN_PASSWORD", "")
        
        # Derived values
        self.BACKEND_BASE_URL = self.BACKEND_SYNC_URL.split("/api/v1/")[0] if self.BACKEND_SYNC_URL else "http://localhost:8000"

        # JSON values (Direct access)
        self.VERSION = self._data.get("version", "0.0.1")
        self.THEME = self._data.get("theme", {})
        self.KIOSK = self._data.get("kiosk", {})
        self.SYNC = self._data.get("sync", {})
        self.NETWORK = self._data.get("network", {})

    def get_theme_color(self, key, default="#000000"):
        return self.THEME.get(key, default)

# Singleton instance
settings = Config()
