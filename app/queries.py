# Read side: series, weekly totals, training load and strength numbers for the pages, all from the local database.
from collections import defaultdict
from datetime import date, timedelta

from . import db


def _days(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def daily(metric, start, end):
    with db.connect() as con:
        rows = con.execute('SELECT day, value FROM metrics WHERE metric=? AND day BETWEEN ? AND ? ORDER BY day',
                           (metric, start.isoformat(), end.isoformat())).fetchall()
    return [(r['day'], r['value']) for r in rows]


def kcal_in(start, end):
    # The CSV export wins over the calorie total MyFitnessPal syncs to Garmin.
    merged = dict(daily('kcal_in_garmin', start, end))
    merged.update(dict(daily('kcal_in', start, end)))
    return sorted(merged.items())


def rolling(points, window=7):
    """Trailing average over calendar days (not over the last N readings), so gaps don't stretch the window."""
    out = []
    by_day = {date.fromisoformat(d): v for d, v in points}
    for d, _ in points:
        day = date.fromisoformat(d)
        vals = [by_day[x] for x in (day - timedelta(days=i) for i in range(window)) if x in by_day]
        out.append((d, sum(vals) / len(vals)))
    return out


def weekly(points, how='mean'):
    groups = defaultdict(list)
    for d, v in points:
        day = date.fromisoformat(d)
        groups[(day - timedelta(days=day.weekday())).isoformat()].append(v)
    agg = (lambda v: sum(v) / len(v)) if how == 'mean' else sum
    return sorted((w, agg(v)) for w, v in groups.items())


def first_day():
    with db.connect() as con:
        row = con.execute('SELECT MIN(d) AS d FROM (SELECT MIN(day) AS d FROM metrics UNION SELECT MIN(day) FROM activities '
                          'UNION SELECT MIN(day) FROM sets)').fetchone()
    return date.fromisoformat(row['d']) if row and row['d'] else date.today() - timedelta(days=90)


def activities(start, end):
    with db.connect() as con:
        return [dict(r) for r in con.execute(
            'SELECT id, day, start_time, type, name, duration_s, distance_m, avg_hr, kcal, training_load '
            'FROM activities WHERE day BETWEEN ? AND ? ORDER BY start_time DESC', (start.isoformat(), end.isoformat()))]


def training_load(start, end):
    """Fitness (42-day) and fatigue (7-day) as exponentially weighted averages of Garmin's per-activity training load,
    the same model as TrainingPeaks' CTL/ATL. Warmed up on 120 days before the range so the start isn't zero."""
    warm = start - timedelta(days=120)
    loads = defaultdict(float)
    for a in activities(warm, end):
        loads[a['day']] += a['training_load'] or 0
    atl = ctl = 0.0
    out = []
    for d in _days(warm, end):
        x = loads.get(d.isoformat(), 0.0)
        atl += (x - atl) / 7
        ctl += (x - ctl) / 42
        if d >= start:
            out.append((d.isoformat(), round(ctl, 1), round(atl, 1)))
    return out


def weekly_hours_by_type(start, end, top=3):
    hours = defaultdict(lambda: defaultdict(float))
    totals = defaultdict(float)
    for a in activities(start, end):
        day = date.fromisoformat(a['day'])
        week = (day - timedelta(days=day.weekday())).isoformat()
        t = (a['type'] or 'other').replace('_', ' ')
        h = (a['duration_s'] or 0) / 3600
        hours[week][t] += h
        totals[t] += h
    keep = [t for t, _ in sorted(totals.items(), key=lambda kv: -kv[1])[:top]]
    series = {t: [] for t in keep}
    if len(totals) > top:
        series['other'] = []
    for week in sorted(hours):
        for t in series:
            v = hours[week].get(t, 0) if t != 'other' else sum(h for k, h in hours[week].items() if k not in keep)
            series[t].append((week, round(v, 2)))
    return series


def e1rm(weight, reps):
    # Epley; above 12 reps the estimate gets unreliable, so those sets don't count.
    if not weight or not reps or reps > 12:
        return None
    return weight if reps == 1 else weight * (1 + reps / 30)


def exercises(start, end):
    with db.connect() as con:
        return [dict(r) for r in con.execute(
            'SELECT exercise, COUNT(DISTINCT day) AS sessions, MAX(day) AS last FROM sets WHERE day BETWEEN ? AND ? '
            'GROUP BY exercise ORDER BY sessions DESC', (start.isoformat(), end.isoformat()))]


def strength(exercise, start, end):
    with db.connect() as con:
        rows = con.execute('SELECT day, weight_kg, reps FROM sets WHERE exercise=? AND day BETWEEN ? AND ? ORDER BY day',
                           (exercise, start.isoformat(), end.isoformat())).fetchall()
    best, top_set, volume = {}, {}, defaultdict(float)
    for r in rows:
        v = e1rm(r['weight_kg'], r['reps'])
        if v and v > best.get(r['day'], 0):
            best[r['day']] = round(v, 1)
        if r['weight_kg'] and r['weight_kg'] > top_set.get(r['day'], 0):
            top_set[r['day']] = r['weight_kg']
        volume[r['day']] += (r['weight_kg'] or 0) * (r['reps'] or 0)
    return sorted(best.items()), sorted(top_set.items()), sorted(volume.items())


def strength_summary(start, end):
    """Per lift: best estimated 1RM in the first and last session of the range."""
    out = []
    for ex in exercises(start, end)[:15]:
        best, _, _ = strength(ex['exercise'], start, end)
        if best:
            out.append({**ex, 'first': best[0][1], 'latest': best[-1][1], 'peak': max(v for _, v in best)})
    return out


def weekly_volume(start, end):
    with db.connect() as con:
        rows = con.execute('SELECT day, SUM(weight_kg * reps) AS v FROM sets WHERE day BETWEEN ? AND ? GROUP BY day',
                           (start.isoformat(), end.isoformat())).fetchall()
    return weekly([(r['day'], r['v'] or 0) for r in rows], 'sum')


def latest(metric, on_or_before, window_days=45):
    pts = daily(metric, on_or_before - timedelta(days=window_days), on_or_before)
    return pts[-1] if pts else None


def avg(points):
    return sum(v for _, v in points) / len(points) if points else None


def withings_fields():
    """Measure types and body positions Withings has sent, to check the segment mapping against real data."""
    groups = defaultdict(list)
    with db.connect() as con:
        for r in con.execute("SELECT json_extract(m.value, '$.type') AS t, json_extract(m.value, '$.position') AS p, "
                             "json_extract(m.value, '$.value') AS v, json_extract(m.value, '$.unit') AS u "
                             "FROM raw, json_each(raw.json, '$.measures') AS m WHERE raw.source = 'withings'"):
            groups[(r['t'], r['p'])].append(r['v'] * 10 ** r['u'])
    return [{'type': t, 'position': p, 'n': len(v), 'avg': round(sum(v) / len(v), 2)}
            for (t, p), v in sorted(groups.items(), key=lambda kv: (kv[0][0] or 0, -1 if kv[0][1] is None else kv[0][1]))]


def sync_status():
    with db.connect() as con:
        last = {r['source']: dict(r) for r in con.execute(
            'SELECT s.* FROM sync_log s JOIN (SELECT source, MAX(id) AS id FROM sync_log GROUP BY source) m ON s.id = m.id')}
        recent = [dict(r) for r in con.execute('SELECT * FROM sync_log ORDER BY id DESC LIMIT 15')]
        counts = {r['source']: r['n'] for r in con.execute('SELECT source, COUNT(DISTINCT day) AS n FROM metrics GROUP BY source')}
        counts['activities'] = con.execute('SELECT COUNT(*) FROM activities').fetchone()[0]
        counts['sets'] = con.execute('SELECT COUNT(*) FROM sets').fetchone()[0]
        imports = [dict(r) for r in con.execute('SELECT * FROM imports ORDER BY imported_at DESC LIMIT 10')]
    return last, recent, counts, imports
