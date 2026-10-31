# Watch folder for the apps without an API: food exports (MyFitnessPal, Cronometer) and strength logs (Jefit, Hevy,
# Strong). Drop a CSV into IMPORT_DIR or upload it on the Setup page; it's recognised by its column names, imported,
# and moved to done/ or failed/. Friends only upload; their files go to their own folder (users.User.import_dir).
import csv
import hashlib
import io
import re
import shutil
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from . import db

LB = 0.45359237
MAX_UPLOAD = 50 * 1024 * 1024
_scan_lock = threading.Lock()


def _norm(h):
    return re.sub(r'[^a-z0-9%]+', ' ', (h or '').lower()).strip()


def _find(headers, *names):
    normed = {_norm(h): h for h in headers}
    for n in names:
        if n in normed:
            return normed[n]
    return None


def _num(v):
    s = str(v or '').strip()
    if s.count(',') == 1 and '.' not in s:
        s = s.replace(',', '.')  # decimal comma: "72,5"
    else:
        s = s.replace(',', '')  # thousands separator: "2,150"
    try:
        return float(s)
    except ValueError:
        return None


DATE_RE = re.compile(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{1,2} [A-Za-z]{3,9},? \d{4}')


def _date_part(v):
    m = DATE_RE.search(v or '')
    return m.group(0).replace(',', '') if m else ''


def _date_parser(values):
    # Picks one format for the whole file, so 03/04 is read the same way on every row.
    samples = [_date_part(v) for v in values if v and v.strip()][:200]
    fmts = ['%Y-%m-%d', '%Y/%m/%d', '%d.%m.%Y', '%d-%m-%Y', '%d %b %Y', '%d %B %Y']
    slash = [s for s in samples if re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', s)]
    if slash:
        day_first = any(int(s.split('/')[0]) > 12 for s in slash)
        fmts.insert(0, '%d/%m/%Y' if day_first else '%m/%d/%Y')
    for fmt in fmts:
        try:
            for s in samples:
                datetime.strptime(s, fmt)
            return lambda v, f=fmt: datetime.strptime(_date_part(v), f).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f'Unknown date format, e.g. "{samples[0] if samples else ""}"')


def import_nutrition(rows, headers, fname):
    date_col = _find(headers, 'date', 'day')
    cols = {
        'kcal_in': _find(headers, 'calories', 'energy kcal', 'energy'),
        'protein_g': _find(headers, 'protein g', 'protein'),
        'carbs_g': _find(headers, 'carbohydrates g', 'carbs g', 'carbohydrates', 'carbs'),
        'fat_g': _find(headers, 'fat g', 'fat'),
        'fibre_g': _find(headers, 'fiber g', 'fiber', 'fibre g'),
    }
    parse = _date_parser([r[date_col] for r in rows])
    totals = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if not r.get(date_col):
            continue
        day = parse(r[date_col])
        for metric, col in cols.items():
            v = _num(r.get(col)) if col else None
            if v is not None:
                totals[day][metric] += v
    with db.tx() as con:
        for day, vals in totals.items():
            for metric, v in vals.items():
                db.put_metric(con, day, metric, v, 'csv')
    return len(totals)


def import_strength(rows, headers, fname, factor=None):
    date_col = _find(headers, 'date', 'workout date', 'log date', 'start time', 'mydate')
    ex_col = _find(headers, 'exercise', 'exercise name', 'exercise title', 'ename', 'name')
    w_col = _find(headers, 'weight kg', 'weight', 'weight lbs', 'kg', 'lbs')
    reps_col = _find(headers, 'reps', 'rep', 'repetitions')
    logs_col = _find(headers, 'logs', 'sets')
    type_col = _find(headers, 'set type', 'type')
    if factor is None:
        in_lb = 'lb' in _norm(w_col or '') or any('lbs' in _norm(h) for h in headers)
        factor = LB if in_lb else 1.0
    parse = _date_parser([r[date_col] for r in rows])
    out = []
    counter = defaultdict(int)
    for r in rows:
        if not r.get(date_col) or not r.get(ex_col):
            continue
        day, ex = parse(r[date_col]), r[ex_col].strip()
        if type_col and 'warm' in (r.get(type_col) or '').lower():
            continue
        if reps_col:
            w, reps = _num(r.get(w_col)) if w_col else None, _num(r.get(reps_col))
            if reps is None:
                continue
            counter[(day, ex)] += 1
            out.append((day, ex, counter[(day, ex)], (w or 0) * factor, int(reps)))
        elif logs_col:
            # One row per exercise with sets written as "60x10,62.5x8".
            for w, reps in re.findall(r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+)', r.get(logs_col) or ''):
                counter[(day, ex)] += 1
                out.append((day, ex, counter[(day, ex)], float(w) * factor, int(reps)))
    with db.tx() as con:
        for day, ex, n, w, reps in out:
            con.execute("INSERT OR REPLACE INTO sets (day, exercise, set_no, weight_kg, reps, source_file, source) VALUES (?,?,?,?,?,?,'csv')",
                        (day, ex, n, round(w, 2), reps, fname))
    return len(out)


def detect(headers):
    h = {_norm(x) for x in headers}
    if h & {'reps', 'rep', 'repetitions', 'logs'} and h & {'exercise', 'exercise name', 'exercise title', 'ename'}:
        return 'strength'
    if h & {'calories', 'energy kcal', 'energy'} and h & {'date', 'day'}:
        return 'nutrition'
    return None


def _section(text, title):
    """One section of a Jefit backup: the CSV between '### TITLE ###' and the next '#' line."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith('### ' + title + ' '):
            inside = True
        elif inside and line.startswith('#'):
            break
        elif inside and line.strip():
            out.append(line)
    return list(csv.DictReader(io.StringIO('\n'.join(out))))


def import_jefit_backup(text, fname):
    # Jefit's account export ("Export data") stacks a dozen CSV sections in one file. EXERCISE LOGS has every
    # exercise done since the first session, sets written as "41x8,41x7", in the unit chosen in Jefit's settings
    # ("mass"). The same exercise id can carry several names over the years (or none), so names are taken per id
    # from its latest log. The backup is the full history, so it replaces all sets from earlier Jefit imports.
    unit = (_section(text, 'SETTING') or [{}])[0].get('mass', '').strip().lower()
    factor = LB if unit.startswith('lb') else 1.0
    rows = _section(text, 'EXERCISE LOGS')
    if not rows:
        raise ValueError('Jefit backup without an EXERCISE LOGS section')
    names = {}
    for r in sorted(rows, key=lambda r: r.get('mydate') or ''):
        if (r.get('ename') or '').strip():
            names[r.get('eid')] = re.sub(r'\s+', ' ', r['ename']).strip()
    out, counter = [], defaultdict(int)
    for r in rows:
        day = (r.get('mydate') or '')[:10]
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', day):
            continue
        eid = r.get('eid') or ''
        ex = names.get(eid) or f'Exercise {eid}'
        log_ts = int(_num(r.get('logTime')) or 0) or None
        for w, reps in re.findall(r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+)', r.get('logs') or ''):
            counter[(day, ex)] += 1
            out.append((day, ex, counter[(day, ex)], round(float(w) * factor, 2), int(reps), fname, eid,
                        r.get('belongsession') or None, log_ts))
    sessions = []
    for s in _section(text, 'WORKOUT SESSIONS'):
        start, end = int(_num(s.get('starttime')) or 0), int(_num(s.get('endtime')) or 0)
        if not start:
            continue
        day = datetime.fromtimestamp(start).date().isoformat()
        sessions.append((s.get('_id'), day, start, end or None, _num(s.get('total_time')), (_num(s.get('total_weight')) or 0) * factor,
                         int(_num(s.get('total_exercise')) or 0)))
    first = min(d[0] for d in out) if out else '9999'
    with db.tx() as con:
        con.execute("DELETE FROM sets WHERE (source = 'jefit' OR source IS NULL) AND day >= ?", (first,))
        con.executemany('INSERT OR REPLACE INTO sets (day, exercise, set_no, weight_kg, reps, source_file, eid, session, log_ts, source) '
                        "VALUES (?,?,?,?,?,?,?,?,?,'jefit')", out)
        con.execute("DELETE FROM workouts WHERE source = 'jefit'")
        con.executemany("INSERT OR REPLACE INTO workouts VALUES (?,?,?,?,?,?,?,'jefit')", sessions)
    return len(out), import_jefit_profile(_section(text, 'PROFILE'), factor), len(sessions)


def import_jefit_profile(rows, factor):
    # Weight and body fat typed into Jefit's profile. A Withings reading of the same day always wins.
    n = 0
    with db.tx() as con:
        for r in rows:
            day = (r.get('mydate') or '')[:10]
            if not re.match(r'^\d{4}-\d{2}-\d{2}$', day):
                continue
            for metric, value in (('weight_kg', (_num(r.get('weight')) or 0) * factor), ('fat_pct', _num(r.get('fatpercent')) or 0)):
                if value <= 0:
                    continue
                if con.execute("SELECT 1 FROM metrics WHERE day=? AND metric=? AND source='withings'", (day, metric)).fetchone():
                    continue
                db.put_metric(con, day, metric, value, 'jefit')
                n += 1
    return n


def import_file(path):
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    text = raw.decode('utf-8-sig', errors='replace')
    jefit = '### EXERCISE LOGS' in text
    # Jefit backups may come again (the importer reads more of them over time); re-importing replaces, never doubles.
    with db.connect() as con:
        if not jefit and con.execute('SELECT 1 FROM imports WHERE sha=?', (sha,)).fetchone():
            return 'duplicate', 0
    if jefit:
        n, body, sessions = import_jefit_backup(text, path.name)
        with db.tx() as con:
            con.execute('INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?)', (sha, path.name, 'jefit', n, db.now()))
        return f'Jefit backup, {sessions} sessions, {body} weight and body fat entries, sets', n
    sample = text[:4096]
    dialect = csv.Sniffer().sniff(sample, delimiters=',;\t') if sample else csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = reader.fieldnames or []
    rows = list(reader)
    kind = detect(headers)
    if kind is None:
        raise ValueError(f'Not recognised as a food or strength export. Columns: {", ".join(headers[:15])}')
    n = (import_nutrition if kind == 'nutrition' else import_strength)(rows, headers, path.name)
    with db.tx() as con:
        con.execute('INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?)', (sha, path.name, kind, n, db.now()))
    return kind, n


def scan(folder):
    """Imports the CSV files in folder into the current database (db.using)."""
    # The 15-minute job and an upload can run at once; only one may move files.
    with _scan_lock:
        return _scan(folder)


def _scan(folder):
    done, failed = folder / 'done', folder / 'failed'
    done.mkdir(parents=True, exist_ok=True)
    failed.mkdir(exist_ok=True)
    files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == '.csv')
    if not files:
        return []
    log = db.log_start('import')
    msgs, ok = [], True
    for p in files:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        try:
            kind, n = import_file(p)
            msgs.append(f'{p.name}: {kind}, {n} rows')
            shutil.move(str(p), done / f'{stamp}-{p.name}')
        except Exception as e:
            ok = False
            msgs.append(f'{p.name}: {e}')
            shutil.move(str(p), failed / f'{stamp}-{p.name}')
            (failed / f'{stamp}-{p.name}.error.txt').write_text(str(e), encoding='utf-8')
    db.log_end(log, 'ok' if ok else 'error', '; '.join(msgs))
    return msgs


def save_upload(folder, name, data):
    """Stores an uploaded file in the import folder under a safe name; scan() then imports it."""
    safe = re.sub(r'[^A-Za-z0-9._ -]+', '_', Path(name or 'upload.csv').name).strip() or 'upload.csv'
    if not safe.lower().endswith('.csv'):
        raise ValueError(f'{safe}: only CSV files can be imported')
    folder.mkdir(parents=True, exist_ok=True)
    (folder / safe).write_bytes(data)
