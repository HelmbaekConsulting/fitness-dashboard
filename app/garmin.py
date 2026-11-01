# Garmin Connect sync via Garmin's official Personal API (https://developer.garmin.com/gc-developer-program/personal/).
# The personal key (GARMIN_API_KEY) is exchanged for a 24-hour access token; the key itself expires on the date chosen
# when it was created in Garmin Connect, after which a new one goes into .env. VO2 max is not offered by this API.
# Friends paste their own key on the Setup page; it's kept in their database (kv 'garmin_api_key'), which also wins
# over .env for the owner.
import json
import time
from datetime import date, datetime, timedelta, timezone

import requests

from . import db
from .config import DB_PATH, GARMIN_API_KEY, HISTORY_START

BASE = 'https://personal.connectapi.garmin.com'
PAUSE = 1.0  # seconds between calls; Garmin publishes no rate limit, so stay gentle
EXTRACT_VERSION = 2  # raise when extract_day changes; reextract() then re-reads the stored days


def api_key():
    return db.kv_get('garmin_api_key') or (GARMIN_API_KEY if db.current.get() == DB_PATH else '')


def has_key():
    return bool(api_key())


def check_key(key):
    """One token call, to tell a wrong or expired key straight away when it's pasted on the Setup page."""
    r = requests.post(BASE + '/personalapitoken-service/personal-api/personal-api-key/token',
                      headers={'Authorization': f'ApiKey {key}'}, timeout=30)
    return r.status_code == 200


class Client:
    def __init__(self):
        key = api_key()
        if not key:
            raise RuntimeError('No Garmin API key: create a personal API key in Garmin Connect and add it on the Setup page')
        r = requests.post(BASE + '/personalapitoken-service/personal-api/personal-api-key/token',
                          headers={'Authorization': f'ApiKey {key}'}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f'Garmin refused the API key (HTTP {r.status_code}); it may have expired')
        self.headers = {'Authorization': f'Bearer {r.text.strip()}', 'Accept': 'application/json'}

    def get(self, path, params=None):
        r = requests.get(BASE + path, headers=self.headers, params=params, timeout=60)
        time.sleep(PAUSE)
        if r.status_code == 404 or not r.content:
            return None
        r.raise_for_status()
        return r.json()


def _num(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d if isinstance(d, (int, float)) and not isinstance(d, bool) else None


def _clock(ms, evening=False):
    """Hour of the day from Garmin's "local" epoch milliseconds (local time written as if it were UTC); with evening,
    times after midnight count on from 24, so a 00:30 bedtime is 24.5 and sorts after 23:30."""
    if not isinstance(ms, (int, float)) or not ms:
        return None
    t = datetime.fromtimestamp(ms / 1000, timezone.utc)
    h = t.hour + t.minute / 60
    return h + 24 if evening and h < 15 else h


def extract_day(con, day, kind, data):
    m = lambda name, value: db.put_metric(con, day, name, value, 'garmin')
    hours = lambda seconds: seconds / 3600 if seconds is not None else None
    if kind == 'summary':
        m('steps', _num(data, 'totalSteps'))
        m('step_goal', _num(data, 'dailyStepGoal'))
        dist = _num(data, 'totalDistanceMeters')
        m('distance_km', dist / 1000 if dist is not None else None)
        m('floors', _num(data, 'floorsAscended'))
        m('floor_goal', _num(data, 'userFloorsAscendedGoal'))
        act, high = _num(data, 'activeSeconds'), _num(data, 'highlyActiveSeconds')
        if act is not None or high is not None:
            m('active_min', ((act or 0) + (high or 0)) / 60)
        m('intensity_goal', _num(data, 'intensityMinutesGoal'))  # a weekly goal in Garmin Connect
        for key, name in (('restStressDuration', 'stress_rest_h'), ('lowStressDuration', 'stress_low_h'),
                          ('mediumStressDuration', 'stress_med_h'), ('highStressDuration', 'stress_high_h')):
            m(name, hours(_num(data, key)))
        m('resp_waking', _num(data, 'avgWakingRespirationValue'))
        m('bb_charged', _num(data, 'bodyBatteryChargedValue'))
        m('bb_drained', _num(data, 'bodyBatteryDrainedValue'))
        m('resting_hr', _num(data, 'restingHeartRate'))
        stress = _num(data, 'averageStressLevel')
        m('stress_avg', stress if stress is not None and stress >= 0 else None)
        m('active_kcal', _num(data, 'activeKilocalories'))
        m('total_kcal', _num(data, 'totalKilocalories'))
        m('body_battery_high', _num(data, 'bodyBatteryHighestValue'))
        m('body_battery_low', _num(data, 'bodyBatteryLowestValue'))
        mod, vig = _num(data, 'moderateIntensityMinutes'), _num(data, 'vigorousIntensityMinutes')
        if mod is not None or vig is not None:
            m('intensity_min', (mod or 0) + 2 * (vig or 0))
        # Calories eaten, when MyFitnessPal syncs to Garmin Connect.
        consumed = _num(data, 'consumedKilocalories')
        if consumed:
            m('kcal_in_garmin', consumed)
    elif kind == 'sleep':
        s = data.get('dailySleepDTO', data)
        if _num(s, 'sleepTimeSeconds'):
            m('sleep_h', s['sleepTimeSeconds'] / 3600)
            for key, name in (('deepSleepSeconds', 'sleep_deep_h'), ('lightSleepSeconds', 'sleep_light_h'),
                              ('remSleepSeconds', 'sleep_rem_h'), ('awakeSleepSeconds', 'sleep_awake_h')):
                if _num(s, key) is not None:
                    m(name, s[key] / 3600)
            m('sleep_score', _num(s, 'sleepScores', 'overall', 'value'))
            m('bedtime', _clock(s.get('sleepStartTimestampLocal'), evening=True))
            m('waketime', _clock(s.get('sleepEndTimestampLocal')))
            m('spo2_sleep', _num(s, 'averageSpO2Value'))
            m('spo2_low', _num(s, 'lowestSpO2Value'))
            m('resp_sleep', _num(s, 'averageRespirationValue'))
            m('sleep_stress', _num(s, 'avgSleepStress'))
            m('awake_count', _num(s, 'awakeCount'))
    elif kind == 'hrv':
        m('hrv_sleep', _num(data, 'hrvSummary', 'lastNightAvg'))
        m('hrv_base_low', _num(data, 'hrvSummary', 'baseline', 'balancedLow'))
        m('hrv_base_high', _num(data, 'hrvSummary', 'baseline', 'balancedUpper'))


def reextract():
    """Re-reads the stored daily responses after extract_day changed, without calling Garmin."""
    if db.kv_get('garmin_extract_version') == EXTRACT_VERSION:
        return
    with db.tx() as con:
        for r in con.execute("SELECT day, kind, json FROM raw WHERE source='garmin'").fetchall():
            data = json.loads(r['json'])
            if '_error' not in data:
                extract_day(con, r['day'], r['kind'], data)
    db.kv_set('garmin_extract_version', EXTRACT_VERSION)


def fetch_day(g, con, day):
    calls = {
        'summary': ('/usersummary-service/usersummary/daily', {'calendarDate': day}),
        'sleep': ('/sleep-service/sleep/dailySleep', {'date': day}),
        'hrv': (f'/hrv-service/hrv/{day}', None),
    }
    for kind, (path, params) in calls.items():
        try:
            data = g.get(path, params) or {}
        except Exception as e:  # one failing endpoint must not stop the day
            data = {'_error': str(e)[:300]}
        db.put_raw(con, 'garmin', kind, day, data)
        if '_error' not in data:
            extract_day(con, day, kind, data)


def save_activity(con, a):
    day = (a.get('startTimeLocal') or '')[:10]
    if not day:
        return
    con.execute('INSERT OR REPLACE INTO activities VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
        str(a.get('activityId')), day, a.get('startTimeLocal'), (a.get('activityType') or {}).get('typeKey'),
        a.get('activityName'), a.get('duration'), a.get('distance'), a.get('averageHR'), a.get('maxHR'),
        a.get('calories'), a.get('activityTrainingLoad'), a.get('aerobicTrainingEffect'),
        a.get('anaerobicTrainingEffect'), json.dumps(a)))


def fetch_activities(g, start, end):
    # Pages of 100, newest first, until the page reaches past the start date.
    n, offset = 0, 0
    while True:
        page = g.get('/activitylist-service/activities/search/activities',
                     {'start': offset, 'limit': 100, 'startDate': start.isoformat(), 'endDate': end.isoformat()}) or []
        with db.tx() as con:
            for a in page:
                save_activity(con, a)
        n += len(page)
        offset += len(page)
        oldest = min(((a.get('startTimeLocal') or '')[:10] for a in page), default='')
        if len(page) < 100 or (oldest and oldest < start.isoformat()):
            return n


def sync(recent_days=4, backfill=True, max_backfill_days=120):
    """Refetch the last few days (Garmin fills them in late), then work backwards through history in slices,
    so a full multi-year backfill spreads over a few nights instead of hammering Garmin at once."""
    if not has_key():
        return
    log = db.log_start('garmin')
    try:
        g = Client()
        today = date.today()
        days = [today - timedelta(days=i) for i in range(recent_days)]
        if backfill:
            start = date.fromisoformat(HISTORY_START)
            with db.connect() as con:
                missing = []
                d = today - timedelta(days=recent_days)
                while d >= start and len(missing) < max_backfill_days:
                    if not db.has_raw(con, 'garmin', 'summary', d.isoformat()):
                        missing.append(d)
                    d -= timedelta(days=1)
            days += missing
        for d in days:
            with db.tx() as con:
                fetch_day(g, con, d.isoformat())
        # Activities: recent window always, full history once.
        acts_from = today - timedelta(days=14)
        full = backfill and not db.kv_get('garmin_activities_backfilled')
        if full:
            acts_from = date.fromisoformat(HISTORY_START)
        n = fetch_activities(g, acts_from, today)
        if full:
            db.kv_set('garmin_activities_backfilled', True)
        db.log_end(log, 'ok', f'{len(days)} days, {n} activities')
    except Exception as e:
        db.log_end(log, 'error', f'{type(e).__name__}: {e}')
        raise
