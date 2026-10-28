# Fitness Dashboard

Personal health and fitness dashboard: FastAPI + Jinja + Chart.js, SQLite, one Docker container on Unraid. See
`README.md` for setup and sources.

- `app/garmin.py`, `app/withings.py`: daily sync; raw responses go to the `raw` table, extracted values to `metrics`
  (one value per day and metric). Re-extract from `raw` rather than calling the APIs again.
- `app/imports.py`: CSV watch folder (food and strength exports), recognised by column names.
- `app/queries.py`: everything the pages read. `app/main.py`: pages; each chart is a spec rendered by `static/charts.js`.
- Garmin uses the official Personal API (`personal.connectapi.garmin.com`, key → 24-hour bearer token). It has no
  published rate limit: keep `PAUSE` between calls and never loop live calls while testing. Never print the key or token.
- Never commit `.env` or `data/`. Test against a throwaway `DATA_DIR`, not the real database.
- Charts: one y-axis per chart, series colours in the fixed `--s1`…`--s8` order from `static/app.css`, dates shown
  dd/mm/yyyy.
- Run locally: `.venv\Scripts\python -m uvicorn app.main:app --port 8080`. Check pages at desktop and 375 px width.
