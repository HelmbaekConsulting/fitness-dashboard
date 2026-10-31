# Command line: python -m app.cli sync | import (for everyone: you and the friends on the admin page)
import sys

from . import db, jobs, users


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    users.init()
    for user in users.everyone():
        with db.using(user.db_path):
            db.init()
    if cmd == 'sync':
        jobs.sync_all()
        print('Sync finished. See the Setup page for details.')
    elif cmd == 'import':
        jobs.scan_imports()
        print('Import folders scanned.')
    else:
        print('Usage: python -m app.cli sync | import')
        sys.exit(1)


if __name__ == '__main__':
    main()
