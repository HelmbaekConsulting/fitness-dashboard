# Settings from environment variables (.env locally, the container's variables on Unraid).
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get('DATA_DIR', 'data')).resolve()
IMPORT_DIR = Path(os.environ.get('IMPORT_DIR', str(DATA_DIR / 'import'))).resolve()
DB_PATH = DATA_DIR / 'fitness.db'
# Friends you invite get a folder each here, with their own database and upload folder.
USERS_DIR = DATA_DIR / 'users'

GARMIN_API_KEY = os.environ.get('GARMIN_API_KEY', '')
WITHINGS_CLIENT_ID = os.environ.get('WITHINGS_CLIENT_ID', '')
WITHINGS_CLIENT_SECRET = os.environ.get('WITHINGS_CLIENT_SECRET', '')
WITHINGS_REDIRECT_URI = os.environ.get('WITHINGS_REDIRECT_URI', 'http://localhost:8080/withings/callback')

# First day the history backfill reaches back to.
HISTORY_START = os.environ.get('HISTORY_START', '2019-01-01')
# Sync times, in the container's TZ; several allowed ("09:00,21:00").
SYNC_TIME = os.environ.get('SYNC_TIME', '09:00')
# Optional password on the home network (HTTP basic auth, user "me"). Outside, Cloudflare Access is the login.
DASHBOARD_PASSWORD = os.environ.get('DASHBOARD_PASSWORD', '')

# Outside access through Cloudflare Access. Requests that come through Cloudflare are only let in with a valid Access
# token from this team (and application, if CF_ACCESS_AUD is set). OWNER_EMAIL is your own login: it opens your
# dashboard and the admin page; other logins open the dashboard of the friend with that address.
_team = os.environ.get('CF_ACCESS_TEAM', '').strip().removeprefix('https://').strip('/')
CF_ACCESS_TEAM = _team if not _team or '.' in _team else _team + '.cloudflareaccess.com'
CF_ACCESS_AUD = os.environ.get('CF_ACCESS_AUD', '').strip()
OWNER_EMAIL = os.environ.get('OWNER_EMAIL', '').strip().lower()
# The outside address (https://fitness.example.com), for the invite message on the admin page.
PUBLIC_URL = os.environ.get('PUBLIC_URL', '').strip().rstrip('/')

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMPORT_DIR.mkdir(parents=True, exist_ok=True)
