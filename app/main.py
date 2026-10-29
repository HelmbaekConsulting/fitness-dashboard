# Web app: one page per area, every page filtered by the date range in the query string (?range=90d or ?from=&to=).
import base64
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, figure, garmin, imports, insights, jobs, muscles, withings
from . import queries as q
from .config import DASHBOARD_PASSWORD, IMPORT_DIR, SYNC_TIME

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / 'templates')
templates.env.filters['dmy'] = lambda iso: f'{iso[8:10]}/{iso[5:7]}/{iso[:4]}' if iso else ''

RANGES = [('30d', '30 days', 30), ('90d', '90 days', 90), ('6m', '6 months', 182), ('1y', '1 year', 365),
          ('3y', '3 years', 1095), ('all', 'All', None)]
PAGES = [('overview', 'Overview', '/'), ('body', 'Body', '/body'), ('muscles', 'Muscles', '/muscles'),
         ('progress', 'Training vs body', '/progress'), ('training', 'Training', '/training'),
         ('recovery', 'Recovery', '/recovery'), ('nutrition', 'Nutrition', '/nutrition'),
         ('strength', 'Strength', '/strength'), ('setup', 'Setup', '/setup')]


@asynccontextmanager
async def lifespan(app):
    db.init()
    withings.reextract()
    sched = jobs.start_scheduler()
    yield
    sched.shutdown(wait=False)


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')


@app.middleware('http')
async def basic_auth(request: Request, call_next):
    if DASHBOARD_PASSWORD and request.url.path != '/withings/callback':
        auth = request.headers.get('authorization', '')
        ok = False
        if auth.startswith('Basic '):
            try:
                _, _, pw = base64.b64decode(auth[6:]).decode().partition(':')
                ok = secrets.compare_digest(pw, DASHBOARD_PASSWORD)
            except Exception:
                ok = False
        if not ok:
            return Response('Login required', 401, {'WWW-Authenticate': 'Basic realm="Fitness"'})
    return await call_next(request)


def parse_range(request):
    p = request.query_params
    today = date.today()
    try:
        if not p.get('range') and (p.get('from') or p.get('to')):
            start = date.fromisoformat(p['from']) if p.get('from') else q.first_day()
            end = date.fromisoformat(p['to']) if p.get('to') else today
            return 'custom', min(start, end), max(start, end)
    except ValueError:
        pass
    key = p.get('range', '90d')
    for k, _, days in RANGES:
        if k == key:
            return k, (q.first_day() if days is None else today - timedelta(days=days - 1)), today
    return '90d', today - timedelta(days=89), today


def series(label, data, slot=1, style='line'):
    return {'label': label, 'slot': slot, 'style': style, 'data': [[d, round(v, 2)] for d, v in data]}


def trend(label, data, slot=1):
    """Daily readings as faint dots plus their 7-day average as the line."""
    return [{**series(label, data, slot, 'dots'), 'legend': False}, series(f'{label}, 7-day avg', q.rolling(data), slot, 'line')]


def weight_trend(start, end):
    return [{**series('Weigh-ins', q.daily('weight_kg', start, end), 1, 'dots'), 'legend': False},
            series('Trend weight', insights.trend_weight(start, end), 1, 'line')]


def chart(cid, title, unit, ser, note='', kind='line', stacked=False, zero=False, span=None):
    """span=(start, end) pins the x axis, so charts stacked above each other line up."""
    c = {'id': cid, 'title': title, 'unit': unit, 'series': ser, 'note': note, 'kind': kind, 'stacked': stacked,
         'zero': zero, 'empty': not any(s['data'] for s in ser)}
    if span:
        c['xmin'], c['xmax'] = span[0].isoformat(), span[1].isoformat()
    return c


def tile(label, value, unit='', fmt='{:.1f}', delta=None, better=None, note=''):
    """better='up'/'down' colours the change; None leaves it neutral."""
    t = {'label': label, 'value': None if value is None else fmt.format(value), 'unit': unit, 'note': note}
    if delta is not None and value is not None:
        shown = fmt.format(abs(delta))
        zero = not any(ch in '123456789' for ch in shown)
        t['delta'] = ('±' if zero else '+' if delta > 0 else '−') + shown
        t['tone'] = '' if better is None or zero else ('good' if (delta > 0) == (better == 'up') else 'bad')
    return t


def change(metric, start, end):
    pts = q.daily(metric, start, end)
    if not pts:
        return None, None
    return pts[-1][1], (pts[-1][1] - pts[0][1] if len(pts) > 1 else None)


def avg_change(points_now, points_before):
    now, before = q.avg(points_now), q.avg(points_before)
    return now, (now - before if now is not None and before is not None else None)


def toggle(request, key, options, current):
    """Links that switch one query parameter and keep the rest (date range, exercise)."""
    out = []
    for value, label in options:
        params = dict(request.query_params)
        params[key] = value
        out.append({'label': label, 'href': '?' + urlencode(params), 'on': value == current})
    return {'key': key, 'value': current, 'options': out}


def render(request, page, ctx):
    rng, start, end = ctx.pop('_range')
    return templates.TemplateResponse(request, f'{"setup" if page == "setup" else "page"}.html', {
        'page': page, 'pages': PAGES, 'ranges': RANGES, 'range': rng, 'start': start.isoformat(), 'end': end.isoformat(),
        'query': request.url.query, **ctx})


# ---- Figures ---------------------------------------------------------------------------------------------------

def muscle_panel(vol, mode, title, note=''):
    def paint(m, seg):
        if seg == 'head':
            return 'head', ''
        if not m:
            return '', ''
        v = vol[m]
        if mode == 'recency':
            when = 'never' if v['days_since'] is None else 'today' if v['days_since'] == 0 else f'{v["days_since"]} days ago'
            return insights.recency_class(v['days_since']), f'{v["label"]}: last trained {when}'
        return insights.volume_class(v['per_week']), f'{v["label"]}: {v["per_week"]:.1f} sets/week'
    legend = insights.RECENCY_LEGEND if mode == 'recency' else insights.VOLUME_LEGEND
    return {'title': title, 'note': note, 'svgs': [figure.svg('front', paint, title), figure.svg('back', paint, title)],
            'legend': legend, 'legend_title': 'Last trained' if mode == 'recency' else 'Sets per week'}


def segment_panel(seg, what, title, note=''):
    better_up = what == 'muscle'

    def paint(m, s):
        if s == 'head':
            return 'head', ''
        v = seg.get(s)
        if not v or v['latest'] is None:
            return '', f'{insights.SEG_LABEL.get(s, s)}: no Body Scan data'
        ch = f', {v["change"]:+.2f} kg' if v['change'] is not None else ''
        return insights.segment_change_class(v['pct'], better_up), f'{v["label"]}: {v["latest"]:.2f} kg{ch}'
    rows = [{'label': v['label'], 'value': v['latest'], 'change': v['change'], 'pct': v['pct'],
             'tone': '' if v['pct'] is None or abs(v['pct']) < 0.5 else ('good' if (v['pct'] > 0) == better_up else 'bad')}
            for v in seg.values()]
    return {'title': title, 'note': note, 'svgs': [figure.svg('front', paint, title)], 'rows': rows, 'diverging': True,
            'legend': [('dn3', ''), ('dn2', ''), ('dn1', ''), ('d0', 'no change'), ('dp1', ''), ('dp2', ''), ('dp3', '')],
            'legend_title': 'Worse ← → Better', 'empty': all(v['latest'] is None for v in seg.values())}


# ---- Pages -----------------------------------------------------------------------------------------------------

@app.get('/', response_class=HTMLResponse)
def overview(request: Request):
    rng, start, end = parse_range(request)
    week, prev = (end - timedelta(days=6), end), (end - timedelta(days=13), end - timedelta(days=7))
    w, dw = change('weight_kg', start, end)
    f, df = change('fat_pct', start, end)
    mu, dmu = change('muscle_kg', start, end)
    rhr, drhr = avg_change(q.daily('resting_hr', *week), q.daily('resting_hr', *prev))
    sl, dsl = avg_change(q.daily('sleep_h', *week), q.daily('sleep_h', *prev))
    hours = sum((a['duration_s'] or 0) for a in q.activities(*week)) / 3600
    load = q.training_load(start, end)
    tdee = insights.expenditure(end - timedelta(days=13), end)
    tw = insights.trend_weight(start, end)
    tiles = [
        tile('Trend weight', tw[-1][1] if tw else w, 'kg', delta=(tw[-1][1] - tw[0][1]) if len(tw) > 1 else dw, note='change over the range'),
        tile('Body fat', f, '%', delta=df, better='down', note='change over the range'),
        tile('Muscle mass', mu, 'kg', delta=dmu, better='up', note='change over the range'),
        tile('Resting HR', rhr, 'bpm', '{:.0f}', drhr, 'down', 'last 7 days vs the 7 before'),
        tile('Sleep', sl, 'h', '{:.1f}', dsl, 'up', 'nightly, last 7 days'),
        tile('Training', hours, 'h', '{:.1f}', note='last 7 days'),
        tile('Maintenance', tdee[-1][1] if tdee else None, 'kcal', '{:,.0f}', note='measured from food and weight, 28 days'),
        tile('Overnight HRV', q.avg(q.daily('hrv_sleep', *week)), 'ms', '{:.0f}', note='last 7 days'),
    ]
    vol, _ = insights.muscle_volume(start, end)
    charts = [
        chart('weight', 'Weight', 'kg', weight_trend(start, end), 'Trend weight smooths out water and food swings.'),
        chart('energy', 'Calories eaten and burned', 'kcal', [
            series('Eaten, 7-day avg', q.rolling(q.kcal_in(start, end)), 1),
            series('Burned (Garmin), 7-day avg', q.rolling(q.daily('total_kcal', start, end)), 2),
            series('Measured maintenance', insights.expenditure(start, end), 3)],
            'Measured maintenance is what you ate minus the energy in your trend weight change.'),
        chart('load', 'Fitness and fatigue', 'load', [
            series('Fitness (42-day)', [(d, c) for d, c, _ in load], 1),
            series('Fatigue (7-day)', [(d, a) for d, _, a in load], 2)],
            'From Garmin’s training load per activity. Fatigue well above fitness means a hard block; below means fresh.'),
        chart('rhr', 'Resting heart rate', 'bpm', trend('Resting HR', q.daily('resting_hr', start, end))),
    ]
    return render(request, 'overview', {'_range': (rng, start, end), 'title': 'Overview', 'tiles': tiles, 'charts': charts,
                                        'readiness': insights.readiness(end),
                                        'panels': [muscle_panel(vol, 'volume', 'Muscles trained', 'Sets per week in the range.')]})


@app.get('/body', response_class=HTMLResponse)
def body(request: Request):
    rng, start, end = parse_range(request)
    what = 'fat' if request.query_params.get('show') == 'fat' else 'muscle'
    seg = insights.segments(start, end, what)
    asym = insights.asymmetry(insights.segments(start, end, 'muscle'))
    tiles = []
    for metric, label, unit, better in (('weight_kg', 'Weight', 'kg', None), ('fat_pct', 'Body fat', '%', 'down'),
                                        ('fat_mass_kg', 'Fat mass', 'kg', 'down'), ('muscle_kg', 'Muscle mass', 'kg', 'up'),
                                        ('visceral_fat', 'Visceral fat', '', 'down'), ('water_kg', 'Body water', 'kg', None),
                                        ('vascular_age', 'Vascular age', 'years', 'down'), ('bmr_kcal', 'Basal metabolic rate', 'kcal', None)):
        v, d = change(metric, start, end)
        tiles.append(tile(label, v, unit, '{:,.0f}' if metric == 'bmr_kcal' else '{:.1f}', d, better, 'change over the range'))
    for part, label in (('arm', 'Arm balance'), ('leg', 'Leg balance')):
        a = asym[part]
        tiles.append(tile(label, abs(a) if a is not None else None, '%', '{:.1f}',
                          note='' if a is None else f'{"right" if a > 0 else "left"} side has more muscle' if abs(a) >= 0.1 else 'even'))
    word = 'Muscle' if what == 'muscle' else 'Fat'
    panel = segment_panel(seg, what, f'{word} mass by body segment',
                          f'Colour shows the change over the range; {"more muscle" if what == "muscle" else "less fat"} is better.')
    seg_charts = []
    for part, label in (('arm', 'Arms'), ('leg', 'Legs')):
        seg_charts.append(chart(f'seg-{part}', f'{label}: {word.lower()} mass', 'kg', [
            series('Right', q.rolling(seg[f'right_{part}']['points'], 14), 1), series('Left', q.rolling(seg[f'left_{part}']['points'], 14), 2)],
            '14-day averages of the Body Scan readings.'))
    seg_charts.append(chart('seg-trunk', f'Trunk: {word.lower()} mass', 'kg', trend('Trunk', seg['trunk']['points'], 3)))
    charts = seg_charts + [
        chart('weight', 'Weight', 'kg', weight_trend(start, end)),
        chart('fat', 'Body fat', '%', trend('Body fat', q.daily('fat_pct', start, end))),
        chart('muscle', 'Muscle mass', 'kg', trend('Muscle mass', q.daily('muscle_kg', start, end), 3)),
        chart('fatmass', 'Fat mass', 'kg', trend('Fat mass', q.daily('fat_mass_kg', start, end), 2)),
        chart('visceral', 'Visceral fat index', '', [series('Visceral fat', q.daily('visceral_fat', start, end), 1, 'dots')]),
        chart('pwv', 'Pulse wave velocity', 'm/s', [series('Pulse wave velocity', q.daily('pwv', start, end), 1, 'dots')],
              'Arterial stiffness from the Body Scan; lower is better.'),
    ]
    other = insights.other_segment_metrics()
    return render(request, 'body', {'_range': (rng, start, end), 'title': 'Body', 'tiles': tiles, 'charts': charts, 'panels': [panel],
                                    'toggle': toggle(request, 'show', [('muscle', 'Muscle'), ('fat', 'Fat')], what),
                                    'notice': f'Unrecognised Body Scan segments: {", ".join(other)}' if other else '',
                                    'source': 'Withings Body Scan (segments measured by bioimpedance, so single readings vary; '
                                              'watch the trend); older weight and body fat typed into Jefit’s profile'})


@app.get('/muscles', response_class=HTMLResponse)
def muscles_page(request: Request):
    rng, start, end = parse_range(request)
    mode = 'recency' if request.query_params.get('mode') == 'recency' else 'volume'
    vol, unmapped = insights.muscle_volume(start, end)
    bal = insights.balance(vol)
    trained = sum(1 for v in vol.values() if v['per_week'] >= 10)
    tiles = [
        tile('Muscles at 10+ sets', trained, f'of {len(vol)}', '{:.0f}', note='sets per week in the range'),
        tile('Push : pull', bal['push'] / bal['pull'] if bal['pull'] else None, '', '{:.2f}', note=f'{bal["push"]:.0f} vs {bal["pull"]:.0f} sets/week; about 1 is balanced'),
        tile('Upper : lower', bal['upper'] / bal['lower'] if bal['lower'] else None, '', '{:.2f}', note=f'{bal["upper"]:.0f} vs {bal["lower"]:.0f} sets/week'),
    ]
    rows = []
    for m, v in sorted(vol.items(), key=lambda kv: -kv[1]['per_week']):
        pw = v['per_week']
        status = ('good', '●', 'In range') if 10 <= pw <= 20 else ('warning', '▲', 'High') if pw > 20 else ('serious', '▽', 'Low') if pw > 0 else ('critical', '○', 'Not trained')
        rows.append({**v, 'status': status})
    panel = muscle_panel(vol, mode, 'Sets per week' if mode == 'volume' else 'Last trained',
                         'A set counts fully for the main muscles of an exercise and half for the helpers. '
                         'Around 10–20 hard sets per muscle per week is the common guideline for growth.' if mode == 'volume'
                         else 'Days since each muscle last worked, as a main or helping muscle, up to the end of the range.')
    weekly = insights.muscle_weekly_by_segment(start, end)
    charts = [chart('segsets', 'Sets per week by body area', 'sets',
                    [series(muscles.SEGMENTS[s], pts, i + 1, 'bar') for i, (s, pts) in enumerate(weekly.items())], kind='bar', stacked=True, zero=True)]
    return render(request, 'muscles', {'_range': (rng, start, end), 'title': 'Muscles', 'tiles': tiles, 'charts': charts,
                                       'panels': [panel], 'muscle_rows': rows, 'unmapped': unmapped,
                                       'toggle': toggle(request, 'mode', [('volume', 'Sets per week'), ('recency', 'Last trained')], mode),
                                       'source': 'Jefit export; muscles per exercise from the exercise name'})


@app.get('/progress', response_class=HTMLResponse)
def progress(request: Request):
    rng, start, end = parse_range(request)
    vol, _ = insights.muscle_volume(start, end)
    seg = insights.segments(start, end, 'muscle')
    weekly = insights.muscle_weekly_by_segment(start, end)
    frames = insights.monthly_timeline(start, end)
    panels = [muscle_panel(vol, 'volume', 'What you trained', 'Sets per week.'),
              segment_panel(seg, 'muscle', 'How your muscle changed', 'Body Scan muscle mass, change over the range.')]
    pairs = []
    for group, parts, label in (('arms', ['right_arm', 'left_arm'], 'Arms'), ('trunk', ['trunk'], 'Trunk'), ('legs', ['right_leg', 'left_leg'], 'Legs')):
        pw = sum(v for _, v in weekly[group]) / max(1, len(weekly[group]))
        ch = [seg[p]['change'] for p in parts if seg[p]['change'] is not None]
        pairs.append({'label': label, 'sets_week': pw, 'change': sum(ch) if ch else None, 'charts': [
            chart(f'{group}-sets', f'{label}: sets per week', 'sets', [series('Sets', weekly[group], 1, 'bar')], kind='bar', zero=True, span=(start, end)),
            chart(f'{group}-muscle', f'{label}: Body Scan muscle mass', 'kg',
                  [series(insights.SEG_LABEL[p], q.rolling(seg[p]['points'], 14), i + 1) for i, p in enumerate(parts)],
                  '14-day averages.', span=(start, end))]})
    return render(request, 'progress', {'_range': (rng, start, end), 'title': 'Training vs body', 'panels': panels, 'pairs': pairs,
                                        'charts': [c for p in pairs for c in p['charts']], 'frames': frames,
                                        'source': 'Jefit export and Withings Body Scan. Segment edges are approximate: shoulders and '
                                                  'back count as trunk, glutes as legs. Bioimpedance segments vary from scan to scan, '
                                                  'so look at months, not single weeks'})


@app.get('/training', response_class=HTMLResponse)
def training(request: Request):
    rng, start, end = parse_range(request)
    acts = q.activities(start, end)
    load = q.training_load(start, end)
    by_type = q.weekly_hours_by_type(start, end)
    weeks = max(1, ((end - start).days + 1) / 7)
    zones = insights.hr_zones_weekly(start, end)
    z2 = sum(v for _, v in zones[2]) / weeks if zones[2] else None
    cal_start = max(start, end - timedelta(days=364))
    cal, active = insights.calendar(cal_start, end)
    tiles = [
        tile('Activities', len(acts), '', '{:.0f}', note='in the range'),
        tile('Hours per week', sum((a['duration_s'] or 0) for a in acts) / 3600 / weeks, 'h', note='average'),
        tile('Zone 2', z2, 'min', '{:.0f}', note='per week, average'),
        tile('Distance', sum((a['distance_m'] or 0) for a in acts) / 1000, 'km', '{:,.0f}', note='in the range'),
        tile('Fitness', load[-1][1] if load else None, '', '{:.0f}', note='42-day load, today'),
        tile('Fatigue', load[-1][2] if load else None, '', '{:.0f}', note='7-day load, today'),
    ]
    zone_slots = ['l2', 'l3', 'l4', 'l5', 'l6']
    charts = [
        chart('hours', 'Training time per week', 'h', [series(t.capitalize(), pts, i + 1, 'bar') for i, (t, pts) in enumerate(by_type.items())],
              kind='bar', stacked=True, zero=True),
        chart('zones', 'Time in heart-rate zones per week', 'min', [series(f'Zone {z}', zones[z], zone_slots[z - 1], 'bar') for z in range(1, 6)],
              'Zones as set in Garmin Connect. Zone 2 is the easy, conversational pace most endurance plans build on.',
              kind='bar', stacked=True, zero=True),
        chart('load', 'Fitness and fatigue', 'load', [
            series('Fitness (42-day)', [(d, c) for d, c, _ in load], 1),
            series('Fatigue (7-day)', [(d, a) for d, _, a in load], 2)]),
        chart('form', 'Form (fitness minus fatigue)', 'load', [series('Form', [(d, c - a) for d, c, a in load], 1, 'bar')],
              'Below zero: carrying fatigue. Well above zero: rested, or losing fitness.', kind='bar'),
        chart('intensity', 'Intensity minutes per week', 'min', [series('Intensity minutes', q.weekly(q.daily('intensity_min', start, end), 'sum'), 1, 'bar')],
              'Vigorous minutes count double, as in Garmin Connect.', kind='bar', zero=True),
    ]
    return render(request, 'training', {'_range': (rng, start, end), 'title': 'Training', 'tiles': tiles, 'charts': charts,
                                        'calendar': cal, 'calendar_active': active, 'calendar_from': cal_start.isoformat(),
                                        'activities': acts[:50], 'source': 'Garmin Connect; Jefit sessions without a watch recording'})


@app.get('/recovery', response_class=HTMLResponse)
def recovery(request: Request):
    rng, start, end = parse_range(request)
    week, prev = (end - timedelta(days=6), end), (end - timedelta(days=13), end - timedelta(days=7))
    tiles = []
    for metric, label, unit, fmt, better in (('resting_hr', 'Resting HR', 'bpm', '{:.0f}', 'down'), ('sleep_h', 'Sleep', 'h', '{:.1f}', 'up'),
                                             ('hrv_sleep', 'Overnight HRV', 'ms', '{:.0f}', 'up'), ('stress_avg', 'Stress', '', '{:.0f}', 'down'),
                                             ('body_battery_high', 'Body Battery peak', '', '{:.0f}', 'up'), ('steps', 'Steps', '', '{:,.0f}', 'up')):
        v, d = avg_change(q.daily(metric, *week), q.daily(metric, *prev))
        tiles.append(tile(label, v, unit, fmt, d, better, 'last 7 days vs the 7 before'))
    stages = [('Deep', 'sleep_deep_h', 1), ('Light', 'sleep_light_h', 3), ('REM', 'sleep_rem_h', 7), ('Awake', 'sleep_awake_h', 4)]
    line, lo, hi = insights.hrv_band(start, end)
    charts = [
        chart('hrv', 'Overnight HRV and your normal range', 'ms', [
            {**series('Normal range low', lo, 1, 'band_lo'), 'legend': False}, series('Normal range', hi, 1, 'band_hi'),
            series('HRV, 7-day avg', line, 1)],
            'Normal range: your 60-day average ± one standard deviation. Below it often means stress, illness or too little recovery.'),
        chart('sleep', 'Sleep per night, weekly average', 'h', [series(lbl, q.weekly(q.daily(m, start, end)), slot, 'bar') for lbl, m, slot in stages],
              kind='bar', stacked=True, zero=True),
        chart('rhr', 'Resting heart rate', 'bpm', trend('Resting HR', q.daily('resting_hr', start, end))),
        chart('score', 'Sleep score', '', trend('Sleep score', q.daily('sleep_score', start, end))),
        chart('bb', 'Body Battery', '', [series('Peak', q.rolling(q.daily('body_battery_high', start, end)), 1),
                                         series('Low', q.rolling(q.daily('body_battery_low', start, end)), 2)], '7-day averages.'),
        chart('stress', 'Average stress', '', trend('Stress', q.daily('stress_avg', start, end))),
        chart('steps', 'Steps per day, weekly average', 'steps', [series('Steps', q.weekly(q.daily('steps', start, end)), 1, 'bar')], kind='bar', zero=True),
    ]
    return render(request, 'recovery', {'_range': (rng, start, end), 'title': 'Recovery', 'tiles': tiles, 'charts': charts,
                                        'readiness': insights.readiness(end), 'source': 'Garmin Connect'})


@app.get('/nutrition', response_class=HTMLResponse)
def nutrition(request: Request):
    rng, start, end = parse_range(request)
    week = (end - timedelta(days=6), end)
    weight = q.latest('weight_kg', end, 60)
    protein = q.avg(q.daily('protein_g', *week))
    tdee = insights.expenditure(start, end)
    burned = q.avg(q.daily('total_kcal', end - timedelta(days=27), end))
    tiles = [
        tile('Measured maintenance', tdee[-1][1] if tdee else None, 'kcal', '{:,.0f}', note='from food and trend weight, last 28 days'),
        tile('Garmin’s estimate', burned, 'kcal', '{:,.0f}', note='calories burned, last 28 days'),
        tile('Calories eaten', q.avg(q.kcal_in(*week)), 'kcal', '{:,.0f}', note='daily, last 7 days'),
        tile('Protein', protein, 'g', '{:.0f}', note='daily, last 7 days'),
        tile('Protein per kg', protein / weight[1] if protein and weight else None, 'g/kg', '{:.1f}', note='1.6 g/kg is the usual target for muscle gain'),
        tile('Carbs', q.avg(q.daily('carbs_g', *week)), 'g', '{:.0f}', note='daily, last 7 days'),
        tile('Fat', q.avg(q.daily('fat_g', *week)), 'g', '{:.0f}', note='daily, last 7 days'),
    ]
    macros = [('Protein', 'protein_g', 4, 1), ('Carbs', 'carbs_g', 4, 4), ('Fat', 'fat_g', 9, 2)]
    charts = [
        chart('tdee', 'Maintenance calories: measured vs Garmin', 'kcal', [
            series('Measured maintenance', tdee, 3),
            series('Garmin’s estimate, 28-day avg', [p for p in q.rolling(q.daily('total_kcal', start - timedelta(days=28), end), 28)
                                                    if p[0] >= start.isoformat()], 2),
            series('Eaten, 7-day avg', q.rolling(q.kcal_in(start, end)), 1)],
            'Measured maintenance: average calories eaten minus 7,700 kcal per kg of trend weight change, over 28 days with at '
            'least 18 days logged. It assumes logged days are complete.'),
        chart('weight', 'Trend weight', 'kg', weight_trend(start, end)),
        chart('macros', 'Calories by macro, weekly daily average', 'kcal',
              [series(lbl, [(w, v * k) for w, v in q.weekly(q.daily(m, start, end))], slot, 'bar') for lbl, m, k, slot in macros],
              'Protein and carbs at 4 kcal per gram, fat at 9.', kind='bar', stacked=True, zero=True),
        chart('protein', 'Protein', 'g', trend('Protein', q.daily('protein_g', start, end))),
    ]
    return render(request, 'nutrition', {'_range': (rng, start, end), 'title': 'Nutrition', 'tiles': tiles, 'charts': charts,
                                         'source': 'MyFitnessPal (through Garmin Connect, or an export for macros), Withings weight'})


@app.get('/strength', response_class=HTMLResponse)
def strength(request: Request):
    rng, start, end = parse_range(request)
    lifts = q.exercises(start, end)
    names = [x['exercise'] for x in lifts]
    picked = request.query_params.get('exercise') or (names[0] if names else '')
    best, top, vol = q.strength(picked, start, end) if picked else ([], [], [])
    summary = q.strength_summary(start, end)
    ws = insights.workouts(start, end)
    with_kcal = [w for w in ws if w['kcal']]
    measured = sum(1 for w in ws if w['kcal_source'] == 'garmin')
    ex_kcal, ex_n, ex_measured = insights.exercise_kcal(picked, ws) if picked else (None, 0, 0)
    with db.connect() as con:
        sessions = con.execute('SELECT COUNT(DISTINCT day) FROM sets WHERE day BETWEEN ? AND ?', (start.isoformat(), end.isoformat())).fetchone()[0]
    weeks = max(1, ((end - start).days + 1) / 7)
    recs = insights.records(start, end)
    tiles = [
        tile('Sessions', sessions, '', '{:.0f}', note='in the range'),
        tile('Sessions per week', sessions / weeks, '', '{:.1f}', note='average'),
        tile('Calories per session', q.avg([(0, w['kcal']) for w in with_kcal]), 'kcal', '{:.0f}',
             note=f'{measured} of {len(with_kcal)} measured by Garmin, the rest estimated'),
        tile('Records', len(recs), '', '{:.0f}', note='new best estimated 1RM in the range'),
        tile(f'{picked or "Exercise"}: calories', ex_kcal, 'kcal', '{:.0f}',
             note=f'per session, {ex_n} sessions ({ex_measured} measured)' if ex_n else 'no sessions in the range'),
    ]
    charts = [
        chart('e1rm', f'{picked}: estimated 1RM' if picked else 'Estimated 1RM', 'kg',
              [series('Estimated 1RM', best, 1, 'line'), series('Heaviest set', top, 2, 'dots')],
              'Best set of each session, Epley formula; sets above 12 reps are left out.'),
        chart('volume', f'{picked}: volume per session' if picked else 'Volume per session', 'kg', [series('Volume', vol, 1, 'bar')],
              'Weight × reps, summed over the session.', kind='bar', zero=True),
        chart('weekvol', 'Total volume per week, all exercises', 'kg', [series('Volume', q.weekly_volume(start, end), 3, 'bar')], kind='bar', zero=True),
    ]
    return render(request, 'strength', {'_range': (rng, start, end), 'title': 'Strength', 'tiles': tiles, 'charts': charts,
                                        'lifts': names, 'picked': picked, 'summary': summary, 'workouts': ws[:40], 'records': recs,
                                        'source': 'Jefit export; calories and heart rate from Garmin where the watch recorded the session'})


@app.get('/setup', response_class=HTMLResponse)
def setup(request: Request):
    last, recent, counts, imports = q.sync_status()
    return render(request, 'setup', {
        '_range': parse_range(request), 'title': 'Setup', 'last': last, 'recent': recent, 'counts': counts, 'imports': imports,
        'garmin_ready': garmin.has_key(), 'withings_configured': withings.configured(), 'withings_connected': withings.connected(),
        'running': jobs.is_running(), 'import_dir': str(IMPORT_DIR), 'sync_time': SYNC_TIME,
        'withings_fields': q.withings_fields(), 'msg': request.query_params.get('msg', '')})


@app.post('/sync')
def sync_now():
    jobs.start_in_background()
    return RedirectResponse('/setup?msg=Sync+started', 303)


@app.post('/upload')
async def upload(files: list[UploadFile] = File(...)):
    errors = []
    for f in files:
        data = await f.read(imports.MAX_UPLOAD + 1)
        try:
            if len(data) > imports.MAX_UPLOAD:
                raise ValueError(f'{f.filename}: larger than 50 MB')
            imports.save_upload(f.filename, data)
        except ValueError as e:
            errors.append(str(e))
    msgs = errors + (await run_in_threadpool(imports.scan) or [])
    return RedirectResponse('/setup?' + urlencode({'msg': '; '.join(msgs)[:600] or 'Nothing to import.'}), 303)


@app.get('/withings/connect')
def withings_connect():
    return RedirectResponse(withings.auth_url(), 302)


@app.get('/withings/callback')
def withings_callback(code: str = '', state: str = ''):
    try:
        withings.exchange_code(code, state)
    except Exception as e:
        return RedirectResponse('/setup?' + urlencode({'msg': f'Withings failed: {str(e)[:150]}'}), 303)
    jobs.start_in_background()
    return RedirectResponse('/setup?' + urlencode({'msg': 'Withings connected. First sync started.'}), 303)
