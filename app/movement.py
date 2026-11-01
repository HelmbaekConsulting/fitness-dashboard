# The Movement page: everyday activity from Garmin's daily summaries (steps against your goal, distance, floors,
# active time, intensity minutes against the weekly goal), with goal rings, streaks, a weekday pattern and records.
from datetime import date, timedelta

from . import svg
from . import queries as q
from .performance import dmy
from .today import WEEKDAYS, short_date

RING_R = (74, 56, 38)  # radii of the three goal rings, outer to inner


def _steps_and_goals(start, end):
    steps = dict(q.daily('steps', start, end))
    goals = dict(q.daily('step_goal', start, end))
    return [(d, v, goals.get(d)) for d, v in sorted(steps.items())]


def _week_start(d):
    return d - timedelta(days=d.weekday())


def rings(end):
    """Goal rings for the latest day with steps: steps and floors that day, intensity minutes that week so far."""
    days = q.daily('steps', end - timedelta(days=14), end)
    if not days:
        return None
    day = date.fromisoformat(days[-1][0])
    one = lambda m: (q.daily(m, day, day) or [(None, None)])[0][1]
    mon = _week_start(day)
    week_int = sum(v for _, v in q.daily('intensity_min', mon, day))
    out = []
    for (label, value, goal, unit, fmt, slot), r in zip((
            ('Steps', one('steps'), one('step_goal') or 10000, '', '{:,.0f}', 's1'),
            ('Floors', one('floors'), one('floor_goal') or 10, '', '{:.0f}', 's3'),
            ('Intensity minutes', week_int, one('intensity_goal') or 150, 'this week', '{:.0f}', 's2')), RING_R):
        if value is None:
            continue
        pct = value / goal * 100 if goal else 0
        out.append({'label': label, 'value': fmt.format(value), 'goal': fmt.format(goal), 'unit': unit, 'slot': slot, 'r': r,
                    'pct': min(pct, 100), 'pct_text': f'{pct:.0f}%', 'done': pct >= 100})
    if not out:
        return None
    done = sum(1 for r in out if r['done'])
    today = day == date.today()
    title = 'Today' if today else short_date(day.isoformat(), True)
    verdict = f'All {len(out)} goals reached' if done == len(out) else f'{done} of {len(out)} goals reached' if done else \
        'No goal reached yet' if today else 'No goal reached'
    return {'title': title, 'verdict': verdict, 'rings': out, 'partial': today}


def _streaks(days, today):
    """Current and longest run of days at or over the step goal. Today doesn't break the current run while it's
    still under the goal: the day isn't over."""
    hit = [(d, v >= g) for d, v, g in days if g]
    longest = run = 0
    best_end = None
    prev = None
    for d, ok in hit:
        cur = date.fromisoformat(d)
        run = run + 1 if ok and prev and (cur - prev).days == 1 and run else (1 if ok else 0)
        prev = cur
        if run > longest:
            longest, best_end = run, d
    current = 0
    seq = hit[:-1] if hit and hit[-1][0] == today and not hit[-1][1] else hit
    expect = None
    for d, ok in reversed(seq):
        cur = date.fromisoformat(d)
        if not ok or (expect and cur != expect):
            break
        current += 1
        expect = cur - timedelta(days=1)
    return current, longest, best_end


def steps_card(start, end):
    days = _steps_and_goals(start, end)
    if not days:
        return None
    vals = [v for _, v, _ in days]
    with_goal = [(d, v, g) for d, v, g in days if g]
    hits = sum(1 for _, v, g in with_goal if v >= g)
    current, longest, _ = _streaks(_steps_and_goals(start - timedelta(days=365), end), date.today().isoformat())
    best = max(days, key=lambda x: x[1])
    return {'avg': f'{sum(vals) / len(vals):,.0f}', 'hits': hits, 'of': len(with_goal), 'pct': hits / len(with_goal) * 100 if with_goal else 0,
            'goal': f'{with_goal[-1][2]:,.0f}' if with_goal else None, 'streak': current, 'longest': longest,
            'best': f'{best[1]:,.0f}', 'best_day': short_date(best[0], True)}


def steps_chart(start, end):
    """Daily bars, green on goal days, with the goal as a line; weekly averages for ranges longer than four months."""
    days = _steps_and_goals(start, end)
    if not days:
        return []
    if (end - start).days > 120:
        return [{'label': 'Steps, weekly average', 'data': q.weekly([(d, v) for d, v, _ in days]), 'slot': 1, 'style': 'bar'},
                {'label': 'Goal', 'data': q.weekly([(d, g) for d, _, g in days if g]), 'slot': 'muted', 'style': 'step'}]
    return [{'label': 'Goal reached', 'data': [(d, v if g and v >= g else 0) for d, v, g in days], 'slot': 3, 'style': 'bar'},
            {'label': 'Under goal', 'data': [(d, 0 if g and v >= g else v) for d, v, g in days], 'slot': 1, 'style': 'bar'},
            {'label': 'Goal', 'data': [(d, g) for d, _, g in days if g], 'slot': 'muted', 'style': 'step'}]


def intensity(start, end):
    """Weekly intensity minutes (vigorous count double) against Garmin's weekly goal."""
    weeks = q.weekly(q.daily('intensity_min', start, end), 'sum')
    goals = dict(q.weekly(q.daily('intensity_goal', start, end)))
    if not weeks:
        return None
    this_week = _week_start(end).isoformat()
    full = [(w, v) for w, v in weeks if w != this_week and goals.get(w)]
    met = sum(1 for w, v in full if v >= goals[w])
    return {'series': [{'label': 'Intensity minutes', 'data': weeks, 'slot': 2, 'style': 'bar'},
                       {'label': 'Weekly goal', 'data': sorted(goals.items()), 'slot': 'muted', 'style': 'step'}],
            'met': met, 'of': len(full), 'avg': f'{sum(v for _, v in full) / len(full):.0f}' if full else None,
            'goal': f'{list(goals.values())[-1]:.0f}' if goals else None}


def weekday_pattern(start, end):
    """Average steps per weekday, with the most and least active days marked."""
    sums, counts = [0.0] * 7, [0] * 7
    for d, v in q.daily('steps', start, end):
        wd = date.fromisoformat(d).weekday()
        sums[wd] += v
        counts[wd] += 1
    avgs = [s / c if c else None for s, c in zip(sums, counts)]
    known = [a for a in avgs if a is not None]
    if len(known) < 7 or min(counts) < 2:
        return None
    top = max(known)
    hi, lo = avgs.index(max(known)), avgs.index(min(known))
    rows = [{'day': WEEKDAYS[i], 'value': f'{a:,.0f}', 'pct': a / top * 100, 'tag': 'most' if i == hi else 'least' if i == lo else ''}
            for i, a in enumerate(avgs)]
    weekend = (avgs[5] + avgs[6]) / 2
    weekday = sum(avgs[:5]) / 5
    diff = (weekend - weekday) / weekday * 100
    text = f'Weekends are {abs(diff):.0f}% {"more" if diff > 0 else "less"} active than weekdays.' if abs(diff) >= 8 else \
        'Weekdays and weekends are about as active.'
    return {'rows': rows, 'text': text}


def _spark_weekly(metric, start, end, how='mean'):
    pts = q.weekly(q.daily(metric, start, end), how)
    if len(pts) < 2:
        return None
    vals = [v for _, v in pts]
    top = max(vals) * 1.08 or 1
    bars = svg.spark_bars(vals, top, gap=max(2, 8 - len(vals) // 8))
    return {'old': ''.join(bars[:-1]), 'now': bars[-1]}


def kpis(start, end):
    """Daily averages over the range, compared with the same number of days before it."""
    span = (end - start).days + 1
    before = (start - timedelta(days=span), start - timedelta(days=1))
    out = []
    for metric, label, icon, unit, fmt, how in (
            ('distance_km', 'Distance', 'walk', 'km a day', '{:.1f}', 'mean'),
            ('floors', 'Floors climbed', 'up', 'a day', '{:.0f}', 'mean'),
            ('active_min', 'Active time', 'flame', 'min a day', '{:.0f}', 'mean'),
            ('total_kcal', 'Calories burned', 'pulse', 'kcal a day', '{:,.0f}', 'mean')):
        now, prev = q.avg(q.daily(metric, start, end)), q.avg(q.daily(metric, *before))
        delta = ''
        if now is not None and prev:
            pct = (now - prev) / prev * 100
            delta = 'Same as the period before' if abs(pct) < 1 else f'{"+" if pct > 0 else "−"}{abs(pct):.0f}% vs the {span} days before'
        out.append({'label': label, 'icon': icon, 'value': None if now is None else fmt.format(now), 'unit': unit, 'delta': delta,
                    'bars': _spark_weekly(metric, start, end, how), 'foot': ('Weekly average', '')})
    return out


def records(end):
    """All-time bests up to the end of the range."""
    first = date(2000, 1, 1)
    steps = q.daily('steps', first, end)
    if not steps:
        return []
    out = []
    d, v = max(steps, key=lambda x: x[1])
    out.append(('Most steps in a day', f'{v:,.0f}', dmy(d)))
    weeks = [(w, v) for w, v in q.weekly(steps) if w != _week_start(end).isoformat()]
    if weeks:
        w, v = max(weeks, key=lambda x: x[1])
        out.append(('Best week', f'{v:,.0f} a day', f'week of {dmy(w)}'))
    _, longest, last = _streaks(_steps_and_goals(first, end), date.today().isoformat())
    if longest:
        out.append(('Longest goal streak', f'{longest} day{"s" if longest != 1 else ""}', f'ending {dmy(last)}'))
    for metric, label, fmt in (('floors', 'Most floors in a day', '{:.0f}'), ('distance_km', 'Most distance in a day', '{:.1f} km')):
        pts = q.daily(metric, first, end)
        if pts:
            d, v = max(pts, key=lambda x: x[1])
            out.append((label, fmt.format(v), dmy(d)))
    return [{'label': a, 'value': b, 'when': c} for a, b, c in out]
