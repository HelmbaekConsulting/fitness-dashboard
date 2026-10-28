# Command line: python -m app.cli garmin-login | sync | import
import sys

from . import db, garmin, imports, jobs


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    db.init()
    if cmd == 'garmin-login':
        name = garmin.login_interactive()
        print(f'Logged in as {name}. Tokens saved; the daily sync will use them.')
    elif cmd == 'sync':
        jobs.sync_all()
        print('Sync finished. See the Setup page for details.')
    elif cmd == 'import':
        imports.scan()
        print('Import folder scanned.')
    else:
        print('Usage: python -m app.cli garmin-login | sync | import')
        sys.exit(1)


if __name__ == '__main__':
    main()
