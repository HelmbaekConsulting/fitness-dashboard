# Fitness Dashboard

A private dashboard for body composition, training, recovery, food and strength. It runs as one Docker container on
Unraid and syncs itself every day.

| Source | How it gets in | What it gives |
|---|---|---|
| Garmin Fenix 6 Pro | Garmin's official Personal API (your own API key), daily | Steps, resting HR, sleep stages and score, overnight HRV, stress, Body Battery, calories burned, intensity minutes, activities with training load. Calories eaten too, if MyFitnessPal syncs to Garmin Connect |
| Withings Body Scan | Withings public API (OAuth), daily | Weight, fat %, fat and muscle mass, water, bone, visceral fat, pulse wave velocity, vascular age, BMR |
| MyFitnessPal / Cronometer | CSV export dropped in the import folder | Calories, protein, carbs, fat, fibre per day |
| Jefit (or Hevy, Strong) | CSV export dropped in the import folder | Sets: exercise, weight, reps |

Pages: Overview, Body, Training, Recovery, Nutrition, Strength, Setup. Every page has a date filter (30 days to all
history, or a custom range).

The Personal API has no VO2 max (its endpoint answers "not found"), so the dashboard doesn't show it.

## Set up

### 1. Withings developer app (5 minutes)

1. Sign in at <https://developer.withings.com/dashboard/> with your Withings account and create an application:
   **Public API integration**, any name, and as callback URL the address you'll open the dashboard on plus
   `/withings/callback`, for example `http://192.168.1.20:8080/withings/callback`.
2. Copy the client ID and secret into `.env` (`WITHINGS_CLIENT_ID`, `WITHINGS_CLIENT_SECRET`) and set
   `WITHINGS_REDIRECT_URI` to the same callback URL.

### 2. Image

Pushing this repository to GitHub builds the image `ghcr.io/<you>/fitness-dashboard:latest`
(`.github/workflows/docker.yml`). Make the package public on GitHub, or log Unraid in to ghcr.io. You can also build it on
the server: in `docker-compose.yml`, replace `image:` with `build: .`.

### 3. Run it on Unraid

With the **Compose Manager** plugin: add a stack, paste `docker-compose.yml`, put your `.env` next to it, start.
Data lives in `/mnt/user/appdata/fitness-dashboard`; the import folder is the share `/mnt/user/fitness-import`.

Without Compose: Docker tab → Add Container, repository `ghcr.io/<you>/fitness-dashboard:latest`, port 8080, paths
`/data` → `/mnt/user/appdata/fitness-dashboard` and `/import` → `/mnt/user/fitness-import`, and the variables from
`.env.example`.

### 4. Connect

1. **Garmin:** in Garmin Connect, create a personal API key (account settings → Personal API) with the longest expiry
   and set it as `GARMIN_API_KEY`. It's shown only once. When it expires, create a new one and replace it.
2. **Withings:** open the dashboard, go to Setup, press **Connect Withings** and allow access.
3. Press **Sync now**. The first run takes the last few days plus 120 days of Garmin history (about 6 minutes, one call
   per second, because Garmin publishes no rate limit). Each night it reaches another 120 days back until `HISTORY_START`.
   Withings history and all Garmin activities come in on the first run.

### 5. Food and strength exports

- **Food:** in MyFitnessPal, connect Garmin Connect (Settings → Sharing & Privacy → Connected apps) for calories with
  no effort. For macros: MyFitnessPal Premium → Reports → Export, or Cronometer → Settings → Export data → Daily
  nutrition.
- **Jefit:** export your workout log as CSV from the Jefit web app.
- Save the files to the `fitness-import` share. They're imported within 15 minutes and moved to `done/` (or `failed/`
  with an `.error.txt` saying why). Exporting an overlapping range again is fine: days are replaced, not doubled.

The importer recognises files by their column names. If a Jefit file lands in `failed/`, the error lists its columns
so the importer can be taught that format.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m uvicorn app.main:app --port 8080
```

Data goes to `data/` (git-ignored). `python -m app.cli sync` runs a sync from the command line.

## How the numbers are made

- **7-day averages** use the last seven calendar days, so missing days don't stretch the window.
- **Fitness and fatigue** are 42- and 7-day exponentially weighted averages of Garmin's training load per activity
  (the CTL/ATL model). **Form** is fitness minus fatigue.
- **Estimated 1RM** uses the Epley formula, weight × (1 + reps / 30), on sets of 12 reps or fewer. Warm-up sets are
  skipped when the export marks them.
- When both a food export and the Garmin calorie sync have a day, the export wins.
