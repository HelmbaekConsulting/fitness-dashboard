# Derived numbers for the body figures, workouts, recovery and energy: sets per muscle, Body Scan segments, Jefit
# sessions matched to Garmin activities, personal records, HR zones, trend weight, measured maintenance and readiness.
import json
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import db, muscles
from . import queries as q

SEGS = ['right_arm', 'left_arm', 'trunk', 'right_leg', 'left_leg']
SEG_LABEL = {'right_arm': 'Right arm', 'left_arm': 'Left arm', 'trunk': 'Trunk', 'right_leg': 'Right leg', 'left_leg': 'Left leg'}
SEG_GROUP = {'right_arm': 'arms', 'left_arm': 'arms', 'trunk': 'trunk', 'right_leg': 'legs', 'left_leg': 'legs'}
KCAL_PER_KG = 7700  # energy in a kilogram of body weight change, the usual rule of thumb


def week_of(day):
    d = date.fromisoformat(day)
    return (d - timedelta(days=d.weekday())).isoformat()


def _sets(start, end):
    with db.connect() as con:
        return con.execute('SELECT day, exercise FROM sets WHERE day BETWEEN ? AND ?', (start.isoformat(), end.isoformat())).fetchall()


# ---- Sets per muscle -------------------------------------------------------------------------------------------

VOLUME_BINS = [(0, 'l0'), (2, 'l1'), (5, 'l2'), (10, 'l3'), (15, 'l4'), (20, 'l5')]  # sets/week upper bounds; above: l6
VOLUME_LEGEND = [('l1', 'under 2'), ('l2', '2–5'), ('l3', '5–10'), ('l4', '10–15'), ('l5', '15–20'), ('l6', 'over 20')]
RECENCY_LEGEND = [('l6', '0–1 days'), ('l5', '2–3'), ('l4', '4–7'), ('l3', '8–14'), ('l2', '15–30'), ('l1', '31–90')]


def volume_class(per_week):
    if not per_week:
        return ''
    for limit, cls in VOLUME_BINS[1:]:
        if per_week <= limit:
            return cls
    return 'l6'


def recency_class(days):
    if days is None or days > 90:
        return ''
    for limit, cls in ((1, 'l6'), (3, 'l5'), (7, 'l4'), (14, 'l3'), (30, 'l2')):
        if days <= limit:
            return cls
    return 'l1'


def muscle_volume(start, end):
    """Per muscle: fractional sets in the range, sets per week, last day trained (any time up to the end)."""
    weeks = max(1.0, ((end - start).days + 1) / 7)
    totals, unmapped = defaultdict(float), defaultdict(int)
    for r in _sets(start, end):
        w = muscles.weights(r['exercise'])
        if not w and muscles.for_exercise(r['exercise'])[0] != [muscles.CARDIO]:
            unmapped[r['exercise']] += 1
        for m, credit in w.items():
            totals[m] += credit
    last = {}
    with db.connect() as con:
        rows = con.execute('SELECT exercise, MAX(day) AS last FROM sets WHERE day <= ? GROUP BY exercise', (end.isoformat(),)).fetchall()
    for r in rows:
        for m in muscles.weights(r['exercise']):
            if r['last'] > last.get(m, ''):
                last[m] = r['last']
    out = {}
    for m, (label, seg) in muscles.MUSCLES.items():
        days = (end - date.fromisoformat(last[m])).days if m in last else None
        out[m] = {'label': label, 'segment': seg, 'sets': round(totals.get(m, 0), 1), 'per_week': round(totals.get(m, 0) / weeks, 1),
                  'last': last.get(m), 'days_since': days}
    return out, sorted(unmapped.items(), key=lambda kv: -kv[1])


def muscle_weekly_by_segment(start, end):
    """{arms|trunk|legs: [(week, sets)]} for the segment charts."""
    out = {s: defaultdict(float) for s in muscles.SEGMENTS}
    for r in _sets(start, end):
        for m, credit in muscles.weights(r['exercise']).items():
            out[muscles.MUSCLES[m][1]][week_of(r['day'])] += credit
    weeks = []
    d = start - timedelta(days=start.weekday())
    while d <= end:
        weeks.append(d.isoformat())
        d += timedelta(days=7)
    return {s: [(w, round(v.get(w, 0), 1)) for w in weeks] for s, v in out.items()}


def balance(vol):
    """Push vs pull and upper vs lower body, from sets per week."""
    pw = lambda ms: sum(vol[m]['per_week'] for m in ms)
    push, pull = pw(['chest', 'front_delts', 'triceps']), pw(['lats', 'upper_back', 'rear_delts', 'biceps'])
    upper = pw([m for m, (_, s) in muscles.MUSCLES.items() if s in ('arms', 'trunk') and m not in ('abs', 'obliques', 'lower_back')])
    lower = pw(['glutes', 'quads', 'hamstrings', 'calves'])
    return {'push': round(push, 1), 'pull': round(pull, 1), 'upper': round(upper, 1), 'lower': round(lower, 1)}


# ---- Body Scan segments ----------------------------------------------------------------------------------------

def segment_change_class(pct, better_up=True):
    if pct is None:
        return 'd0'
    p = pct if better_up else -pct
    for limit, cls in ((3, 'dp3'), (1.5, 'dp2'), (0.5, 'dp1')):
        if p >= limit:
            return cls
    for limit, cls in ((-3, 'dn3'), (-1.5, 'dn2'), (-0.5, 'dn1')):
        if p <= limit:
            return cls
    return 'd0'


def segments(start, end, what='muscle'):
    """Per segment: first and latest Body Scan value in the range, change in kg and %, and the series."""
    out = {}
    for s in SEGS:
        pts = q.daily(f'seg_{what}_{s}', start, end)
        first, last = (pts[0][1], pts[-1][1]) if pts else (None, None)
        change = last - first if len(pts) > 1 else None
        pct = change / first * 100 if change is not None and first else None
        out[s] = {'label': SEG_LABEL[s], 'first': first, 'latest': last, 'change': change, 'pct': pct, 'points': pts,
                  'n': len(pts), 'first_day': pts[0][0] if pts else None, 'last_day': pts[-1][0] if pts else None}
    return out


def asymmetry(seg):
    """Right vs left, in % of their average (positive: right side larger)."""
    out = {}
    for part in ('arm', 'leg'):
        r, l = seg[f'right_{part}']['latest'], seg[f'left_{part}']['latest']
        out[part] = round((r - l) / ((r + l) / 2) * 100, 1) if r and l else None
    return out


def other_segment_metrics():
    """Segment metrics whose position isn't in the known list (seg_*_p<n>), to show rather than hide."""
    with db.connect() as con:
        return [r['metric'] for r in con.execute("SELECT DISTINCT metric FROM metrics WHERE metric LIKE 'seg\\_%\\_p%' ESCAPE '\\'")]


def monthly_timeline(start, end):
    """Months in the range with sets/week per muscle and Body Scan muscle per segment vs the first month."""
    months = []
    d = date(start.year, start.month, 1)
    while d <= end:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        months.append((d, min(nxt - timedelta(days=1), end)))
        d = nxt
    base = {}
    frames = []
    for m_start, m_end in months:
        lo = max(m_start, start)
        vol, _ = muscle_volume(lo, m_end)
        seg_vals = {}
        for s in SEGS:
            pts = q.daily(f'seg_muscle_{s}', lo, m_end)
            if pts:
                seg_vals[s] = sum(v for _, v in pts) / len(pts)
                base.setdefault(s, seg_vals[s])
        frames.append({
            'month': m_start.strftime('%B %Y'),
            'muscles': {m: [volume_class(v['per_week']), f'{v["label"]}: {v["per_week"]:.1f} sets/week'] for m, v in vol.items()},
            'segments': {s: [segment_change_class((seg_vals[s] - base[s]) / base[s] * 100 if s in seg_vals else None),
                             f'{SEG_LABEL[s]}: {seg_vals[s]:.2f} kg ({seg_vals[s] - base[s]:+.2f} kg)' if s in seg_vals else f'{SEG_LABEL[s]}: no scan'] for s in SEGS},
        })
    return frames


# ---- Workouts, calories per exercise, records ------------------------------------------------------------------

def _garmin_activities():
    # Any type: a session recorded on the watch as "cardio" or "other" still belongs to the Jefit session it overlaps.
    with db.connect() as con:
        rows = con.execute('SELECT id, json FROM activities').fetchall()
    out = []
    for r in rows:
        a = json.loads(r['json'] or '{}')
        if a.get('manualActivity') or a.get('isManualActivity'):
            continue  # typed-in entries (e.g. from MyFitnessPal) carry no measured calories or heart rate
        try:
            t0 = datetime.strptime(a['startTimeGMT'][:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc).timestamp()
        except (KeyError, ValueError, TypeError):
            continue
        out.append({'id': r['id'], 'start': t0, 'end': t0 + (a.get('duration') or 0), 'kcal': a.get('calories'),
                    'avg_hr': a.get('averageHR'), 'max_hr': a.get('maxHR'), 'name': a.get('activityName')})
    return out


STRENGTH_MET = 3.5  # Compendium of Physical Activities, resistance training, multiple exercises, 8–15 reps


def workouts(start, end):
    """Jefit sessions with the overlapping Garmin activity's calories and heart rate. Without a Garmin recording the
    calories are estimated as 3.5 MET × body weight × hours (close to Garmin's figure on the sessions that have both).
    Calories per exercise are split by sets: Jefit's per-exercise timestamps are too irregular to split by time."""
    with db.connect() as con:
        ws = [dict(r) for r in con.execute('SELECT * FROM workouts WHERE day BETWEEN ? AND ? ORDER BY start_ts DESC',
                                           (start.isoformat(), end.isoformat()))]
        sets = con.execute('SELECT session, exercise, COUNT(*) AS n, SUM(weight_kg * reps) AS vol, MAX(log_ts) AS t FROM sets '
                           'WHERE session IS NOT NULL AND day BETWEEN ? AND ? GROUP BY session, exercise',
                           (start.isoformat(), end.isoformat())).fetchall()
    by_session = defaultdict(list)
    for r in sets:
        by_session[r['session']].append(dict(r))
    garmin = _garmin_activities()
    for w in ws:
        w0, w1 = w['start_ts'], w['end_ts'] or (w['start_ts'] + (w['duration_s'] or 3600))
        best, overlap = None, 0
        for g in garmin:
            o = min(w1, g['end']) - max(w0, g['start'])
            if o > overlap and o > 0.3 * (w1 - w0):
                best, overlap = g, o
        w['garmin'] = best
        w['avg_hr'] = best['avg_hr'] if best else None
        if best and best['kcal']:
            w['kcal'], w['kcal_source'] = best['kcal'], 'garmin'
        else:
            weight = q.latest('weight_kg', date.fromisoformat(w['day']), 365)
            hours = (w['duration_s'] or 0) / 3600
            w['kcal'] = STRENGTH_MET * weight[1] * hours if weight and hours else None
            w['kcal_source'] = 'estimate' if w['kcal'] else None
        exs = sorted(by_session.get(w['id'], []), key=lambda e: e['t'] or 0)
        total_n = sum(e['n'] for e in exs)
        for e in exs:
            e['kcal'] = round(w['kcal'] * e['n'] / total_n) if w['kcal'] and total_n else None
        w['exercise_list'] = exs
    return ws


def exercise_kcal(exercise, ws):
    """Average calories per session for one exercise: (average, sessions, how many of them measured by Garmin)."""
    vals = [(e['kcal'], w['kcal_source']) for w in ws for e in w['exercise_list'] if e['exercise'] == exercise and e['kcal']]
    if not vals:
        return None, 0, 0
    return sum(v for v, _ in vals) / len(vals), len(vals), sum(1 for _, s in vals if s == 'garmin')


def records(start, end, limit=25):
    """New best estimated 1RM per exercise (beating every earlier session) set within the range."""
    with db.connect() as con:
        rows = con.execute('SELECT day, exercise, weight_kg, reps FROM sets WHERE day <= ? ORDER BY day', (end.isoformat(),)).fetchall()
    best_day = defaultdict(dict)
    for r in rows:
        v = q.e1rm(r['weight_kg'], r['reps'])
        if v and v > best_day[r['exercise']].get(r['day'], (0,))[0]:
            best_day[r['exercise']][r['day']] = (v, r['weight_kg'], r['reps'])
    out = []
    for ex, days in best_day.items():
        best = None
        for day in sorted(days):
            v, w, reps = days[day]
            if best is not None and v > best * 1.001 and day >= start.isoformat():
                out.append({'day': day, 'exercise': ex, 'e1rm': round(v, 1), 'previous': round(best, 1), 'set': f'{w:g} kg × {reps}'})
            best = max(best or 0, v)
    return sorted(out, key=lambda r: r['day'], reverse=True)[:limit]


# ---- Training: activity list, HR zones and calendar ------------------------------------------------------------

EFFECT_LABELS = {'RECOVERY': 'Recovery', 'AEROBIC_BASE': 'Base', 'TEMPO': 'Tempo', 'LACTATE_THRESHOLD': 'Threshold',
                 'VO2MAX': 'VO2 max', 'ANAEROBIC_CAPACITY': 'Anaerobic', 'SPEED': 'Speed', 'NO_BENEFIT': 'No benefit'}
PACE_TYPES = ('running', 'treadmill_running', 'trail_running', 'walking', 'hiking')


def type_label(t):
    return (t or 'other').replace('_', ' ').capitalize()


def _pace(a, t):
    """Pace (min/km) for runs and walks, speed (km/h) for rides, nothing for the rest."""
    sp = a.get('averageSpeed') or 0
    if sp <= 0 or not a.get('distance'):
        return None
    if t in PACE_TYPES:
        s = 1000 / sp
        return f'{int(s // 60)}:{int(s % 60):02d} /km'
    if 'cycling' in t or 'biking' in t:
        return f'{sp * 3.6:.1f} km/h'
    return None


def activity_rows(start, end, kind=None):
    """The Training table: one row per Garmin activity, with the fields Garmin fills for that type."""
    with db.connect() as con:
        sql = 'SELECT * FROM activities WHERE day BETWEEN ? AND ?' + (' AND type = ?' if kind else '') + ' ORDER BY start_time DESC'
        rows = con.execute(sql, (start.isoformat(), end.isoformat(), *([kind] if kind else []))).fetchall()
    dup = {a['id']: a['duplicate'] for a in q.activities(start, end, include_duplicates=True)}
    out = []
    for r in rows:
        a = json.loads(r['json'] or '{}')
        t = r['type'] or 'other'
        manual = bool(a.get('manualActivity') or a.get('isManualActivity'))
        zones = [(a.get(f'hrTimeInZone_{z}') or 0) / 60 for z in range(1, 6)]
        zt = sum(zones)
        out.append({
            'day': r['day'], 'time': (r['start_time'] or '')[11:16], 'name': r['name'] or type_label(t), 'type': t, 'type_label': type_label(t),
            'duration_s': r['duration_s'], 'distance_km': (r['distance_m'] or 0) / 1000 or None, 'pace': _pace(a, t),
            'kcal': r['kcal'], 'avg_hr': r['avg_hr'], 'max_hr': r['max_hr'], 'load': r['training_load'],
            'aerobic': r['aerobic_te'], 'anaerobic': r['anaerobic_te'], 'effect': EFFECT_LABELS.get(a.get('trainingEffectLabel'), ''),
            'ascent': a.get('elevationGain'), 'sweat_ml': a.get('waterEstimated'), 'steps': a.get('steps'),
            'cadence': a.get('averageRunningCadenceInStepsPerMinute'), 'sets': a.get('totalSets'), 'reps': a.get('totalReps'),
            'zones': [{'z': z + 1, 'min': round(m), 'pct': m / zt * 100} for z, m in enumerate(zones)] if zt else [],
            'manual': manual, 'duplicate': dup.get(r['id'], False),
            'source': 'MyFitnessPal' if (r['name'] or '').endswith('MyFitnessPal') else 'manual entry' if manual else '',
        })
        if out[-1]['source'] == 'MyFitnessPal':
            out[-1]['name'] = out[-1]['name'].rsplit(' - MyFitnessPal', 1)[0]
    return out


def activity_mix(rows):
    """Per activity type: count, hours, km, kcal and average HR, most time first."""
    agg = defaultdict(lambda: {'n': 0, 'hours': 0.0, 'km': 0.0, 'kcal': 0.0, 'hr': []})
    for r in rows:
        if r['duplicate']:
            continue
        g = agg[r['type']]
        g['n'] += 1
        g['hours'] += (r['duration_s'] or 0) / 3600
        g['km'] += r['distance_km'] or 0
        g['kcal'] += r['kcal'] or 0
        if r['avg_hr']:
            g['hr'].append(r['avg_hr'])
    return sorted(({'type': t, 'label': type_label(t), **g, 'avg_hr': sum(g['hr']) / len(g['hr']) if g['hr'] else None}
                   for t, g in agg.items()), key=lambda x: -x['hours'])

def hr_zones_weekly(start, end):
    """Minutes per HR zone per week, from Garmin's time-in-zone per activity."""
    zones = {z: defaultdict(float) for z in range(1, 6)}
    with db.connect() as con:
        rows = con.execute('SELECT day, json FROM activities WHERE day BETWEEN ? AND ?', (start.isoformat(), end.isoformat())).fetchall()
    for r in rows:
        a = json.loads(r['json'] or '{}')
        for z in range(1, 6):
            zones[z][week_of(r['day'])] += (a.get(f'hrTimeInZone_{z}') or 0) / 60
    weeks = sorted({w for z in zones.values() for w in z})
    return {z: [(w, round(zones[z].get(w, 0), 1)) for w in weeks] for z in zones}


def calendar(start, end):
    """Training minutes per day (Garmin activities, plus Jefit sessions without a matching Garmin activity)."""
    mins = defaultdict(float)
    for a in q.activities(start, end):
        mins[a['day']] += (a['duration_s'] or 0) / 60
    for w in workouts(start, end):
        if not w['garmin']:
            mins[w['day']] += (w['duration_s'] or 0) / 60
    first = start - timedelta(days=start.weekday())
    weeks = []
    d = first
    while d <= end:
        week = []
        for i in range(7):
            day = d + timedelta(days=i)
            m = mins.get(day.isoformat(), 0)
            cls = '' if day < start or day > end else ('l0' if not m else 'l2' if m < 30 else 'l4' if m < 60 else 'l6')
            week.append({'day': day.isoformat(), 'minutes': round(m), 'cls': cls, 'out': day < start or day > end})
        weeks.append(week)
        d += timedelta(days=7)
    active = sum(1 for v in mins.values() if v > 0)
    return weeks, active


def trips(start, end, min_days=3):
    """Runs of 3 or more days with activities only away from your usual places, to mark trips on charts. Usual places
    are the activity locations Garmin names in at least 3 different months of your history."""
    with db.connect() as con:
        rows = con.execute("SELECT day, json_extract(json, '$.locationName') AS loc FROM activities "
                           "WHERE json_extract(json, '$.locationName') IS NOT NULL").fetchall()
    months = defaultdict(set)
    for r in rows:
        months[r['loc']].add(r['day'][:7])
    home = {loc for loc, ms in months.items() if len(ms) >= 3} or {max(months, key=lambda k: len(months[k]))} if months else set()
    by_day = defaultdict(list)
    for r in rows:
        if start.isoformat() <= r['day'] <= end.isoformat():
            by_day[r['day']].append(r['loc'])
    away = sorted(d for d, locs in by_day.items() if not any(loc in home for loc in locs))
    runs, run = [], []
    for d in away:
        if run and (date.fromisoformat(d) - date.fromisoformat(run[-1])).days > 2:
            runs.append(run)
            run = []
        run.append(d)
    if run:
        runs.append(run)
    out = []
    for run in runs:
        if len(run) >= min_days:
            locs = [loc for d in run for loc in by_day[d]]
            out.append({'from': run[0], 'to': run[-1], 'label': max(set(locs), key=locs.count)})
    return out


# ---- Weight trend and measured maintenance --------------------------------------------------------------------

def trend_weight(start, end, alpha=0.1):
    """Exponentially smoothed weight (10% per day, as in The Hacker's Diet), warmed up on 60 days before the range.
    Days without a weigh-in carry the trend forward."""
    pts = dict(q.daily('weight_kg', start - timedelta(days=60), end))
    if not pts:
        return []
    out, t = [], None
    d = date.fromisoformat(min(pts))
    while d <= end:
        v = pts.get(d.isoformat())
        if v is not None:
            t = v if t is None else t + alpha * (v - t)
        if d >= start and t is not None:
            out.append((d.isoformat(), round(t, 2)))
        d += timedelta(days=1)
    return out


def expenditure(start, end, window=28, min_logged=18):
    """Measured maintenance calories per week: average calories eaten minus the energy in the trend weight change,
    over the previous 28 days. Needs at least 18 days with food logged in the window."""
    trend = dict(trend_weight(start - timedelta(days=window + 1), end))
    intake = dict(q.kcal_in(start - timedelta(days=window), end))
    out = []
    d = start + timedelta(days=(6 - start.weekday()) % 7)  # Sundays
    while d <= end:
        lo = d - timedelta(days=window)
        days = [x for x in intake if lo.isoformat() < x <= d.isoformat()]
        t0, t1 = trend.get(lo.isoformat()), trend.get(d.isoformat())
        if len(days) >= min_logged and t0 is not None and t1 is not None:
            eaten = sum(intake[x] for x in days) / len(days)
            out.append((d.isoformat(), round(eaten - (t1 - t0) * KCAL_PER_KG / window)))
        d += timedelta(days=7)
    return out


# ---- Readiness -------------------------------------------------------------------------------------------------

def hrv_band(start, end):
    """7-day average overnight HRV with its normal range: the 60-day mean ± one SD of the 7-day averages."""
    pts = q.daily('hrv_sleep', start - timedelta(days=70), end)
    roll = q.rolling(pts, 7)
    line, lo, hi = [], [], []
    j = 0
    for i, (d, v) in enumerate(roll):
        floor = (date.fromisoformat(d) - timedelta(days=60)).isoformat()
        while roll[j][0] < floor:
            j += 1
        prior = [x for _, x in roll[j:i]]
        if d >= start.isoformat():
            line.append((d, round(v, 1)))
            if len(prior) >= 20:
                m, sd = statistics.mean(prior), statistics.pstdev(prior)
                lo.append((d, round(m - sd, 1)))
                hi.append((d, round(m + sd, 1)))
    return line, lo, hi


def readiness(end):
    """Four checks against your own baselines. Each gives good / warning / serious with a short reason."""
    checks = []
    line, lo, hi = hrv_band(end - timedelta(days=7), end)
    if line and lo:
        v, low, high = line[-1][1], lo[-1][1], hi[-1][1]
        st = 'good' if low <= v <= high else ('warning' if v > high else 'serious')
        checks.append({'name': 'HRV', 'value': f'{v:.0f} ms', 'num': f'{v:.0f}', 'unit': 'ms', 'status': st,
                       'note': f'7-day average; your normal range is {low:.0f}–{high:.0f} ms',
                       'short': f'Your range {low:.0f}–{high:.0f} ms',
                       'off': f'HRV is {"above" if v > high else "below"} your normal range: {v:.0f} ms against {low:.0f}–{high:.0f}'})
    rhr = q.daily('resting_hr', end - timedelta(days=33), end)
    if len(rhr) >= 10:
        recent = [v for d, v in rhr if d > (end - timedelta(days=3)).isoformat()]
        base = [v for d, v in rhr if d <= (end - timedelta(days=3)).isoformat()]
        if recent and base:
            r, b = statistics.mean(recent), statistics.mean(base)
            st = 'good' if r <= b + 2 else 'warning' if r <= b + 5 else 'serious'
            checks.append({'name': 'Resting HR', 'value': f'{r:.0f} bpm', 'num': f'{r:.0f}', 'unit': 'bpm', 'status': st,
                           'note': f'last 3 days vs your 30-day average of {b:.0f} bpm',
                           'short': f'30-day average {b:.0f} bpm',
                           'off': f'Resting heart rate is up: {r:.0f} bpm against your usual {b:.0f}'})
    sleep = [v for d, v in q.daily('sleep_h', end - timedelta(days=2), end)]
    if sleep:
        s = statistics.mean(sleep)
        st = 'good' if s >= 7 else 'warning' if s >= 6 else 'serious'
        h, m = divmod(round(s * 60), 60)
        checks.append({'name': 'Sleep', 'value': f'{h}:{m:02d} h', 'num': f'{h}:{m:02d}', 'unit': 'h', 'status': st,
                       'note': 'average of the last 3 nights; 7 h or more is the usual advice', 'short': 'Last 3 nights; 7 h or more',
                       'off': f'Sleep is short: {h} h {m} min a night over the last three nights'})
    load = q.training_load(end - timedelta(days=1), end)
    if load and load[-1][1] >= 5:
        ratio = load[-1][2] / load[-1][1]
        st = 'good' if ratio <= 1.3 else 'warning' if ratio <= 1.5 else 'serious'
        checks.append({'name': 'Load', 'value': f'{ratio:.2f}', 'num': f'{ratio:.2f}', 'unit': '', 'status': st,
                       'note': 'fatigue ÷ fitness; up to 1.3 is a steady build, above 1.5 a sharp jump',
                       'short': 'Fatigue ÷ fitness; steady to 1.3',
                       'off': f'Load is climbing fast: fatigue is {ratio:.1f} times your fitness'})
    # Watch counts 1, off counts 2: one clearly off signal means take it easier, two or more mean recover.
    if not checks:
        return None, checks
    score = sum(['good', 'warning', 'serious'].index(c['status']) for c in checks)
    verdict = ('good', 'Good to train') if score == 0 else ('warning', 'Train, but keep it moderate') if score <= 2 \
        else ('serious', 'Prioritise recovery today')
    return verdict, checks
