# Garmin Connect sync via the unofficial garminconnect library. The login is done once (python -m app.cli garmin-login,
# which handles MFA); the saved tokens in DATA_DIR/garmin_tokens last about a year and are reused by the daily sync.
import json
import time
from datetime import date, timedelta

from garminconnect import Garmin

from . import db
from .config import GARMIN_EMAIL, GARMIN_PASSWORD, GARMIN_TOKEN_DIR, HISTORY_START

PAUSE = 1.0  # seconds between calls, to stay well clear of Garmin's rate limits
DAY_KINDS = ('summary', 'sleep', 'hrv', 'maxmetrics')


def has_tokens():
    return GARMIN_TOKEN_DIR.exists() and any(GARMIN_TOKEN_DIR.iterdir())


def login_interactive():
    g = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD, prompt_mfa=lambda: input('Garmin MFA code: ').strip())
    g.login()
    GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    g.garth.dump(str(GARMIN_TOKEN_DIR))
    return g.get_full_name()


def client():
    g = Garmin()
    if has_tokens():
        g.login(str(GARMIN_TOKEN_DIR))
        return g
    if not (GARMIN_EMAIL and GARMIN_PASSWORD):
        raise RuntimeError('No Garmin login yet: run "python -m app.cli garmin-login" once')
    g = Garmin(GARMIN_EMAIL, GARMIN_PASSWORD)
    g.login()
    GARMIN_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    g.garth.dump(str(GARMIN_TOKEN_DIR))
    return g


def _num(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d if isinstance(d, (int, float)) else None


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
        s = data.get('dailySleepDTO') or {}
        if _num(s, 'sleepTimeSeconds'):
            m('sleep_h', s['sleepTimeSeconds'] / 3600)
            for key, name in (('deepSleepSeconds', 'sleep_deep_h'), ('lightSleepSeconds', 'sleep_light_h'),
                              ('remSleepSeconds', 'sleep_rem_h'), ('awakeSleepSeconds', 'sleep_awake_h')):
                if _num(s, key) is not None:
                    m(name, s[key] / 3600)
            m('sleep_score', _num(s, 'sleepScores', 'overall', 'value'))
        m('hrv_sleep', _num(data, 'avgOvernightHrv'))
    elif kind == 'hrv':
        m('hrv_sleep', _num(data, 'hrvSummary', 'lastNightAvg'))
    elif kind == 'maxmetrics':
        rows = data if isinstance(data, list) else [data]
        for r in rows:
            m('vo2max', _num(r, 'generic', 'vo2MaxPreciseValue') or _num(r, 'generic', 'vo2MaxValue'))


def fetch_day(g, con, day):
    calls = {
        'summary': lambda: g.get_user_summary(day),
        'sleep': lambda: g.get_sleep_data(day),
        'hrv': lambda: g.get_hrv_data(day),
        'maxmetrics': lambda: g.get_max_metrics(day),
    }
    for kind, call in calls.items():
        try:
            data = call()
        except Exception as e:  # one missing endpoint (e.g. HRV on a Fenix 6) must not stop the day
            data = {'_error': str(e)[:300]}
        if data is None:
            data = {}
        db.put_raw(con, 'garmin', kind, day, data)
        if not (isinstance(data, dict) and '_error' in data):
            extract_day(con, day, kind, data)
        time.sleep(PAUSE)


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
    # Chunks of 30 days keep each response small.
    d = start
    n = 0
    while d <= end:
        chunk_end = min(d + timedelta(days=29), end)
        acts = g.get_activities_by_date(d.isoformat(), chunk_end.isoformat()) or []
        with db.tx() as con:
            for a in acts:
                save_activity(con, a)
        n += len(acts)
        d = chunk_end + timedelta(days=1)
        time.sleep(PAUSE)
    return n


def sync(recent_days=4, backfill=True, max_backfill_days=120):
    """Refetch the last few days (Garmin fills them in late), then work backwards through history in slices,
    so a full multi-year backfill spreads over a few nights instead of hammering Garmin at once."""
    log = db.log_start('garmin')
    try:
        g = client()
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
        if backfill and not db.kv_get('garmin_activities_backfilled'):
            acts_from = date.fromisoformat(HISTORY_START)
        n = fetch_activities(g, acts_from, today)
        if acts_from.isoformat() == HISTORY_START:
            db.kv_set('garmin_activities_backfilled', True)
        db.log_end(log, 'ok', f'{len(days)} days, {n} activities')
    except Exception as e:
        db.log_end(log, 'error', f'{type(e).__name__}: {e}')
        raise
