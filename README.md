# Fitness Dashboard

A private dashboard for body composition, training, recovery, food and strength. It runs as one Docker container on
Unraid and syncs itself every day.

| Source | How it gets in | What it gives |
|---|---|---|
| Garmin Fenix 6 Pro | Garmin's official Personal API (your own API key), daily | Steps, resting HR, sleep stages and score, overnight HRV, stress, Body Battery, calories burned, intensity minutes, activities with training load. Calories eaten too, if MyFitnessPal syncs to Garmin Connect |
| Withings Body Scan | Withings public API (OAuth), daily | Weight, fat %, fat and muscle mass, water, bone, visceral fat, pulse wave velocity, vascular age, BMR |
| MyFitnessPal / Cronometer | CSV export dropped in the import folder | Calories, protein, carbs, fat, fibre per day |
| Jefit (or Hevy, Strong) | CSV export dropped in the import folder | Sets: exercise, weight, reps |

Pages (every one with a date filter, 30 days to all history or a custom range):

- **Today:** readiness ring, trend weight with what the change was made of (fat, muscle, the rest), sleep, HRV,
  resting HR and steps with 30-day or 8-week sparklines, the latest sessions, things worth knowing, energy balance.
- **Body:** Body Scan segments (arms, legs, trunk) on a body figure, muscle or fat, change and left/right balance.
- **Muscles:** sets per week per muscle on a front and back figure, or days since each muscle was trained.
- **Training vs body:** training and Body Scan muscle side by side, with a month slider to play the change.
- **Training:** calendar, time in heart-rate zones, fitness and fatigue. **Recovery:** HRV against your normal
  range, sleep, resting HR. **Nutrition:** measured vs Garmin maintenance, macros. **Strength:** lifts, records,
  sessions with calories per exercise.

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
- **Jefit:** export your data from Jefit (one CSV with all sections: settings, profile, routines, logs). The importer
  reads its EXERCISE LOGS section, in the weight unit set in Jefit. Importing a newer export again replaces the old sets.
- Upload the files on the Setup page (imported straight away), or save them to the `fitness-import` share. Files in
  the share are imported within 15 minutes and moved to `done/` (or `failed/`
  with an `.error.txt` saying why). Exporting an overlapping range again is fine: days are replaced, not doubled.

The importer recognises files by their column names. If a Jefit file lands in `failed/`, the error lists its columns
so the importer can be taught that format.

### 6. Open it from outside (optional)

The `tunnel` service in `docker-compose.yml` runs a Cloudflare Tunnel: it connects out to Cloudflare, so no router
ports are opened. Cloudflare Access sits in front and only lets in the e-mail addresses you list; the dashboard reads
who's logged in from Access, so set up Access first.

1. **Access** (Cloudflare Zero Trust, free plan): Access controls → Applications → Self-hosted, hostname for example
   `fitness.example.com`, with an Allow policy for your e-mail addresses. Integrations → Identity providers: add
   One-time PIN, so a code by e-mail is enough to log in.
2. **Tunnel:** Networking → Tunnels → Create tunnel (cloudflared). Add a published application route from the same
   hostname to `http://fitness-dashboard:8080`; Cloudflare creates the DNS record.
3. Copy the tunnel token (the long text after `--token` in the Docker command) into `.env` as
   `CLOUDFLARE_TUNNEL_TOKEN`. Also set `CF_ACCESS_TEAM` (your team name, the first part of
   `<team>.cloudflareaccess.com`), `CF_ACCESS_AUD` (the Access application's Application Audience (AUD) Tag),
   `OWNER_EMAIL` (the address you log in with) and `PUBLIC_URL` (`https://fitness.example.com`). Then Compose Up. The
   tunnel shows Healthy in Cloudflare once it's connected. Requests through it without a valid Access login are refused.
4. **Withings** (only to press Connect Withings from outside; an existing connection keeps working): add
   `https://fitness.example.com/withings/callback` to the callback URLs of your Withings app and set it as
   `WITHINGS_REDIRECT_URI`.

### 7. Share it with friends (optional)

On the **People** page (only yours, under Setup in the menu), invite a friend by name and e-mail. They get a dashboard
of their own: their own database, Garmin key, Withings connection and uploads, in `/data/users/`. Nothing of yours is
shared, and the People page only shows whether their sync works. Then:

1. Add their e-mail to the Allow policy of the Access application.
2. Send them the message the page shows. They log in with a code by e-mail, paste their own Garmin personal API key on
   Setup and press Connect Withings, which needs `https://fitness.example.com/withings/callback` in your Withings app
   (step 6.4).

Removing someone deletes their folder; take their address off the policy as well. At home, without Cloudflare in
between, the dashboard is always yours.

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
- **Sets per muscle:** each exercise is matched to muscles by name (`app/muscles.py`); a set counts 1 for the main
  muscles and ½ for the helpers. The figures colour sets per week against the common 10–20 sets guideline.
- **Body Scan segments** come from Withings measure types 173–175 with a body position. The Setup page lists the
  types and positions received, to check the mapping.
- **Trend weight** smooths weigh-ins by 10% a day (The Hacker's Diet). **Measured maintenance** is average calories
  eaten minus 7,700 kcal per kg of trend weight change over 28 days, with at least 18 days logged.
- **Recovery check:** HRV 7-day average against your 60-day average ± one standard deviation, resting HR of the last
  3 days against your 30-day average, sleep of the last 3 nights, and fatigue ÷ fitness.
- **Calories per workout** come from the Garmin activity overlapping the Jefit session. Without one they're estimated
  as 3.5 MET × body weight × session time. Each exercise gets a share by its number of sets.
- **What the weight change was made of:** the first and latest Body Scan in the range that have weight, fat mass and
  muscle mass; "the rest" is weight minus fat and muscle (water outside muscle, bone).
- **Trips** on the Today weight chart: 3 or more days with activities only at places other than your usual ones
  (Garmin location names seen in at least 3 different months).
- **Worth knowing** lists only what holds: two weeks under 7 h sleep, a new estimated 1RM in the last 14 days, legs
  under a third of the upper body's sets, more than a quarter of a weight loss being muscle, strength sessions
  without a watch recording.
