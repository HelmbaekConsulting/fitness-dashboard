# Who uses the dashboard: you (the owner: data/fitness.db, and everyone on the home network) and the friends you invite
# on the admin page, each with their own database and upload folder under data/users/<id>/. Outside the home network
# Cloudflare Access logs people in by e-mail; its signed token (Cf-Access-Jwt-Assertion) says who they are.
import re
import secrets
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt

from . import db
from .config import CF_ACCESS_AUD, CF_ACCESS_TEAM, DATA_DIR, DB_PATH, IMPORT_DIR, OWNER_EMAIL, USERS_DIR

USERS_DB = DATA_DIR / 'users.db'
# Cloudflare adds these to every request it passes on, so a request with any of them came in through the tunnel.
CF_HEADERS = ('cf-ray', 'cf-connecting-ip', 'cf-access-jwt-assertion')
EMAIL = re.compile(r'[^@\s]+@[^@\s]+\.[^@\s]+')


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str
    invited: str = ''
    last_seen: str = ''

    @property
    def is_owner(self):
        return self.id == 'owner'

    @property
    def folder(self):
        return DATA_DIR if self.is_owner else USERS_DIR / self.id

    @property
    def db_path(self):
        return DB_PATH if self.is_owner else self.folder / 'fitness.db'

    @property
    def import_dir(self):
        return IMPORT_DIR if self.is_owner else self.folder / 'import'


OWNER = User('owner', OWNER_EMAIL, 'You')


def _connect():
    con = sqlite3.connect(USERS_DB, timeout=30, factory=db.Connection)
    con.row_factory = sqlite3.Row
    return con


def init():
    with _connect() as con:
        con.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, '
                    'invited TEXT NOT NULL, last_seen TEXT)')


def _user(row):
    return User(row['id'], row['email'], row['name'], row['invited'], row['last_seen'] or '')


def friends():
    with _connect() as con:
        return [_user(r) for r in con.execute('SELECT * FROM users ORDER BY invited')]


def everyone():
    return [OWNER] + friends()


def get(user_id):
    return next((u for u in everyone() if u.id == user_id), None)


def by_email(email):
    with _connect() as con:
        row = con.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    return _user(row) if row else None


def invite(email, name):
    email = email.strip().lower()
    if not EMAIL.fullmatch(email):
        raise ValueError('That doesn’t look like an e-mail address.')
    if email == OWNER_EMAIL:
        raise ValueError('That’s your own address.')
    if by_email(email):
        raise ValueError(f'{email} is already invited.')
    user = User(secrets.token_hex(6), email, name.strip()[:60] or email.split('@')[0], datetime.now().isoformat(timespec='seconds'))
    user.import_dir.mkdir(parents=True, exist_ok=True)
    with db.using(user.db_path):
        db.init()
    with _connect() as con:
        con.execute('INSERT INTO users (id, email, name, invited) VALUES (?,?,?,?)', (user.id, user.email, user.name, user.invited))
    return user


def remove(user_id):
    """Takes a friend off the list and deletes their folder: database, Garmin key, Withings connection, uploads."""
    user = get(user_id)
    if not user or user.is_owner:
        return None
    shutil.rmtree(user.folder)  # first, so a failure leaves them on the list rather than their data behind
    with _connect() as con:
        con.execute('DELETE FROM users WHERE id=?', (user.id,))
    return user


def _touch(user):
    now = datetime.now()
    if user.last_seen and now - datetime.fromisoformat(user.last_seen) < timedelta(minutes=5):
        return
    with _connect() as con:
        con.execute('UPDATE users SET last_seen=? WHERE id=?', (now.isoformat(timespec='seconds'), user.id))


_jwks = jwt.PyJWKClient(f'https://{CF_ACCESS_TEAM}/cdn-cgi/access/certs') if CF_ACCESS_TEAM else None


def via_cloudflare(headers):
    return any(h in headers for h in CF_HEADERS)


def access_email(token):
    """The e-mail in a Cloudflare Access token, or '' when it's missing, expired or not from this team."""
    if not _jwks or not token:
        return ''
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=['RS256'], issuer=f'https://{CF_ACCESS_TEAM}',
                            audience=CF_ACCESS_AUD or None, options={'verify_aud': bool(CF_ACCESS_AUD)})
    except jwt.PyJWTError:
        return ''
    return str(claims.get('email', '')).strip().lower()


def from_access(headers, cookies):
    """Who came in through Cloudflare: (user, '') or (None, why they can't come in)."""
    if not CF_ACCESS_TEAM:
        return None, 'Outside access isn’t set up yet: CF_ACCESS_TEAM is missing from the settings.'
    email = access_email(headers.get('cf-access-jwt-assertion') or cookies.get('CF_Authorization'))
    if not email:
        return None, 'Your Cloudflare login couldn’t be checked. Reload the page to sign in again.'
    if email == OWNER_EMAIL:
        return OWNER, ''
    user = by_email(email)
    if not user:
        hint = '' if OWNER_EMAIL else ' (If this is the owner’s address: OWNER_EMAIL isn’t set yet.)'
        return None, f'You’re signed in as {email}, but this dashboard hasn’t been shared with that address.{hint}'
    _touch(user)
    return user, ''
