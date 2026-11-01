# One activity in full, from the Garmin record stored for it: headline numbers, heart-rate zones, training effect,
# the details Garmin fills for that sport, fastest splits and power bests against your all-time bests, strength sets
# (Garmin's or the matching Jefit session's), the run/walk split, and how it compares with your usual session.
import json
import re
from datetime import date, datetime, timedelta

from . import db, insights
from .performance import POWER, RIDE_SPLITS, RUN_SPLITS, clock, dmy, is_ride, is_run
from .today import MONTHS, type_icon

ZONES = [(1, 'Warm-up'), (2, 'Easy'), (3, 'Aerobic'), (4, 'Threshold'), (5, 'Maximum')]
TE_WORDS = [(1, 'No effect'), (2, 'Minor'), (3, 'Maintaining'), (4, 'Improving'), (5, 'Highly improving'), (6, 'Overreaching')]


def _get(activity_id):
    with db.connect() as con:
        row = con.execute('SELECT * FROM activities WHERE id=?', (activity_id,)).fetchone()
    return dict(row) if row else None


def _neighbours(start_time):
    with db.connect() as con:
        prev = con.execute('SELECT id, name, day FROM activities WHERE start_time < ? ORDER BY start_time DESC LIMIT 1', (start_time,)).fetchone()
        nxt = con.execute('SELECT id, name, day FROM activities WHERE start_time > ? ORDER BY start_time LIMIT 1', (start_time,)).fetchone()
    link = lambda r: {'href': f'/activity/{r["id"]}', 'name': r['name'], 'when': dmy(r['day'])} if r else None
    return link(prev), link(nxt)


def message(code):
    """Garmin's training-effect message code in words: IMPROVING_AEROBIC_BASE_8 → Improving aerobic base."""
    words = re.sub(r'_\d+$', '', code or '').replace('_', ' ').lower().replace('vo2max', 'VO2 max')
    return words[:1].upper() + words[1:]


def _te(value, code):
    """Garmin's own message for the effect when it has one (it doesn't always follow the plain scale), else the scale."""
    if value is None:
        return None
    word = message(code) if code else next(w for top, w in TE_WORDS if value < top) if value < 5 else 'Overreaching'
    # Five segments of one point each, filled as far as the value reaches.
    return {'value': f'{value:.1f}', 'segs': [min(max(value - i, 0), 1) * 100 for i in range(5)], 'word': word}


def _pace(speed):
    s = 1000 / speed
    return f'{int(s // 60)}:{int(s % 60):02d}'


def headline(r, a):
    t = r['type'] or ''
    out = [('Time', clock(r['duration_s'] or 0), '')]
    if r['distance_m']:
        out.append(('Distance', f'{r["distance_m"] / 1000:.2f}', 'km'))
    sp = a.get('averageSpeed') or 0
    if sp > 0 and r['distance_m']:
        if t in insights.PACE_TYPES:
            out.append(('Pace', _pace(sp), '/km'))
        elif is_ride(t) or 'ski' in t:
            out.append(('Speed', f'{sp * 3.6:.1f}', 'km/h'))
    if r['avg_hr']:
        out.append(('Avg heart rate', f'{r["avg_hr"]:.0f}', 'bpm'))
    if r['kcal']:
        out.append(('Calories', f'{r["kcal"]:,.0f}', 'kcal'))
    if r['training_load']:
        out.append(('Training load', f'{r["training_load"]:.0f}', ''))
    if a.get('elevationGain'):
        out.append(('Ascent', f'{a["elevationGain"]:,.0f}', 'm'))
    return [{'label': l, 'value': v, 'unit': u} for l, v, u in out]


def zones(a, max_hr, duration):
    secs = [a.get(f'hrTimeInZone_{z}') or 0 for z, _ in ZONES]
    total = sum(secs)
    if not total:
        return None
    top = max(secs)
    rows = [{'z': z, 'name': name, 'min': round(s / 60), 'pct': s / total * 100, 'bar': s / top * 100} for (z, name), s in zip(ZONES, secs)]
    main = max(rows, key=lambda x: x['pct'])
    text = f'Most time in zone {main["z"]} ({main["name"].lower()}).'
    below = round(((duration or 0) - total) / 60)
    if below >= 5:
        text += f' Another {below} min were below zone 1.'
    return {'rows': rows, 'max_hr': f'{max_hr:.0f}' if max_hr else None, 'text': text}


def details(r, a):
    """The extra numbers Garmin records for this sport, in groups; empty groups are left out."""
    t = r['type'] or ''
    n = lambda k: a.get(k) if isinstance(a.get(k), (int, float)) and a.get(k) else None
    groups = []
    rows = []
    if n('movingDuration') and abs((a['movingDuration'] or 0) - (r['duration_s'] or 0)) > 30:
        rows.append(('Moving time', clock(a['movingDuration'])))
    if n('maxSpeed') and r['distance_m']:
        rows.append(('Fastest pace', _pace(a['maxSpeed']) + ' /km') if t in insights.PACE_TYPES else ('Top speed', f'{a["maxSpeed"] * 3.6:.1f} km/h'))
    if r['max_hr']:
        rows.append(('Max heart rate', f'{r["max_hr"]:.0f} bpm'))
    if n('lapCount') and a['lapCount'] > 1:
        rows.append(('Laps', f'{a["lapCount"]}'))
    if n('steps'):
        rows.append(('Steps', f'{a["steps"]:,}'))
    if n('waterEstimated'):
        rows.append(('Sweat loss, estimated', f'{a["waterEstimated"] / 1000:.1f} l'))
    if a.get('minTemperature') is not None and n('maxTemperature'):
        rows.append(('Watch temperature', f'{a.get("minTemperature") or 0:.0f}–{a["maxTemperature"]:.0f} °C'))
    groups.append(('Overview', rows))
    rows = []
    if n('elevationGain') or n('elevationLoss'):
        rows.append(('Ascent / descent', f'{a.get("elevationGain") or 0:,.0f} / {a.get("elevationLoss") or 0:,.0f} m'))
    if a.get('minElevation') is not None and a.get('maxElevation') is not None and (n('elevationGain') or n('elevationLoss')):
        rows.append(('Lowest / highest', f'{a["minElevation"]:,.0f} / {a["maxElevation"]:,.0f} m'))
    groups.append(('Elevation', rows))
    rows = []
    if n('averageRunningCadenceInStepsPerMinute'):
        rows.append(('Cadence', f'{a["averageRunningCadenceInStepsPerMinute"]:.0f} spm' +
                     (f', max {a["maxRunningCadenceInStepsPerMinute"]:.0f}' if n('maxRunningCadenceInStepsPerMinute') else '')))
    if n('avgStrideLength'):
        rows.append(('Stride length', f'{a["avgStrideLength"] / 100:.2f} m'))
    if n('avgGroundContactTime'):
        rows.append(('Ground contact time', f'{a["avgGroundContactTime"]:.0f} ms'))
    if n('avgGroundContactBalance'):
        rows.append(('Contact balance, left', f'{a["avgGroundContactBalance"]:.1f}%'))
    if n('avgVerticalOscillation'):
        rows.append(('Vertical oscillation', f'{a["avgVerticalOscillation"]:.1f} cm'))
    if n('avgVerticalRatio'):
        rows.append(('Vertical ratio', f'{a["avgVerticalRatio"]:.1f}%'))
    if n('averageBikingCadenceInRevPerMinute'):
        rows.append(('Cadence', f'{a["averageBikingCadenceInRevPerMinute"]:.0f} rpm' +
                     (f', max {a["maxBikingCadenceInRevPerMinute"]:.0f}' if n('maxBikingCadenceInRevPerMinute') else '')))
    if n('averageSwimCadenceInStrokesPerMinute'):
        rows.append(('Stroke rate', f'{a["averageSwimCadenceInStrokesPerMinute"]:.0f} per min'))
    if n('averageSwolf'):
        rows.append(('SWOLF', f'{a["averageSwolf"]:.0f}'))
    if n('poolLength'):
        rows.append(('Pool length', f'{a["poolLength"] / 100:.0f} m'))
    groups.append(('Technique', rows))
    rows = []
    if n('avgPower'):
        rows.append(('Average power', f'{a["avgPower"]:.0f} W'))
    if n('normPower'):
        rows.append(('Normalised power', f'{a["normPower"]:.0f} W'))
    if n('maxPower'):
        rows.append(('Max power', f'{a["maxPower"]:.0f} W'))
    if n('intensityFactor'):
        rows.append(('Intensity factor', f'{a["intensityFactor"]:.2f}'))
    if n('trainingStressScore'):
        rows.append(('Training stress score', f'{a["trainingStressScore"]:.0f}'))
    if n('maxFtp'):
        rows.append(('FTP, Garmin’s estimate', f'{a["maxFtp"]:.0f} W'))
    if n('avgLeftBalance'):
        rows.append(('Left/right balance', f'{a["avgLeftBalance"]:.0f} / {100 - a["avgLeftBalance"]:.0f}'))
    groups.append(('Power', rows))
    rows = []
    if n('avgRespirationRate'):
        rows.append(('Breathing rate', f'{a["avgRespirationRate"]:.0f} per min' +
                     (f' ({a["minRespirationRate"]:.0f}–{a["maxRespirationRate"]:.0f})' if n('minRespirationRate') and n('maxRespirationRate') else '')))
    if n('lactateThresholdBpm'):
        rows.append(('Lactate threshold HR', f'{a["lactateThresholdBpm"]:.0f} bpm'))
    if n('avgStress'):
        rows.append(('Stress', f'{a.get("startStress") or 0:.0f} → {a.get("endStress") or 0:.0f}, average {a["avgStress"]:.0f}'))
    groups.append(('Body', rows))
    return [{'title': title, 'rows': [{'label': l, 'value': v} for l, v in rows]} for title, rows in groups if rows]


def _all_time(field, family, before_or_on, lower):
    """Best value of one Garmin field among activities of the same family (runs or rides) up to a date."""
    with db.connect() as con:
        rows = con.execute(f"SELECT type, json_extract(json, '$.{field}') AS v FROM activities WHERE day <= ? AND "
                           f"json_extract(json, '$.{field}') > 0", (before_or_on,)).fetchall()
    vals = [r['v'] for r in rows if family(r['type'])]
    return (min(vals) if lower else max(vals)) if vals else None


def splits(r, a):
    t = r['type'] or ''
    family, keys = (is_run, RUN_SPLITS) if is_run(t) else (is_ride, RIDE_SPLITS) if is_ride(t) else (None, [])
    out = []
    for key, label in keys:
        v = a.get(key)
        if not v:
            continue
        best = _all_time(key, family, r['day'], lower=True)
        metres = int(key.rsplit('_', 1)[1])
        out.append({'label': label, 'value': clock(v), 'pace': _pace(metres / v) + ' /km' if family is is_run else '',
                    'pb': best is not None and v <= best,
                    'best': clock(best) if best and v > best else None})
    return out


def power_bests(r, a):
    if not a.get('maxAvgPower_5'):
        return []
    out = []
    for s, label in POWER:
        v = a.get(f'maxAvgPower_{s}')
        if not v:
            continue
        best = _all_time(f'maxAvgPower_{s}', is_ride, r['day'], lower=False)
        out.append({'label': label, 'value': f'{v:.0f}', 'pct': v / best * 100 if best else 100, 'pb': bool(best) and v >= best,
                    'best': f'{best:.0f}' if best else None})
    return out


def strength(r, a):
    sets = a.get('summarizedExerciseSets') or []
    rows = [{'name': message(s.get('category')) if s.get('category') not in (None, 'UNKNOWN') else 'Other',
             'sets': s.get('sets'), 'reps': s.get('reps'), 'max': f'{s["maxWeight"] / 1000:.1f}' if s.get('maxWeight') else '',
             'volume': f'{s["volume"] / 1000:,.0f}' if s.get('volume') else ''} for s in sets if s.get('sets')]
    jefit = None
    for w in insights.workouts(date.fromisoformat(r['day']), date.fromisoformat(r['day'])):
        if w['garmin'] and w['garmin']['id'] == r['id']:
            jefit = {'volume': f'{(w["volume_kg"] or 0):,.0f}', 'exercises': [
                {'name': e['exercise'], 'sets': e['n'], 'volume': f'{e["vol"]:,.0f}' if e.get('vol') else '', 'kcal': e['kcal']}
                for e in w['exercise_list']]}
    return {'garmin': rows, 'jefit': jefit} if rows or jefit else None


def run_walk(a):
    parts = {s.get('splitType'): s for s in a.get('splitSummaries') or [] if s.get('splitType') in ('RWD_RUN', 'RWD_WALK', 'RWD_STAND')}
    if len(parts) < 2:
        return None
    total = sum(p.get('duration') or 0 for p in parts.values()) or 1
    names = {'RWD_RUN': ('Running', 's1'), 'RWD_WALK': ('Walking', 's3'), 'RWD_STAND': ('Standing', 'other')}
    return [{'label': names[k][0], 'slot': names[k][1], 'pct': (p.get('duration') or 0) / total * 100, 'time': clock(p.get('duration') or 0),
             'km': f'{(p.get("distance") or 0) / 1000:.2f}'} for k, p in sorted(parts.items(), key=lambda kv: list(names).index(kv[0]))]


def compared(r, a):
    """This session against the average of the same type in the 90 days before it."""
    day = date.fromisoformat(r['day'])
    with db.connect() as con:
        rows = [dict(x) for x in con.execute(
            'SELECT duration_s, distance_m, avg_hr, kcal, training_load FROM activities WHERE type=? AND id<>? AND day BETWEEN ? AND ? '
            "AND COALESCE(json_extract(json, '$.manualActivity'), 0) = 0",
            (r['type'], r['id'], (day - timedelta(days=90)).isoformat(), (day - timedelta(days=1)).isoformat()))]
    if len(rows) < 3:
        return None
    out = []
    for key, label, fmt, scale in (('duration_s', 'Time', 'clock', 1), ('distance_m', 'Distance', '{:.1f} km', 1 / 1000),
                                   ('avg_hr', 'Avg heart rate', '{:.0f} bpm', 1), ('kcal', 'Calories', '{:,.0f}', 1),
                                   ('training_load', 'Training load', '{:.0f}', 1)):
        vals = [x[key] for x in rows if x[key]]
        if not r[key] or len(vals) < 3:
            continue
        usual = sum(vals) / len(vals)
        pct = (r[key] - usual) / usual * 100
        show = (lambda v: clock(v)) if fmt == 'clock' else (lambda v, f=fmt, s=scale: f.format(v * s))
        out.append({'label': label, 'value': show(r[key]), 'usual': show(usual), 'pct': pct,
                    'text': 'same' if abs(pct) < 5 else f'{"+" if pct > 0 else "−"}{abs(pct):.0f}%',
                    'dir': 'same' if abs(pct) < 5 else 'up' if pct > 0 else 'down'})
    return {'n': len(rows), 'type': insights.type_label(r['type']).lower(), 'rows': out} if out else None


def build(activity_id):
    r = _get(activity_id)
    if not r:
        return None
    a = json.loads(r['json'] or '{}')
    start = datetime.fromisoformat(r['start_time']) if r['start_time'] else None
    end = start + timedelta(seconds=a.get('elapsedDuration') or r['duration_s'] or 0) if start else None
    d = date.fromisoformat(r['day'])
    when = f'{d.strftime("%A")} {d.day} {MONTHS[d.month - 1]} {d.year}' + (f', {start:%H:%M}–{end:%H:%M}' if start else '')
    prev, nxt = _neighbours(r['start_time'] or r['day'])
    manual = bool(a.get('manualActivity') or a.get('isManualActivity'))
    return {
        'id': r['id'], 'name': r['name'] or insights.type_label(r['type']), 'type': insights.type_label(r['type']),
        'icon': type_icon(r['type'], r['name']), 'when': when, 'place': a.get('locationName'), 'day': r['day'],
        'manual': manual, 'headline': headline(r, a), 'zones': zones(a, r['max_hr'], r['duration_s']),
        'effect': {'label': insights.EFFECT_LABELS.get(a.get('trainingEffectLabel'), ''),
                   'aerobic': _te(r['aerobic_te'], a.get('aerobicTrainingEffectMessage')),
                   'anaerobic': _te(r['anaerobic_te'], a.get('anaerobicTrainingEffectMessage'))} if r['aerobic_te'] is not None else None,
        'details': details(r, a), 'splits': splits(r, a), 'power': power_bests(r, a), 'strength': strength(r, a),
        'run_walk': run_walk(a), 'compared': compared(r, a), 'prev': prev, 'next': nxt,
    }
