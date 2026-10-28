# Garmin Connect sync via Garmin's official Personal API (https://developer.garmin.com/gc-developer-program/personal/).
# The personal key (GARMIN_API_KEY) is exchanged for a 24-hour access token; the key itself expires on the date chosen
# when it was created in Garmin Connect, after which a new one goes into .env. VO2 max is not offered by this API.
import json
import time
from datetime import date, timedelta

import requests

from . import db
from .config import GARMIN_API_KEY, HISTORY_START

BASE = 'https://personal.connectapi.garmin.com'
PAUSE = 1.0  # seconds between calls; Garmin publishes no rate limit, so stay gentle


def has_key():
    return bool(GARMIN_API_KEY)


class Client:
    def __init__(self):
        if not GARMIN_API_KEY:
            raise RuntimeError('GARMIN_API_KEY is missing: create a personal API key in Garmin Connect and add it to .env')
        r = requests.post(BASE + '/personalapitoken-service/personal-api/personal-api-key/token',
                          headers={'Authorization': f'ApiKey {GARMIN_API_KEY}'}, timeout=30)
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


def extract_day(con, day, kind, data):
    m = lambda name, value: db.put_metric(con, day, name, value, 'garmin')
    if kind == 'summary':
        m('steps', _num(data, 'totalSteps'))
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
    elif kind == 'hrv':
        m('hrv_sleep', _num(data, 'hrvSummary', 'lastNightAvg'))


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
