# Web app: one page per area, every page filtered by the date range in the query string (?range=90d or ?from=&to=).
import base64
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db, garmin, jobs, withings
from . import queries as q
from .config import DASHBOARD_PASSWORD, IMPORT_DIR, SYNC_TIME

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / 'templates')
templates.env.filters['dmy'] = lambda iso: f'{iso[8:10]}/{iso[5:7]}/{iso[:4]}' if iso else ''

RANGES = [('30d', '30 days', 30), ('90d', '90 days', 90), ('6m', '6 months', 182), ('1y', '1 year', 365),
          ('3y', '3 years', 1095), ('all', 'All', None)]
PAGES = [('overview', 'Overview', '/'), ('body', 'Body', '/body'), ('training', 'Training', '/training'),
         ('recovery', 'Recovery', '/recovery'), ('nutrition', 'Nutrition', '/nutrition'),
         ('strength', 'Strength', '/strength'), ('setup', 'Setup', '/setup')]


@asynccontextmanager
async def lifespan(app):
    db.init()
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


def chart(cid, title, unit, ser, note='', kind='line', stacked=False, zero=False):
    return {'id': cid, 'title': title, 'unit': unit, 'series': ser, 'note': note, 'kind': kind, 'stacked': stacked,
            'zero': zero, 'empty': not any(s['data'] for s in ser)}


def tile(label, value, unit='', fmt='{:.1f}', delta=None, better=None, note=''):
    """better='up'/'down' colours the change; None leaves it neutral."""
    t = {'label': label, 'value': None if value is None else fmt.format(value), 'unit': unit, 'note': note}
    if delta is not None and value is not None:
        t['delta'] = ('+' if delta > 0 else '−' if delta < 0 else '±') + fmt.format(abs(delta))
        t['tone'] = '' if better is None or abs(delta) < 1e-9 else ('good' if (delta > 0) == (better == 'up') else 'bad')
    return t


def change(metric, start, end):
    pts = q.daily(metric, start, end)
    if not pts:
        return None, None
    return pts[-1][1], (pts[-1][1] - pts[0][1] if len(pts) > 1 else None)


def avg_change(points_now, points_before):
    now, before = q.avg(points_now), q.avg(points_before)
    return now, (now - before if now is not None and before is not None else None)


def render(request, page, ctx):
    rng, start, end = ctx.pop('_range')
    return templates.TemplateResponse(request, f'{"setup" if page == "setup" else "page"}.html', {
        'page': page, 'pages': PAGES, 'ranges': RANGES, 'range': rng, 'start': start.isoformat(), 'end': end.isoformat(),
        'query': request.url.query, **ctx})


@app.get('/', response_class=HTMLResponse)
def overview(request: Request):
    rng, start, end = parse_range(request)
    week, prev = (end - timedelta(days=6), end), (end - timedelta(days=13), end - timedelta(days=7))
    w, dw = change('weight_kg', start, end)
    f, df = change('fat_pct', start, end)
    mu, dmu = change('muscle_kg', start, end)
    rhr, drhr = avg_change(q.daily('resting_hr', *week), q.daily('resting_hr', *prev))
    sl, dsl = avg_change(q.daily('sleep_h', *week), q.daily('sleep_h', *prev))
    kin = q.avg(q.kcal_in(*week))
    hours = sum((a['duration_s'] or 0) for a in q.activities(*week)) / 3600
    load = q.training_load(start, end)
    vo2 = q.latest('vo2max', end, 120)
    tiles = [
        tile('Weight', w, 'kg', delta=dw, note='change over the range'),
        tile('Body fat', f, '%', delta=df, better='down', note='change over the range'),
        tile('Muscle mass', mu, 'kg', delta=dmu, better='up', note='change over the range'),
        tile('Resting HR', rhr, 'bpm', '{:.0f}', drhr, 'down', 'last 7 days vs the 7 before'),
        tile('Sleep', sl, 'h', '{:.1f}', dsl, 'up', 'nightly, last 7 days'),
        tile('Training', hours, 'h', '{:.1f}', note='last 7 days'),
        tile('Calories eaten', kin, 'kcal', '{:,.0f}', note='daily, last 7 days'),
        tile('VO2 max', vo2[1] if vo2 else None, '', '{:.0f}', note=f'Garmin estimate, {vo2[0][8:10]}/{vo2[0][5:7]}' if vo2 else ''),
    ]
    charts = [
        chart('weight', 'Weight', 'kg', trend('Weight', q.daily('weight_kg', start, end))),
        chart('energy', 'Calories eaten and burned', 'kcal', [
            series('Eaten, 7-day avg', q.rolling(q.kcal_in(start, end)), 1),
            series('Burned, 7-day avg', q.rolling(q.daily('total_kcal', start, end)), 2)],
            'Burned is Garmin’s estimate of the whole day, resting energy included.'),
        chart('load', 'Fitness and fatigue', 'load', [
            series('Fitness (42-day)', [(d, c) for d, c, _ in load], 1),
            series('Fatigue (7-day)', [(d, a) for d, _, a in load], 2)],
            'From Garmin’s training load per activity. Fatigue well above fitness means a hard block; below means fresh.'),
        chart('rhr', 'Resting heart rate', 'bpm', trend('Resting HR', q.daily('resting_hr', start, end))),
    ]
    return render(request, 'overview', {'_range': (rng, start, end), 'title': 'Overview', 'tiles': tiles, 'charts': charts})


@app.get('/body', response_class=HTMLResponse)
def body(request: Request):
    rng, start, end = parse_range(request)
    tiles = []
    for metric, label, unit, better in (('weight_kg', 'Weight', 'kg', None), ('fat_pct', 'Body fat', '%', 'down'),
                                        ('fat_mass_kg', 'Fat mass', 'kg', 'down'), ('muscle_kg', 'Muscle mass', 'kg', 'up'),
                                        ('visceral_fat', 'Visceral fat', '', 'down'), ('water_kg', 'Body water', 'kg', None),
                                        ('vascular_age', 'Vascular age', 'years', 'down'), ('bmr_kcal', 'Basal metabolic rate', 'kcal', None)):
        v, d = change(metric, start, end)
        tiles.append(tile(label, v, unit, '{:,.0f}' if metric == 'bmr_kcal' else '{:.1f}', d, better, 'change over the range'))
    charts = [
        chart('weight', 'Weight', 'kg', trend('Weight', q.daily('weight_kg', start, end))),
        chart('fat', 'Body fat', '%', trend('Body fat', q.daily('fat_pct', start, end))),
        chart('muscle', 'Muscle mass', 'kg', trend('Muscle mass', q.daily('muscle_kg', start, end), 3)),
        chart('fatmass', 'Fat mass', 'kg', trend('Fat mass', q.daily('fat_mass_kg', start, end), 2)),
        chart('visceral', 'Visceral fat index', '', [series('Visceral fat', q.daily('visceral_fat', start, end), 1, 'dots')]),
        chart('pwv', 'Pulse wave velocity', 'm/s', [series('Pulse wave velocity', q.daily('pwv', start, end), 1, 'dots')],
              'Arterial stiffness from the Body Scan; lower is better.'),
    ]
    return render(request, 'body', {'_range': (rng, start, end), 'title': 'Body', 'tiles': tiles, 'charts': charts,
                                    'source': 'Withings Body Scan'})


@app.get('/training', response_class=HTMLResponse)
def training(request: Request):
    rng, start, end = parse_range(request)
    acts = q.activities(start, end)
    load = q.training_load(start, end)
    by_type = q.weekly_hours_by_type(start, end)
    weeks = max(1, ((end - start).days + 1) / 7)
    tiles = [
        tile('Activities', len(acts), '', '{:.0f}', note='in the range'),
        tile('Hours per week', sum((a['duration_s'] or 0) for a in acts) / 3600 / weeks, 'h', note='average'),
        tile('Distance', sum((a['distance_m'] or 0) for a in acts) / 1000, 'km', '{:,.0f}', note='in the range'),
        tile('Fitness', load[-1][1] if load else None, '', '{:.0f}', note='42-day load, today'),
        tile('Fatigue', load[-1][2] if load else None, '', '{:.0f}', note='7-day load, today'),
    ]
    charts = [
        chart('hours', 'Training time per week', 'h', [series(t.capitalize(), pts, i + 1, 'bar') for i, (t, pts) in enumerate(by_type.items())],
              kind='bar', stacked=True, zero=True),
        chart('load', 'Fitness and fatigue', 'load', [
            series('Fitness (42-day)', [(d, c) for d, c, _ in load], 1),
            series('Fatigue (7-day)', [(d, a) for d, _, a in load], 2)]),
        chart('form', 'Form (fitness minus fatigue)', 'load', [series('Form', [(d, c - a) for d, c, a in load], 1, 'bar')],
              'Below zero: carrying fatigue. Well above zero: rested, or losing fitness.', kind='bar'),
        chart('vo2', 'VO2 max', '', [series('VO2 max', q.daily('vo2max', start, end), 1, 'line')], 'Garmin’s estimate from runs and rides.'),
        chart('intensity', 'Intensity minutes per week', 'min', [series('Intensity minutes', q.weekly(q.daily('intensity_min', start, end), 'sum'), 1, 'bar')],
              'Vigorous minutes count double, as in Garmin Connect.', kind='bar', zero=True),
    ]
    return render(request, 'training', {'_range': (rng, start, end), 'title': 'Training', 'tiles': tiles, 'charts': charts,
                                        'activities': acts[:50], 'source': 'Garmin Connect'})


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
    charts = [
        chart('sleep', 'Sleep per night, weekly average', 'h', [series(lbl, q.weekly(q.daily(m, start, end)), slot, 'bar') for lbl, m, slot in stages],
              kind='bar', stacked=True, zero=True),
        chart('rhr', 'Resting heart rate', 'bpm', trend('Resting HR', q.daily('resting_hr', start, end))),
        chart('hrv', 'Overnight HRV', 'ms', trend('HRV', q.daily('hrv_sleep', start, end)),
              'The Fenix 6 has no HRV status, so this stays empty unless a newer watch adds it.'),
        chart('score', 'Sleep score', '', trend('Sleep score', q.daily('sleep_score', start, end))),
        chart('bb', 'Body Battery', '', [series('Peak', q.rolling(q.daily('body_battery_high', start, end)), 1),
                                         series('Low', q.rolling(q.daily('body_battery_low', start, end)), 2)], '7-day averages.'),
        chart('stress', 'Average stress', '', trend('Stress', q.daily('stress_avg', start, end))),
        chart('steps', 'Steps per day, weekly average', 'steps', [series('Steps', q.weekly(q.daily('steps', start, end)), 1, 'bar')], kind='bar', zero=True),
    ]
    return render(request, 'recovery', {'_range': (rng, start, end), 'title': 'Recovery', 'tiles': tiles, 'charts': charts,
                                        'source': 'Garmin Connect'})


@app.get('/nutrition', response_class=HTMLResponse)
def nutrition(request: Request):
    rng, start, end = parse_range(request)
    week = (end - timedelta(days=6), end)
    weight = q.latest('weight_kg', end, 60)
    protein = q.avg(q.daily('protein_g', *week))
    tiles = [
        tile('Calories eaten', q.avg(q.kcal_in(*week)), 'kcal', '{:,.0f}', note='daily, last 7 days'),
        tile('Calories burned', q.avg(q.daily('total_kcal', *week)), 'kcal', '{:,.0f}', note='daily, last 7 days (Garmin)'),
        tile('Protein', protein, 'g', '{:.0f}', note='daily, last 7 days'),
        tile('Protein per kg', protein / weight[1] if protein and weight else None, 'g/kg', '{:.1f}', note='at your latest weight'),
        tile('Carbs', q.avg(q.daily('carbs_g', *week)), 'g', '{:.0f}', note='daily, last 7 days'),
        tile('Fat', q.avg(q.daily('fat_g', *week)), 'g', '{:.0f}', note='daily, last 7 days'),
    ]
    macros = [('Protein', 'protein_g', 4, 1), ('Carbs', 'carbs_g', 4, 4), ('Fat', 'fat_g', 9, 2)]
    charts = [
        chart('energy', 'Calories eaten and burned', 'kcal', [
            series('Eaten, 7-day avg', q.rolling(q.kcal_in(start, end)), 1),
            series('Burned, 7-day avg', q.rolling(q.daily('total_kcal', start, end)), 2)]),
        chart('macros', 'Calories by macro, weekly daily average', 'kcal',
              [series(lbl, [(w, v * k) for w, v in q.weekly(q.daily(m, start, end))], slot, 'bar') for lbl, m, k, slot in macros],
              'Protein and carbs at 4 kcal per gram, fat at 9.', kind='bar', stacked=True, zero=True),
        chart('protein', 'Protein', 'g', trend('Protein', q.daily('protein_g', start, end))),
        chart('weight', 'Weight', 'kg', trend('Weight', q.daily('weight_kg', start, end))),
    ]
    return render(request, 'nutrition', {'_range': (rng, start, end), 'title': 'Nutrition', 'tiles': tiles, 'charts': charts,
                                         'source': 'MyFitnessPal or Cronometer export (macros), Garmin Connect (calories)'})


@app.get('/strength', response_class=HTMLResponse)
def strength(request: Request):
    rng, start, end = parse_range(request)
    lifts = q.exercises(start, end)
    names = [x['exercise'] for x in lifts]
    picked = request.query_params.get('exercise') or (names[0] if names else '')
    best, top, vol = q.strength(picked, start, end) if picked else ([], [], [])
    summary = q.strength_summary(start, end)
    with db.connect() as con:
        sessions = con.execute('SELECT COUNT(DISTINCT day) FROM sets WHERE day BETWEEN ? AND ?', (start.isoformat(), end.isoformat())).fetchone()[0]
    weeks = max(1, ((end - start).days + 1) / 7)
    tiles = [
        tile('Sessions', sessions, '', '{:.0f}', note='in the range'),
        tile('Sessions per week', sessions / weeks, '', '{:.1f}', note='average'),
        tile('Exercises', len(lifts), '', '{:.0f}', note='in the range'),
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
                                        'lifts': names, 'picked': picked, 'summary': summary, 'source': 'Jefit export'})


@app.get('/setup', response_class=HTMLResponse)
def setup(request: Request):
    last, recent, counts, imports = q.sync_status()
    return render(request, 'setup', {
        '_range': parse_range(request), 'title': 'Setup', 'last': last, 'recent': recent, 'counts': counts, 'imports': imports,
        'garmin_ready': garmin.has_tokens(), 'withings_configured': withings.configured(), 'withings_connected': withings.connected(),
        'running': jobs.is_running(), 'import_dir': str(IMPORT_DIR), 'sync_time': SYNC_TIME,
        'msg': request.query_params.get('msg', '')})


@app.post('/sync')
def sync_now():
    jobs.start_in_background()
    return RedirectResponse('/setup?msg=Sync+started', 303)


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
