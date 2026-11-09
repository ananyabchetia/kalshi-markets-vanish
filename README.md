# Kalshi Quiet-Removal Monitor

Tracks Kalshi's open events over time and flags any event that vanishes from
the open-events list without resolving normally or running out its clock —
a signal it may have been quietly pulled rather than settled.

## How it's structured

```
kalshi_monitor.py             # core logic: pull, save/load snapshots, diff, verify
snapshot_cron.py               # one run = one snapshot + diff + verification, called on a schedule
generate_static_dashboard.py   # renders data/ into a static docs/index.html (Chart.js, no server needed)
app.py                          # optional: a live Streamlit dashboard reading the same data
data/snapshots/                 # one JSON file per snapshot (committed to the repo)
data/alerts/                    # one JSON file per verification run (committed to the repo)
docs/index.html                 # the static dashboard GitHub Pages serves — regenerated every run
.github/workflows/snapshot.yml # GitHub Action: snapshot -> diff/verify -> rebuild docs/index.html -> commit
```

There are two ways to *view* this, pick whichever fits:

- **Static site (recommended, no extra hosting)**: `generate_static_dashboard.py`
  renders the current data into a single self-contained `docs/index.html`
  (charts via Chart.js from a CDN, no build step). The GitHub Action
  regenerates and commits it on every scheduled run, and **GitHub Pages**
  serves it directly — this is the actual `index.html` you were looking for.
- **Live Streamlit app** (`app.py`, optional): a more interactive version
  with filtering/sorting widgets, but it needs a running Python process.
  GitHub itself can't run that for you — you'd host it on
  [Streamlit Community Cloud](https://share.streamlit.io), which deploys
  straight from this repo for free. `docs/index.html` doesn't depend on this
  at all; skip it if you don't want the extra piece.

## 1. Push this to GitHub

```bash
cd kalshi-dashboard
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

## 2. Turn on the scheduled snapshot

The workflow in `.github/workflows/snapshot.yml` is set to run every
5 minutes once it's on GitHub. The dashboard page also reloads every 5 minutes.
GitHub Actions schedules can be delayed during high load. Two things to check:

- **Actions permissions**: in the repo, go to Settings → Actions → General →
  Workflow permissions, and set it to "Read and write permissions" so the
  workflow can commit new data back to the repo.
- You can trigger the very first run manually from the Actions tab
  ("Kalshi snapshot" → Run workflow) instead of waiting for the schedule.
  You'll need at least two snapshots before any diffing/verification shows up.

## 3. Turn on GitHub Pages for the static dashboard

In the repo, go to Settings → Pages → Build and deployment → Source, set it
to "Deploy from a branch", and pick branch `main`, folder `/docs`. Save.
Your dashboard will be live at `https://<you>.github.io/<repo>/` and will
update automatically each time the scheduled Action commits a fresh
`docs/index.html`.

## 3b. (Optional) Deploy the live Streamlit app too

Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub,
and point it at this repo with `app.py` as the entry point. It redeploys
automatically whenever the repo updates.

## Running locally

```bash
pip install -r requirements.txt
python snapshot_cron.py               # take one snapshot (run it twice, a bit apart, to get a diff)
python generate_static_dashboard.py   # build docs/index.html — open it directly in a browser
streamlit run app.py                  # or, run the live version instead
```

## Notes / things you may want to tune

- **Snapshot frequency**: the `cron` line in `snapshot.yml` controls this.
  GitHub's scheduler can drift, so updates may arrive later than five minutes.
- **Data growth**: each snapshot is a full JSON dump of every open event, so
  the repo will grow over time. If that becomes an issue, you could prune
  old snapshots in `snapshot_cron.py` or move older ones to a separate
  branch/archive.
- **Rate limits**: `pull_open_events` paginates through all open events on
  every run — keep an eye on Kalshi's API rate limits if you shorten the
  schedule a lot.
