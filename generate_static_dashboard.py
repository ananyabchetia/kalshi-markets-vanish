"""
Builds a self-contained docs/index.html from the saved snapshot/alert data,
so the dashboard can be served as a plain static site via GitHub Pages
(no Streamlit process required).

Charts and tables are rendered client-side with Chart.js (loaded from a
CDN); the underlying data is embedded directly in the page as JSON.

Run this after snapshot_cron.py, or let the GitHub Action run both.
"""

import json
from pathlib import Path

import pandas as pd

from kalshi_monitor import load_alerts, load_snapshots

DOCS_DIR = Path(__file__).parent / "docs"

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Kalshi Quiet-Removal Monitor</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 2rem;
          background: #0f1117; color: #e6e6e6; }}
  h1 {{ margin-bottom: 0.2rem; }}
  .sub {{ color: #9aa0a6; margin-top: 0; margin-bottom: 2rem; }}
  .metrics {{ display: flex; gap: 1rem; margin-bottom: 2rem; flex-wrap: wrap; }}
  .metric {{ background: #1a1d27; border-radius: 10px; padding: 1rem 1.5rem; min-width: 160px; }}
  .metric .value {{ font-size: 1.8rem; font-weight: 600; }}
  .metric .label {{ color: #9aa0a6; font-size: 0.85rem; }}
  .card {{ background: #1a1d27; border-radius: 10px; padding: 1.5rem; margin-bottom: 2rem; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
  th, td {{ text-align: left; padding: 0.5rem 0.7rem; border-bottom: 1px solid #2a2e3a; }}
  th {{ color: #9aa0a6; font-weight: 500; }}
  select {{ background: #0f1117; color: #e6e6e6; border: 1px solid #2a2e3a; border-radius: 6px;
            padding: 0.4rem; margin-bottom: 1rem; }}
  .badge {{ padding: 0.15rem 0.5rem; border-radius: 6px; font-size: 0.8rem; }}
  .quiet_removal_suspected {{ background: #4a1f24; color: #ff8a8a; }}
  .early_settlement {{ background: #3a3320; color: #ffd479; }}
  .normal_close {{ background: #1f3a26; color: #7ee08a; }}
  .unclear, .lookup_error {{ background: #2a2e3a; color: #b0b6c0; }}
  .empty {{ color: #9aa0a6; font-style: italic; }}
  .generated {{ color: #6b7280; font-size: 0.8rem; margin-top: 2rem; }}
</style>
</head>
<body>
  <h1>Kalshi Quiet-Removal Monitor</h1>
  <p class="sub">Tracks Kalshi's open events over time and flags events that vanish from the
     open list without resolving normally or running out the clock.</p>

  <div class="metrics">
    <div class="metric"><div class="value">{n_snapshots}</div><div class="label">Snapshots collected</div></div>
    <div class="metric"><div class="value">{latest_count}</div><div class="label">Latest open-event count</div></div>
    <div class="metric"><div class="value">{n_suspected}</div><div class="label">Quiet removals suspected (all time)</div></div>
  </div>

  <div class="card">
    <h3>Open events over time</h3>
    <canvas id="eventsChart" height="90"></canvas>
  </div>

  <div class="card">
    <h3>Vanished-event checks</h3>
    <div id="alertsTableWrap">{alerts_table_html}</div>
  </div>

  <p class="generated">Generated {generated_at} UTC · This page refreshes every 5 minutes.</p>

<script>
const countsData = {counts_json};
const ctx = document.getElementById('eventsChart').getContext('2d');
new Chart(ctx, {{
  type: 'line',
  data: {{
    labels: countsData.map(d => d.snapshot_time),
    datasets: [{{
      label: 'Open events',
      data: countsData.map(d => d.open_events),
      borderColor: '#7ee08a',
      backgroundColor: 'rgba(126,224,138,0.15)',
      tension: 0.2,
      fill: true,
    }}]
  }},
  options: {{
    scales: {{
      x: {{ ticks: {{ color: '#9aa0a6' }}, grid: {{ color: '#2a2e3a' }} }},
      y: {{ ticks: {{ color: '#9aa0a6' }}, grid: {{ color: '#2a2e3a' }}, beginAtZero: true }}
    }},
    plugins: {{ legend: {{ labels: {{ color: '#e6e6e6' }} }} }}
  }}
}});
</script>
</body>
</html>
"""


def _alerts_table_html(alerts: pd.DataFrame) -> str:
    if alerts is None or not len(alerts):
        return '<p class="empty">No vanished-event checks yet — need at least two snapshots to diff.</p>'

    relevant = alerts[alerts["classification"].isin(["quiet_removal_suspected", "unclear", "early_settlement"])]
    if relevant.empty:
        return '<p class="empty">No quiet-removal alerts to display.</p>'

    cols = [
        "checked_at",
        "event_ticker",
        "title",
        "category",
        "classification",
        "still_had_time_left",
        "http_status",
    ]
    cols = [c for c in cols if c in relevant.columns]
    view = relevant[cols].sort_values("checked_at", ascending=False)

    header = "".join(f"<th>{c}</th>" for c in cols)
    rows = []
    for _, r in view.iterrows():
        cells = []
        for c in cols:
            val = r[c]
            if c == "classification":
                cells.append(f'<td><span class="badge {val}">{val}</span></td>')
            else:
                cells.append(f"<td>{val}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")

    return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def build_dashboard() -> Path:
    snapshots = load_snapshots()
    alerts = load_alerts()
    if len(alerts):
        alerts = alerts[alerts["classification"].isin(["quiet_removal_suspected", "unclear", "early_settlement"])].copy()

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DIR / "index.html"

    if not snapshots:
        out_path.write_text(
            "<html><body style='font-family:sans-serif;padding:2rem'>"
            "<h1>Kalshi Quiet-Removal Monitor</h1>"
            "<p>No snapshots yet — waiting for the first scheduled run.</p>"
            "</body></html>"
        )
        return out_path

    counts = [
        {"snapshot_time": pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M"), "open_events": len(df)}
        for ts, df in snapshots.items()
    ]
    latest_count = counts[-1]["open_events"]
    n_suspected = int((alerts["classification"] == "quiet_removal_suspected").sum()) if len(alerts) else 0

    html = PAGE_TEMPLATE.format(
        n_snapshots=len(snapshots),
        latest_count=latest_count,
        n_suspected=n_suspected,
        alerts_table_html=_alerts_table_html(alerts),
        counts_json=json.dumps(counts),
        generated_at=pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M"),
    )
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    path = build_dashboard()
    print(f"Wrote static dashboard: {path}")
