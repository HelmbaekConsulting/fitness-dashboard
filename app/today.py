# The Today page: readiness ring, the body card with what the weight change was made of, recovery tiles with
# sparklines, the latest Garmin and Jefit sessions, things worth knowing and the energy balance.
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import db, insights, muscles, svg
from . import queries as q

MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
STATUS = {'good': ('Normal', 'check'), 'warning': ('Watch', 'alert'), 'serious': ('Off', 'alert')}
VERDICT_WORD = {'good': 'Good', 'warning': 'Moderate', 'serious': 'Recover'}
CHECK_WORDS = {'HRV': 'HRV', 'Resting HR': 'resting heart rate', 'Sleep': 'sleep', 'Load': 'load'}
GROUPS = {'chest': 'chest', 'front_delts': 'shoulders', 'side_delts': 'shoulders', 'rear_delts': 'shoulders', 'traps': 'back',
          'upper_back': 'back', 'lats': 'back', 'lower_back': 'back', 'abs': 'core', 'obliques': 'core', 'biceps': 'arms',
          'triceps': 'arms', 'forearms': 'arms', 'glutes': 'legs', 'quads': 'legs', 'hamstrings': 'legs', 'calves': 'legs'}
TYPE_ICONS = [('golf', 'flag'), ('cycl', 'bike'), ('bik', 'bike'), ('run', 'run'), ('walk', 'walk'), ('hik', 'walk'),
              ('swim', 'swim'), ('strength', 'dumbbell')]


def short_date(iso, weekday=False):
    d = date.fromisoformat(iso[:10])
    s = f'{d.day} {MONTHS[d.month - 1]}'
    return f'{WEEKDAYS[d.weekday()]} {s}' if weekday else s


def long_date(d):
    return d.strftime('%A') + f' {d.day} ' + d.strftime('%B')


def _join(words):
    return words[0] if len(words) == 1 else ', '.join(words[:-1]) + ' and ' + words[-1]


def _cap(s):
    return s[:1].upper() + s[1:]


def _minus(s):
    return s.replace('-', '−')


def num(v):
    return f'{v:.1f}' if abs(v) < 10 else f'{v:.0f}'


def duration(seconds):
    m = round((seconds or 0) / 60)
    return f'{m} min' if m < 60 else f'{m // 60}:{m % 60:02d} h'


def delta_text(now, before, unit, fmt='{:.1f}'):
    if now is None or before is None:
        return ''
    shown = fmt.format(abs(now - before))
    if not any(ch in '123456789' for ch in shown):
        return 'Same as the week before'
    return f'{"+" if now > before else "−"}{shown}{" " + unit if unit else ""} vs the week before'


# ---- Readiness -------------------------------------------------------------------------------------------------

def readiness(end):
    verdict, checks = insights.readiness(end)
    if not verdict:
        return None
    items = [{**c, 'label': STATUS[c['status']][0], 'icon': STATUS[c['status']][1], 'path': d}
             for c, d in zip(checks, svg.ring(len(checks)))]
    off = [c for c in checks if c['status'] != 'good']
    ok = [CHECK_WORDS[c['name']] for c in checks if c['status'] == 'good']
    if not off:
        text = f'{_cap(_join(ok))} {"is" if len(ok) == 1 else "are all"} in your normal range.'
    else:
        text = '. '.join(c['off'] for c in off) + '.'
        if ok:
            text += f' {_cap(_join(ok))} {"is" if len(ok) == 1 else "are"} in your normal range.'
    return {'status': verdict[0], 'verdict': verdict[1], 'word': VERDICT_WORD[verdict[0]], 'text': text, 'checks': items,
            'count': f'{len(checks) - len(off)} of {len(checks)} normal'}


# ---- Body ------------------------------------------------------------------------------------------------------

def _latest_change(metric, start, end):
    pts = q.daily(metric, start, end)
    if not pts:
        return None, None
    return pts[-1][1], (pts[-1][1] - pts[0][1] if len(pts) > 1 else None)


def composition(start, end):
    """Weight change between the first and latest Body Scan in the range, split into fat, muscle and the rest."""
    with db.connect() as con:
        rows = con.execute("SELECT day, metric, value FROM metrics WHERE metric IN ('weight_kg', 'fat_mass_kg', 'muscle_kg') "
                           'AND day BETWEEN ? AND ?', (start.isoformat(), end.isoformat())).fetchall()
    days = defaultdict(dict)
    for r in rows:
        days[r['day']][r['metric']] = r['value']
    full = sorted(d for d, m in days.items() if len(m) == 3)
    if len(full) < 2:
        return None
    a, b = days[full[0]], days[full[-1]]
    dw = b['weight_kg'] - a['weight_kg']
    df, dm = b['fat_mass_kg'] - a['fat_mass_kg'], b['muscle_kg'] - a['muscle_kg']
    parts = [{'label': 'Fat', 'kg': df, 'slot': 's2'}, {'label': 'Muscle', 'kg': dm, 'slot': 's1'},
             {'label': 'Water, bone, the rest', 'kg': dw - df - dm, 'slot': 'other'}]
    lost = dw < 0
    same = abs(dw) >= 0.3 and all(abs(p['kg']) < 0.05 or (p['kg'] < 0) == lost for p in parts)
    for p in parts:
        p['pct'] = round(p['kg'] / dw * 100) if same else None
        p['shown'] = f'{abs(p["kg"]):.1f} kg' if same else _minus(f'{p["kg"]:+.1f} kg')
        p['flex'] = f'{max(abs(p["kg"]), 0.01):.2f}'
    title = (f'What the {abs(dw):.1f} kg you {"lost" if lost else "gained"} was made of' if same
             else _minus(f'How your body changed: {dw:+.1f} kg'))
    return {'title': title, 'parts': parts, 'bar': same, 'from': short_date(full[0]), 'to': short_date(full[-1]),
            'dw': dw, 'df': df, 'dm': dm, 'weight': b['weight_kg']}


def body(start, end):
    tw = insights.trend_weight(start, end)
    fat, dfat = _latest_change('fat_pct', start, end)
    mus, dmus = _latest_change('muscle_kg', start, end)
    stats = []
    if fat is not None:
        stats.append({'label': 'Body fat', 'value': f'{fat:.1f}', 'unit': '%', 'delta': dfat, 'better': 'down', 'unit_d': 'points'})
    if mus is not None:
        stats.append({'label': 'Muscle mass', 'value': f'{mus:.1f}', 'unit': 'kg', 'delta': dmus, 'better': 'up', 'unit_d': 'kg'})
    for s in stats:
        d = s.pop('delta')
        s['change'] = None if d is None or abs(d) < 0.05 else f'{abs(d):.1f} {s["unit_d"]}'
        s['dir'] = None if s['change'] is None else 'down' if d < 0 else 'up'
        s['tone'] = '' if s['dir'] is None else 'good' if s['dir'] == s['better'] else 'bad'
    weight = change = None
    if tw:
        weight = f'{tw[-1][1]:.1f}'
        d = tw[-1][1] - tw[0][1]
        change = {'dir': 'down' if d < 0 else 'up', 'text': f'{abs(d):.1f} kg since {short_date(tw[0][0])}'} if abs(d) >= 0.05 else None
    trips = insights.trips(start, end)
    for t in trips:
        a, b = date.fromisoformat(t['from']), date.fromisoformat(t['to'])
        t['span'] = f'{a.day}–{short_date(t["to"])}' if a.month == b.month else f'{short_date(t["from"])} – {short_date(t["to"])}'
    return {'weight': weight, 'change': change, 'stats': stats, 'trend': tw, 'weighins': q.daily('weight_kg', start, end),
            'trips': trips, 'composition': composition(start, end)}


# ---- Recovery tiles --------------------------------------------------------------------------------------------

def _weekly_bars(metric, end, target=None, weeks=8):
    first = end - timedelta(days=end.weekday()) - timedelta(weeks=weeks - 1)
    keys = [(first + timedelta(weeks=i)).isoformat() for i in range(weeks)]
    vals = dict(q.weekly(q.daily(metric, first, end)))
    values = [vals.get(k) for k in keys]
    known = [v for v in values if v is not None]
    if not known:
        return None
    top = max(known + [target or 0]) * 1.08
    bars = svg.spark_bars(values, top)
    return {'old': ''.join(bars[:-1]), 'now': bars[-1], 'target': svg.level(target, top) if target else None}


def tiles(end, ready):
    week, prev = (end - timedelta(days=6), end), (end - timedelta(days=13), end - timedelta(days=7))
    s30 = end - timedelta(days=29)
    x = lambda d: (date.fromisoformat(d) - s30).days / 29
    avg = lambda m, r: q.avg(q.daily(m, *r))
    out = []

    now, before = avg('sleep_h', week), avg('sleep_h', prev)
    out.append({'label': 'Sleep', 'icon': 'moon', 'value': None if now is None else f'{now:.1f}', 'unit': 'h',
                'delta': delta_text(now, before, 'h'), 'bars': _weekly_bars('sleep_h', end, 7),
                'status': None if now is None else ('good', '7 h or more', 'check') if now >= 7 else ('warning', 'Under 7 h', 'alert'),
                'foot': ('8 weeks', 'dashed line: 7 h')})

    line, lo, hi = insights.hrv_band(s30, end)
    now, before = avg('hrv_sleep', week), avg('hrv_sleep', prev)
    t = {'label': 'Overnight HRV', 'icon': 'pulse', 'value': None if now is None else f'{now:.0f}', 'unit': 'ms',
         'delta': delta_text(now, before, 'ms', '{:.0f}'), 'status': None, 'foot': ('30 days, 7-day average', '')}
    if len(line) > 1:
        ys = [v for _, v in line + lo + hi]
        t['line'], sy = svg.spark_line([(x(d), v) for d, v in line], min(ys), max(ys))
        if len(lo) > 1:
            t['band'] = svg.spark_band([(x(d), v) for d, v in hi], [(x(d), v) for d, v in lo], sy)
            t['foot'] = ('30 days, 7-day average', 'band: your range')
    if line and lo:
        v, low, high = line[-1][1], lo[-1][1], hi[-1][1]
        t['status'] = ('good', 'Normal', 'check') if low <= v <= high else ('warning', 'Above range', 'alert') if v > high \
            else ('serious', 'Below range', 'alert')
    out.append(t)

    pts = [(d, v) for d, v in q.rolling(q.daily('resting_hr', s30 - timedelta(days=7), end)) if d >= s30.isoformat()]
    now, before = avg('resting_hr', week), avg('resting_hr', prev)
    check = next((c for c in (ready or {}).get('checks', []) if c['name'] == 'Resting HR'), None)
    t = {'label': 'Resting heart rate', 'icon': 'heart', 'value': None if now is None else f'{now:.0f}', 'unit': 'bpm',
         'delta': delta_text(now, before, 'bpm', '{:.0f}'), 'status': (check['status'], check['label'], check['icon']) if check else None,
         'foot': ('30 days, 7-day average', '')}
    if len(pts) > 1:
        t['line'] = svg.spark_line([(x(d), v) for d, v in pts])[0]
        t['foot'] = ('30 days, 7-day average', f'{min(v for _, v in pts):.0f}–{max(v for _, v in pts):.0f} bpm')
    out.append(t)

    now, before = avg('steps', week), avg('steps', prev)
    out.append({'label': 'Steps', 'icon': 'steps', 'value': None if now is None else f'{now:,.0f}', 'unit': 'a day',
                'delta': delta_text(now, before, '', '{:,.0f}'), 'status': None, 'bars': _weekly_bars('steps', end),
                'foot': ('8 weeks', 'weekly average')})
    return out


# ---- Training --------------------------------------------------------------------------------------------------

def type_icon(kind, name=''):
    s = f'{kind or ""} {name or ""}'.lower()
    return next((icon for key, icon in TYPE_ICONS if key in s), 'pulse')


def session_title(exercises):
    """Main areas of a Jefit session from its sets, such as "Chest and shoulders"."""
    credit = defaultdict(float)
    for e in exercises:
        for m, c in muscles.weights(e['exercise']).items():
            credit[GROUPS[m]] += c * e['n']
    total = sum(credit.values())
    top = [g for g, c in sorted(credit.items(), key=lambda kv: -kv[1]) if total and c / total >= 0.25][:2]
    return _cap(_join(top)) if top else 'Strength'


def training(end, ws):
    """The last 30 days of sessions, newest first: Garmin activities, and Jefit sessions in place of the Garmin
    recording they overlap (so a session shows once, with Jefit's lifts and Garmin's heart rate)."""
    s30 = end - timedelta(days=29)
    matched = {w['garmin']['id'] for w in ws if w['garmin']}
    items = []
    for a in q.activities(s30, end):
        if a['id'] in matched:
            continue
        metrics = [('Time', duration(a['duration_s']))]
        if a['distance_m']:
            metrics.append(('Distance', f'{a["distance_m"] / 1000:.1f} km'))
        if a['kcal']:
            metrics.append(('kcal', f'{a["kcal"]:,.0f}'))
        if a['avg_hr']:
            metrics.append(('Avg HR', f'{a["avg_hr"]:.0f}'))
        if a['training_load']:
            metrics.append(('Load', f'{a["training_load"]:.0f}'))
        name = a['name'] or insights.type_label(a['type'])
        source = 'MyFitnessPal' if name.endswith('MyFitnessPal') else 'manual entry' if a['manual'] else 'Garmin'
        items.append({'when': a['start_time'] or a['day'], 'day': a['day'], 'seconds': a['duration_s'] or 0,
                      'title': name.rsplit(' - MyFitnessPal', 1)[0], 'icon': type_icon(a['type'], name),
                      'sub': f'{short_date(a["day"], True)} · {source}', 'metrics': metrics[:4]})
    for w in ws:
        if w['day'] < s30.isoformat():
            continue
        metrics = [('Time', duration(w['duration_s'])), ('Volume', f'{(w["volume_kg"] or 0) / 1000:.1f} t')]
        if w['kcal']:
            metrics.append(('kcal' if w['kcal_source'] == 'garmin' else 'kcal, est.', f'{w["kcal"]:.0f}'))
        metrics.append(('Avg HR', f'{w["avg_hr"]:.0f}') if w['avg_hr'] else ('Lifts', str(len(w['exercise_list']))))
        items.append({'when': datetime.fromtimestamp(w['start_ts']).strftime('%Y-%m-%d %H:%M:%S') if w['start_ts'] else w['day'],
                      'day': w['day'], 'seconds': w['duration_s'] or 0, 'title': session_title(w['exercise_list']),
                      'icon': 'dumbbell', 'metrics': metrics[:4],
                      'sub': f'{short_date(w["day"], True)} · Jefit' + (' and Garmin' if w['garmin'] else ', no watch recording')})
    items.sort(key=lambda i: i['when'], reverse=True)
    week = [i for i in items if i['day'] >= (end - timedelta(days=6)).isoformat()]
    load = q.training_load(s30, end)
    out = {'sessions': items[:4], 'week_time': duration(sum(i['seconds'] for i in week)), 'week_n': len(week), 'load': load}
    if load:
        fit, fat, fit0 = load[-1][1], load[-1][2], load[0][1]
        out['fitness'], out['fatigue'], out['form'] = f'{fit:.0f}', f'{fat:.0f}', _minus(f'{fit - fat:+.0f}')
        out['fitness_note'] = 'Same as a month ago' if round(fit) == round(fit0) else \
            f'{"Down" if fit < fit0 else "Up"} from {fit0:.0f} a month ago'
        form = fit - fat
        out['form_note'] = 'Rested' if form > 5 else 'Balanced' if form >= -5 else 'Carrying fatigue'
    return out


# ---- Worth knowing and energy ----------------------------------------------------------------------------------

def worth_knowing(end, ready, comp, ws):
    week, prev = (end - timedelta(days=6), end), (end - timedelta(days=13), end - timedelta(days=7))
    out = []
    a, b = q.avg(q.daily('sleep_h', *prev)), q.avg(q.daily('sleep_h', *week))
    if a is not None and b is not None and a < 7 and b < 7:
        only = ready and [c['name'] for c in ready['checks'] if c['status'] != 'good'] == ['Sleep']
        out.append(('moon', 'Sleep is running short', f'{a:.1f} and {b:.1f} h a night the last two weeks.'
                    + (' It’s the only readiness check that’s off.' if only else '')))
    recs = insights.records(end - timedelta(days=13), end, limit=3)
    if recs:
        r = recs[0]
        more = f' and {len(recs) - 1} more' if len(recs) > 1 else ''
        out.append(('trend', 'New personal record', f'{r["exercise"]}: {r["e1rm"]:.1f} kg estimated 1RM on {short_date(r["day"])}, '
                    f'up from {r["previous"]:.1f}{more}.'))
    vol, _ = insights.muscle_volume(end - timedelta(days=89), end)
    bal = insights.balance(vol)
    if bal['upper'] >= 3 and bal['lower'] < bal['upper'] / 3:
        gap = bal['upper'] - bal['lower']
        out.append(('figure', 'Legs are falling behind', f'{num(bal["lower"])} sets a week for legs against {num(bal["upper"])} '
                    'for the upper body over 90 days.' + (' One more leg session a week would close most of the gap.' if gap <= 12 else '')))
    if comp and comp['dw'] <= -1:
        kg = comp['weight']
        if comp['dm'] < 0 and -comp['dm'] >= 0.25 * -comp['dw']:
            protein = q.avg(q.daily('protein_g', end - timedelta(days=13), end))
            text = f'{-comp["dm"]:.1f} of the {-comp["dw"]:.1f} kg was muscle. ' + (
                f'Protein is {protein:.0f} g a day, {protein / kg:.1f} g per kg; 1.6 g per kg is about {1.6 * kg:.0f} g.' if protein
                else f'Protein isn’t logged yet; at {kg:.0f} kg, 1.6 g per kg is about {1.6 * kg:.0f} g a day.')
            out.append(('utensils', 'Protect the muscle', text))
        elif comp['dm'] >= 0:
            gained = f'{comp["dm"]:+.1f}'
            out.append(('trend', 'Muscle held while you lost weight',
                        f'{-comp["dw"]:.1f} kg down and muscle mass {gained} kg since {comp["from"]}.'))
    last = ws[:6]
    no_watch = sum(1 for w in last if not w['garmin'])
    if len(last) >= 3 and no_watch >= 2:
        out.append(('watch', 'Lift with the watch on', f'{no_watch} of your last {len(last)} strength sessions have no watch '
                    'recording, so their calories are estimates and they add no training load.'))
    return [{'icon': i, 'title': t, 'text': x} for i, t, x in out]


def energy(end):
    eaten = q.avg(q.kcal_in(end - timedelta(days=6), end))
    burned = q.avg(q.daily('total_kcal', end - timedelta(days=27), end))
    tdee = insights.expenditure(end - timedelta(days=13), end)
    measured = tdee[-1][1] if tdee else None
    logged = len(q.kcal_in(end - timedelta(days=27), end))
    rows = [(label, v, slot) for label, v, slot in (('Eaten, last 7 days', eaten, 's1'), ('Measured maintenance, 28 days', measured, 's3'),
                                                    ('Burned, Garmin estimate, 28 days', burned, 's2')) if v]
    if not rows:
        return None
    top = max(v for _, v, _ in rows) * 1.06
    ref, ref_name = (measured, 'your measured maintenance') if measured else (burned, 'Garmin’s estimate')
    text = ''
    if eaten and ref:
        diff = eaten - ref
        text = (f'About even with {ref_name}.' if abs(diff) < 50 else
                f'About {abs(round(diff, -1)):,.0f} kcal a day {"under" if diff < 0 else "over"} {ref_name}.')
    elif not eaten:
        text = 'No food logged in the last 7 days.'
    if not measured:
        text += f' A measured maintenance needs 18 logged days out of 28; you have {logged}.'
    return {'rows': [{'label': label, 'value': f'{v:,.0f}', 'pct': f'{v / top * 100:.1f}', 'slot': slot} for label, v, slot in rows],
            'text': text.strip()}


def build(start, end):
    ready = readiness(end)
    b = body(start, end)
    ws = insights.workouts(end - timedelta(days=89), end)
    return {'ready': ready, 'body': b, 'kpis': tiles(end, ready), 'training': training(end, ws),
            'know': worth_knowing(end, ready, b['composition'], ws), 'energy': energy(end), 'today_long': long_date(end)}
