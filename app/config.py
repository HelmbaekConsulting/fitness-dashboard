# Settings from environment variables (.env locally, the container's variables on Unraid).
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get('DATA_DIR', 'data')).resolve()
IMPORT_DIR = Path(os.environ.get('IMPORT_DIR', str(DATA_DIR / 'import'))).resolve()
DB_PATH = DATA_DIR / 'fitness.db'

GARMIN_API_KEY = os.environ.get('GARMIN_API_KEY', '')
WITHINGS_CLIENT_ID = os.environ.get('WITHINGS_CLIENT_ID', '')
WITHINGS_CLIENT_SECRET = os.environ.get('WITHINGS_CLIENT_SECRET', '')
WITHINGS_REDIRECT_URI = os.environ.get('WITHINGS_REDIRECT_URI', 'http://localhost:8080/withings/callback')

# First day the history backfill reaches back to.
HISTORY_START = os.environ.get('HISTORY_START', '2019-01-01')
# Daily sync time, in the container's TZ.
SYNC_TIME = os.environ.get('SYNC_TIME', '05:30')
# Optional password for the web pages (HTTP basic auth, user "me").
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_DIR.mkdir(parents=True, exist_ok=True)
