# Background jobs: Garmin and Withings sync at each SYNC_TIME, the import folder every 15 minutes.
import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from . import garmin, imports, withings
from .config import SYNC_TIME

log = logging.getLogger('jobs')
_running = threading.Lock()


def sync_all():
    if not _running.acquire(blocking=False):
        return False
    try:
        for name, job in (('withings', withings.sync), ('garmin', garmin.sync), ('import', imports.scan)):
            try:
                job()
            except Exception:
                log.exception('%s sync failed', name)
    finally:
        _running.release()
    return True


def is_running():
    return _running.locked()


def start_in_background():
    threading.Thread(target=sync_all, daemon=True).start()


def scan_imports():
    try:
        imports.scan()
    except Exception:
        log.exception('import scan failed')


def start_scheduler():
    s = BackgroundScheduler()
    # SYNC_TIME can hold several times, e.g. "09:00,21:00".
    for i, t in enumerate(x.strip() for x in SYNC_TIME.split(',') if x.strip()):
        hour, minute = (int(x) for x in t.split(':'))
        s.add_job(sync_all, 'cron', hour=hour, minute=minute, id=f'daily{i}', misfire_grace_time=3600, coalesce=True)
    s.add_job(scan_imports, 'interval', minutes=15, id='imports')
    s.start()
    return s
