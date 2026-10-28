# Command line: python -m app.cli sync | import
import sys

from . import db, imports, jobs


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ''
    db.init()
    if cmd == 'sync':
        jobs.sync_all()
        print('Sync finished. See the Setup page for details.')
    elif cmd == 'import':
        imports.scan()
        print('Import folder scanned.')
    else:
        print('Usage: python -m app.cli sync | import')
        sys.exit(1)


if __name__ == '__main__':
    main()
