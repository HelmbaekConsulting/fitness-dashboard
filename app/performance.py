# The Performance page, from the Garmin activities already stored: the year so far against last year, weekly
# consistency, personal bests (fastest splits, power bests, longest and biggest sessions), training focus by Garmin's
# training-effect label, the cycling power curve, and running and cycling efficiency (output per heartbeat).
import json
from collections import defaultdict
from datetime import date, timedelta

from . import db, insights
from . import queries as q
from .today import type_icon

RUN_SPLITS = [('fastestSplit_1000', '1 km'), ('fastestSplit_1609', '1 mile'), ('fastestSplit_5000', '5 km'),
              ('fastestSplit_10000', '10 km'), ('fastestSplit_21098', 'Half marathon'), ('fastestSplit_42195', 'Marathon')]
RIDE_SPLITS = [('fastestSplit_40000', '40 km')]
POWER = [(1, '1 s'), (2, '2 s'), (5, '5 s'), (10, '10 s'), (20, '20 s'), (30, '30 s'), (60, '1 min'), (120, '2 min'),
         (300, '5 min'), (600, '10 min'), (1200, '20 min'), (1800, '30 min'), (3600, '1 h'), (7200, '2 h')]
POWER_CARDS = [5, 60, 300, 1200, 3600]
FOCUS = {'RECOVERY': 'low', 'AEROBIC_BASE': 'low', 'TEMPO': 'high', 'LACTATE_THRESHOLD': 'high', 'VO2MAX': 'high',
         'ANAEROBIC_CAPACITY': 'anaerobic', 'SPEED': 'anaerobic', 'SPRINT': 'anaerobic'}
FOCUS_INFO = [('low', 'Low aerobic', 's1', 'Recovery and base: easy, long, conversational'),
              ('high', 'High aerobic', 's2', 'Tempo, threshold and VO2 max: hard but sustained'),
              ('anaerobic', 'Anaerobic', 's7', 'Short, all-out efforts'),
              ('none', 'No label', 'other', 'Garmin gives strength, golf and similar sessions no training-effect label')]


def dmy(iso):
    return f'{iso[8:10]}/{iso[5:7]}/{iso[:4]}'


def clock(seconds):
    s = round(seconds)
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'


def is_run(t):
    return 'run' in (t or '')


def is_ride(t):
    return any(k in (t or '') for k in ('cycling', 'biking', 'ride'))


def activities(start, end):
    """Garmin activities in the range (typed-in duplicates left out), each with its full Garmin record."""
    keep = {a['id'] for a in q.activities(start, end)}
    with db.connect() as con:
        rows = con.execute('SELECT id, day, start_time, type, name, duration_s, distance_m, avg_hr, kcal, training_load, json '
                           'FROM activities WHERE day BETWEEN ? AND ? ORDER BY start_time', (start.isoformat(), end.isoformat())).fetchall()
    return [{**dict(r), 'a': json.loads(r['json'] or '{}')} for r in rows if r['id'] in keep]


def everything(end):
    """All activities up to the end of the range, loaded once per page and filtered by the parts below."""
    return activities(date(2000, 1, 1), end)


def within(acts, start, end):
    return [a for a in acts if start.isoformat() <= a['day'] <= end.isoformat()]


# ---- Year so far -----------------------------------------------------------------------------------------------

def _totals(acts):
    return {'sessions': len(acts), 'hours': sum((a['duration_s'] or 0) for a in acts) / 3600,
            'km': sum((a['distance_m'] or 0) for a in acts) / 1000,
            'ascent': sum(a['a'].get('elevationGain') or 0 for a in acts), 'kcal': sum(a['kcal'] or 0 for a in acts)}


def year_so_far(every, end):
    try:
        last_end = end.replace(year=end.year - 1)
    except ValueError:  # 29 February
        last_end = end - timedelta(days=365)
    now, then = within(every, date(end.year, 1, 1), end), within(every, date(end.year - 1, 1, 1), last_end)
    if not now and not then:
        return None
    a, b = _totals(now), _totals(then)
    stats = []
    for key, label, fmt, unit in (('sessions', 'Sessions', '{:,.0f}', ''), ('hours', 'Time', '{:,.0f}', 'h'),
                                  ('km', 'Distance', '{:,.0f}', 'km'), ('ascent', 'Ascent', '{:,.0f}', 'm'),
                                  ('kcal', 'Activity calories', '{:,.0f}', 'kcal')):
        change = None
        if b[key]:
            pct = (a[key] - b[key]) / b[key] * 100
            change = {'text': f'{"+" if pct >= 0 else "−"}{abs(pct):.0f}%', 'dir': 'up' if pct >= 0 else 'down'}
        stats.append({'label': label, 'value': fmt.format(a[key]), 'unit': unit, 'before': fmt.format(b[key]), 'change': change})
    hours_now, hours_then = defaultdict(float), defaultdict(float)
    for x in now:
        hours_now[x['type'] or 'other'] += (x['duration_s'] or 0) / 3600
    for x in then:
        hours_then[x['type'] or 'other'] += (x['duration_s'] or 0) / 3600
    types = sorted(set(hours_now) | set(hours_then), key=lambda t: (-hours_now[t], -hours_then[t]))[:6]
    top = max([hours_now[t] for t in types] + [hours_then[t] for t in types] + [1])
    sports = [{'label': insights.type_label(t), 'icon': type_icon(t), 'now': f'{hours_now[t]:.0f}', 'then': f'{hours_then[t]:.0f}',
               'now_pct': hours_now[t] / top * 100, 'then_pct': hours_then[t] / top * 100} for t in types]
    return {'year': end.year, 'last': end.year - 1, 'through': dmy(end.isoformat()), 'stats': stats, 'sports': sports}


# ---- Consistency -----------------------------------------------------------------------------------------------

def _training_days(start, end):
    days = {a['day'] for a in q.activities(start, end)}
    days |= {w['day'] for w in insights.workouts(start, end)}
    return days


def consistency(end, target=3, weeks=16):
    """Weeks with at least `target` training days: the current run, the longest in two years, and the last few weeks.
    The week in progress only counts once it reaches the target."""
    mon = end - timedelta(days=end.weekday())
    first = mon - timedelta(weeks=104)
    days = _training_days(first, end)
    per_week = defaultdict(int)
    for d in days:
        x = date.fromisoformat(d)
        per_week[(x - timedelta(days=x.weekday())).isoformat()] += 1
    keys = [(first + timedelta(weeks=i)).isoformat() for i in range(105)]
    hit = [per_week[k] >= target for k in keys]
    current = 0
    for i in range(len(keys) - 1, -1, -1):
        if i == len(keys) - 1 and not hit[i]:
            continue  # this week isn't over
        if not hit[i]:
            break
        current += 1
    longest = run = 0
    for h in hit:
        run = run + 1 if h else 0
        longest = max(longest, run)
    recent = [{'week': k, 'n': per_week[k], 'hit': per_week[k] >= target, 'now': k == mon.isoformat(),
               'cells': [per_week[k] > i for i in reversed(range(7))],  # top to bottom, filled from the bottom
               'title': f'Week of {dmy(k)}: {per_week[k]} training day{"s" if per_week[k] != 1 else ""}'} for k in keys[-weeks:]]
    avg = sum(per_week[k] for k in keys[-weeks:-1]) / (weeks - 1)
    return {'current': current, 'longest': longest, 'target': target, 'weeks': recent, 'avg': f'{avg:.1f}',
            'this_week': per_week[mon.isoformat()]}


# ---- Personal bests --------------------------------------------------------------------------------------------

def _best(acts, value, lower=False):
    found = [(value(a), a) for a in acts]
    found = [(v, a) for v, a in found if v]
    if not found:
        return None
    return min(found, key=lambda x: x[0]) if lower else max(found, key=lambda x: x[0])


def _pb(label, acts, in_range, value, show, lower=False):
    best = _best(acts, value, lower)
    if not best:
        return None
    v, a = best
    out = {'label': label, 'value': show(v), 'when': dmy(a['day']), 'id': a['id'], 'name': a['name'], 'new': a['id'] in in_range}
    rb = _best([x for x in acts if x['id'] in in_range], value, lower)
    if rb and rb[1]['id'] != a['id']:
        out['range'] = show(rb[0])
    return out


def personal_bests(every, start, end):
    in_range = {a['id'] for a in within(every, start, end)}
    if len(in_range) == len(every):
        in_range = set()  # the whole history: nothing is "new in this range"
    runs = [a for a in every if is_run(a['type'])]
    rides = [a for a in every if is_ride(a['type'])]
    groups = []
    run_pbs = [_pb(label, runs, in_range, lambda a, k=key: a['a'].get(k), clock, lower=True) for key, label in RUN_SPLITS]
    run_pbs.append(_pb('Longest run', runs, in_range, lambda a: a['distance_m'], lambda v: f'{v / 1000:.1f} km'))
    groups.append(('Running', 'run', [p for p in run_pbs if p], 'Fastest stretch within any run, as Garmin measures it.'))
    ride_pbs = [_pb(f'{label} ride', rides, in_range, lambda a, k=key: a['a'].get(k), clock, lower=True) for key, label in RIDE_SPLITS]
    ride_pbs.append(_pb('Longest ride', rides, in_range, lambda a: a['distance_m'], lambda v: f'{v / 1000:.0f} km'))
    ride_pbs += [_pb(f'Power, {label}', rides, in_range, lambda a, s=s: a['a'].get(f'maxAvgPower_{s}'), lambda v: f'{v:.0f} W')
                 for s, label in POWER if s in POWER_CARDS]
    groups.append(('Cycling', 'bike', [p for p in ride_pbs if p], 'Power bests: the highest average power held for that long.'))
    # Resort skiing counts the lift rides as ascent, so it's left out of the climb.
    climbs = [a for a in every if 'ski' not in (a['type'] or '') and 'snowboard' not in (a['type'] or '')]
    other = [
        _pb('Biggest climb', climbs, in_range, lambda a: a['a'].get('elevationGain'), lambda v: f'{v:,.0f} m'),
        _pb('Longest session', every, in_range, lambda a: a['duration_s'], lambda v: clock(v)),
        _pb('Most calories', every, in_range, lambda a: a['kcal'], lambda v: f'{v:,.0f} kcal'),
        _pb('Highest training load', every, in_range, lambda a: a['training_load'], lambda v: f'{v:.0f}'),
    ]
    groups.append(('Any activity', 'trophy', [p for p in other if p], ''))
    return [{'title': t, 'icon': i, 'bests': items, 'note': n} for t, i, items, n in groups if items]


def ftp(end):
    """Garmin's latest functional threshold power estimate, if a ride carried one."""
    with db.connect() as con:
        row = con.execute("SELECT day, json_extract(json, '$.maxFtp') AS ftp FROM activities WHERE day <= ? AND "
                          "json_extract(json, '$.maxFtp') > 0 ORDER BY day DESC LIMIT 1", (end.isoformat(),)).fetchone()
    return {'value': f'{row["ftp"]:.0f}', 'when': dmy(row['day'])} if row else None


def power_curve(every, start, end):
    """Best average power per duration: all time and in the range, on a log time axis."""
    every = [a for a in every if is_ride(a['type']) and a['a'].get('maxAvgPower_5')]
    if not every:
        return None
    rng = within(every, start, end)
    curve = lambda acts: [(s, max((a['a'].get(f'maxAvgPower_{s}') or 0) for a in acts)) for s, _ in POWER]
    alltime = [(s, v) for s, v in curve(every) if v]
    ranged = [(s, v) for s, v in curve(rng) if v] if rng else []
    series = [{'label': 'All time', 'data': alltime, 'slot': 1, 'style': 'line'}]
    if ranged and len(rng) != len(every):
        series = [{'label': 'All time', 'data': alltime, 'slot': 'muted', 'style': 'line'},
                  {'label': 'This range', 'data': ranged, 'slot': 1, 'style': 'line'}]
    return {'id': 'power', 'title': 'Power curve', 'unit': 'W', 'xkind': 'seconds', 'series': series,
            'note': f'Highest average power held for each duration, from {len(every)} rides with power '
                    '(a power meter or smart trainer).'}


# ---- Training focus --------------------------------------------------------------------------------------------

def _focus(a):
    return FOCUS.get(a['a'].get('trainingEffectLabel'), 'none')


def training_focus(every, start, end):
    acts = [a for a in within(every, start, end) if a['training_load']]
    total = sum(a['training_load'] for a in acts)
    if not total:
        return None
    load, hours, n = defaultdict(float), defaultdict(float), defaultdict(int)
    for a in acts:
        f = _focus(a)
        load[f] += a['training_load']
        hours[f] += (a['duration_s'] or 0) / 3600
        n[f] += 1
    rows = [{'key': k, 'label': label, 'slot': slot, 'what': what, 'pct': load[k] / total * 100, 'load': f'{load[k]:,.0f}',
             'hours': f'{hours[k]:.1f}', 'n': n[k]} for k, label, slot, what in FOCUS_INFO if load[k]]
    aerobic = load['low'] + load['high'] + load['anaerobic']
    if aerobic:
        hi = (load['high'] + load['anaerobic']) / aerobic * 100
        text = (f'{100 - hi:.0f}% of your labelled load was easy aerobic work and {hi:.0f}% hard. ' +
                ('That’s close to the 80/20 split many endurance plans use.' if 10 <= hi <= 30 else
                 'Almost all easy: harder sessions are what build speed and top-end fitness.' if hi < 10 else
                 'That’s more hard work than the 80/20 split many endurance plans use.'))
    else:
        text = 'None of the sessions in this range carry a Garmin training-effect label.'
    weekly = {k: defaultdict(float) for k, *_ in FOCUS_INFO}
    for a in acts:
        weekly[_focus(a)][insights.week_of(a['day'])] += a['training_load']
    weeks = sorted({w for v in weekly.values() for w in v})
    series = [{'label': label, 'data': [(w, round(weekly[k].get(w, 0))) for w in weeks], 'slot': slot, 'style': 'bar'}
              for k, label, slot, _ in FOCUS_INFO if any(weekly[k].values())]
    return {'rows': rows, 'text': text, 'total': f'{total:,.0f}', 'sessions': len(acts),
            'chart': {'id': 'focus', 'title': 'Training load per week, by focus', 'unit': 'load', 'kind': 'bar', 'stacked': True,
                      'zero': True, 'series': series,
                      'note': 'Each session’s Garmin training load, counted under its training-effect label. Garmin’s own load focus '
                              'splits a session’s load more finely, so its numbers can differ.'}}


# ---- Efficiency ------------------------------------------------------------------------------------------------

def _trend(points, n=5):
    """Average of each point and the four before it: a smooth line through scattered sessions."""
    return [(d, sum(v for _, v in points[max(0, i - n + 1):i + 1]) / len(points[max(0, i - n + 1):i + 1]))
            for i, (d, _) in enumerate(points)]


def efficiency(every, start, end):
    acts = within(every, start, end)
    charts = []
    runs = [(a['day'], (a['a'].get('averageSpeed') or 0) * 60 / a['avg_hr']) for a in acts
            if is_run(a['type']) and a['avg_hr'] and (a['distance_m'] or 0) >= 1500 and a['a'].get('averageSpeed')]
    if len(runs) >= 5:
        charts.append({'id': 'run-eff', 'title': 'Running: distance per heartbeat', 'unit': 'm per beat', 'series': [
            {'label': 'Run', 'data': runs, 'slot': 1, 'style': 'points'}, {'label': 'Trend, last 5 runs', 'data': _trend(runs), 'slot': 1}],
            'note': 'Speed divided by heart rate, for runs of 1.5 km or more. Rising means more speed for the same effort: '
                    'aerobic fitness improving. Heat, hills and fatigue pull it down.'})
    rides = [(a['day'], a['a']['avgPower'] / a['avg_hr']) for a in acts
             if is_ride(a['type']) and a['avg_hr'] and a['a'].get('avgPower') and (a['duration_s'] or 0) >= 900]
    if len(rides) >= 5:
        charts.append({'id': 'ride-eff', 'title': 'Cycling: power per heartbeat', 'unit': 'W per bpm', 'series': [
            {'label': 'Ride', 'data': rides, 'slot': 3, 'style': 'points'}, {'label': 'Trend, last 5 rides', 'data': _trend(rides), 'slot': 3}],
            'note': 'Average power divided by average heart rate, for rides of 15 minutes or more with power. Rising means more '
                    'watts for the same effort.'})
    cadence = [(a['day'], a['a']['averageRunningCadenceInStepsPerMinute']) for a in acts
               if is_run(a['type']) and a['a'].get('averageRunningCadenceInStepsPerMinute') and (a['distance_m'] or 0) >= 1500]
    if len(cadence) >= 5:
        charts.append({'id': 'cadence', 'title': 'Running cadence', 'unit': 'steps/min', 'series': [
            {'label': 'Run', 'data': cadence, 'slot': 2, 'style': 'points'}, {'label': 'Trend, last 5 runs', 'data': _trend(cadence), 'slot': 2}],
            'note': 'Steps per minute. Most runners land between 160 and 180; a higher cadence usually means shorter, lighter strides.'})
    return charts
