# Withings public API (OAuth 2): body measurements from the Body Scan. Connect once on the Setup page; the refresh
# token is stored in the kv table and renewed on every sync (Withings tokens last 3 hours, refresh tokens a year).
import secrets
import time
from datetime import datetime
from urllib.parse import urlencode

import requests

from . import db
from .config import WITHINGS_CLIENT_ID, WITHINGS_CLIENT_SECRET, WITHINGS_REDIRECT_URI

AUTH_URL = 'https://account.withings.com/oauth2_user/authorize2'
TOKEN_URL = 'https://wbsapi.withings.net/v2/oauth2'
MEASURE_URL = 'https://wbsapi.withings.net/measure'

# Withings measure types -> our metric names (https://developer.withings.com/api-reference#tag/measure).
TYPES = {
    1: 'weight_kg', 5: 'lean_mass_kg', 6: 'fat_pct', 8: 'fat_mass_kg', 11: 'scale_hr', 76: 'muscle_kg',
    77: 'water_kg', 88: 'bone_kg', 91: 'pwv', 155: 'vascular_age', 170: 'visceral_fat', 226: 'bmr_kcal',
}


def configured():
    return bool(WITHINGS_CLIENT_ID and WITHINGS_CLIENT_SECRET)


def connected():
    return bool(db.kv_get('withings_token'))


def auth_url():
    state = secrets.token_urlsafe(16)
    db.kv_set('withings_state', state)
    return AUTH_URL + '?' + urlencode({
        'response_type': 'code', 'client_id': WITHINGS_CLIENT_ID, 'scope': 'user.metrics',
        'redirect_uri': WITHINGS_REDIRECT_URI, 'state': state,
    })


def _token_call(params):
    r = requests.post(TOKEN_URL, data={'action': 'requesttoken', 'client_id': WITHINGS_CLIENT_ID,
                                       'client_secret': WITHINGS_CLIENT_SECRET, **params}, timeout=30)
    body = r.json()
    if body.get('status') != 0:
        raise RuntimeError(f'Withings token error {body.get("status")}: {body.get("error", "")}')
    t = body['body']
    db.kv_set('withings_token', {'access': t['access_token'], 'refresh': t['refresh_token'],
                                 'expires': time.time() + int(t['expires_in']) - 60, 'userid': t.get('userid')})


def exchange_code(code, state):
    if state != db.kv_get('withings_state'):
        raise RuntimeError('Withings login expired or came from elsewhere: start again from the Setup page')
    _token_call({'grant_type': 'authorization_code', 'code': code, 'redirect_uri': WITHINGS_REDIRECT_URI})


def _access():
    t = db.kv_get('withings_token')
    if not t:
        raise RuntimeError('Withings is not connected yet: use the Setup page')
    if time.time() > t['expires']:
        _token_call({'grant_type': 'refresh_token', 'refresh_token': t['refresh']})
        t = db.kv_get('withings_token')
    return t['access']


def sync():
    if not connected():
        return
    log = db.log_start('withings')
    try:
        last = db.kv_get('withings_lastupdate', 0)
        started = int(time.time())
        offset, groups = 0, 0
        while True:
            params = {'action': 'getmeas', 'category': 1, 'lastupdate': last}
            if offset:
                params['offset'] = offset
            r = requests.post(MEASURE_URL, data=params, headers={'Authorization': f'Bearer {_access()}'}, timeout=60)
            body = r.json()
            if body.get('status') != 0:
                raise RuntimeError(f'Withings measure error {body.get("status")}: {body.get("error", "")}')
            b = body['body']
            with db.tx() as con:
                # Oldest first, so the last weigh-in of a day wins.
                for grp in sorted(b.get('measuregrps', []), key=lambda g: g['date']):
                    day = datetime.fromtimestamp(grp['date']).date().isoformat()
                    db.put_raw(con, 'withings', f'grp{grp["grpid"]}', day, grp)
                    for meas in grp.get('measures', []):
                        name = TYPES.get(meas['type'])
                        if name:
                            db.put_metric(con, day, name, meas['value'] * 10 ** meas['unit'], 'withings')
                    groups += 1
            if not b.get('more'):
                break
            offset = b.get('offset', 0)
        db.kv_set('withings_lastupdate', started)
        db.log_end(log, 'ok', f'{groups} measurements')
    except Exception as e:
        db.log_end(log, 'error', f'{type(e).__name__}: {e}')
        raise
