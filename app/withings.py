# Withings public API (OAuth 2): body measurements from the Body Scan. Connect once on the Setup page; the refresh
# token is stored in the kv table and renewed on every sync (Withings tokens last 3 hours, refresh tokens a year).
import json
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
# Body Scan segments: the type says what, the measure's "position" says where. Positions per Withings' API reference;
# unknown ones are kept as seg_<what>_p<position> so nothing is lost if the list changes.
SEG_TYPES = {173: 'ffm', 174: 'fat', 175: 'muscle'}
POSITIONS = {2: 'right_arm', 3: 'left_arm', 10: 'left_leg', 11: 'right_leg', 12: 'trunk'}
EXTRACT_VERSION = 2


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


def extract_group(con, day, grp):
    for meas in grp.get('measures', []):
        value = meas['value'] * 10 ** meas['unit']
        if meas['type'] in SEG_TYPES and meas.get('position') is not None:
            pos = meas['position']
            db.put_metric(con, day, f'seg_{SEG_TYPES[meas["type"]]}_{POSITIONS.get(pos, f"p{pos}")}', value, 'withings')
        elif meas['type'] in TYPES:
            db.put_metric(con, day, TYPES[meas['type']], value, 'withings')


def reextract():
    """Re-reads stored measurement groups after the extraction changed, without calling Withings."""
    if db.kv_get('withings_extract_version') == EXTRACT_VERSION:
        return
    with db.tx() as con:
        rows = con.execute("SELECT day, json FROM raw WHERE source='withings' ORDER BY json_extract(json, '$.date')").fetchall()
        for r in rows:
            extract_group(con, r['day'], json.loads(r['json']))
    db.kv_set('withings_extract_version', EXTRACT_VERSION)


def _fetch(kind, last, meastypes=None):
    offset, groups = 0, 0
    while True:
        params = {'action': 'getmeas', 'category': 1, 'lastupdate': last}
        if meastypes:
            params['meastypes'] = meastypes
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
                db.put_raw(con, 'withings', f'{kind}{grp["grpid"]}', day, grp)
                extract_group(con, day, grp)
                groups += 1
        if not b.get('more'):
            return groups
        offset = b.get('offset', 0)


def sync():
    if not connected():
        return
    log = db.log_start('withings')
    try:
        started = int(time.time())
        groups = _fetch('grp', db.kv_get('withings_lastupdate', 0))
        db.kv_set('withings_lastupdate', started)
        # Segment values are asked for by type as well, in case the plain call leaves them out. Its own
        # lastupdate starts at 0, so the first run fetches the whole Body Scan history.
        msg = f'{groups} measurements'
        try:
            seg = _fetch('seg', db.kv_get('withings_seg_lastupdate', 0), ','.join(str(t) for t in SEG_TYPES))
            db.kv_set('withings_seg_lastupdate', started)
            msg += f', {seg} with body segments'
        except Exception as e:
            msg += f'; body segments failed: {e}'
        db.log_end(log, 'ok', msg)
    except Exception as e:
        db.log_end(log, 'error', f'{type(e).__name__}: {e}')
        raise
