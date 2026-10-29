# Fitness Dashboard

Personal health and fitness dashboard: FastAPI + Jinja + Chart.js, SQLite, one Docker container on Unraid. See
`README.md` for setup and sources.

- `app/garmin.py`, `app/withings.py`: daily sync; raw responses go to the `raw` table, extracted values to `metrics`
  (one value per day and metric). Re-extract from `raw` rather than calling the APIs again.
- `app/imports.py`: CSV watch folder (food and strength exports), recognised by column names.
- `app/queries.py`: basic reads. `app/insights.py`: derived numbers (sets per muscle, segments, workouts with Garmin
  calories, records, HR zones, trend weight, maintenance, readiness). `app/main.py`: pages; each chart is a spec
  rendered by `static/charts.js`.
- `app/figure.py`: the SVG body figure (front/back, one shape per muscle, tagged with its Withings segment);
  `app/muscles.py`: exercise name → muscles. `static/timeline.js` plays the month frames on "Training vs body".
- Jefit backups replace all earlier Jefit sets (`source = 'jefit'`); exercises are grouped by Jefit's exercise id.
- Garmin uses the official Personal API (`personal.connectapi.garmin.com`, key → 24-hour bearer token). It has no
  published rate limit: keep `PAUSE` between calls and never loop live calls while testing. Never print the key or token.
- Never commit `.env` or `data/`. Test against a throwaway `DATA_DIR`, not the real database.
- Charts: one y-axis per chart, series colours in the fixed `--s1`…`--s8` order from `static/app.css`, dates shown
  dd/mm/yyyy.
- Run locally: `.venv\Scripts\python -m uvicorn app.main:app --port 8080`. Check pages at desktop and 375 px width.
