# Background jobs: Garmin and Withings sync for everyone at each SYNC_TIME, the import folders every 15 minutes. Each
# person's jobs run against their own database (db.using).
import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler

from . import db, garmin, imports, users, withings
from .config import SYNC_TIME

log = logging.getLogger('jobs')
_running = {}  # user id -> lock held while that person's sync runs


def _lock(user):
    return _running.setdefault(user.id, threading.Lock())


def sync_user(user):
    lock = _lock(user)
    if not lock.acquire(blocking=False):
        return False
    try:
        with db.using(user.db_path):
            for name, job in (('withings', withings.sync), ('garmin', garmin.sync), ('import', lambda: imports.scan(user.import_dir))):
                try:
                    job()
                except Exception:
                    log.exception('%s sync failed for %s', name, user.id)
    finally:
        lock.release()
    return True


def sync_all():
    # One person after the other, so the APIs only ever see one sync at a time from the nightly run.
    for user in users.everyone():
        sync_user(user)


def is_running(user):
    return _lock(user).locked()


def start_in_background(user):
    threading.Thread(target=sync_user, args=(user,), daemon=True).start()


def scan_imports():
    for user in users.everyone():
        try:
            with db.using(user.db_path):
                imports.scan(user.import_dir)
        except Exception:
            log.exception('import scan failed for %s', user.id)


def start_scheduler():
    s = BackgroundScheduler()
    # SYNC_TIME can hold several times, e.g. "09:00,21:00".
    for i, t in enumerate(x.strip() for x in SYNC_TIME.split(',') if x.strip()):
        hour, minute = (int(x) for x in t.split(':'))
        s.add_job(sync_all, 'cron', hour=hour, minute=minute, id=f'daily{i}', misfire_grace_time=3600, coalesce=True)
    s.add_job(scan_imports, 'interval', minutes=15, id='imports')
    s.start()
    return s
