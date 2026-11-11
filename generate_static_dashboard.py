"""
Builds a self-contained docs/index.html from the saved snapshot/alert data,
so the dashboard can be served as a plain static site via GitHub Pages
(no Streamlit process required).

The alert history is rendered client-side; the underlying data is embedded
directly in the page as JSON.

Run this after snapshot_cron.py, or let the GitHub Action run both.
"""

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
  input[type="search"], button {{ background: #0f1117; color: #e6e6e6; border: 1px solid #2a2e3a;
            border-radius: 6px; padding: 0.55rem 0.7rem; }}
  input[type="search"] {{ box-sizing: border-box; margin: 0 0 1rem; width: min(100%, 32rem); }}
  button {{ cursor: pointer; }}
  button:disabled {{ cursor: default; opacity: 0.45; }}
  .alerts-pagination {{ align-items: center; display: flex; justify-content: space-between;
            gap: 1rem; margin-top: 1rem; }}
  .alerts-pagination button + button {{ margin-left: 0.5rem; }}
  .alerts-page-info {{ color: #9aa0a6; font-size: 0.9rem; }}
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
    <h3>Vanished-event checks</h3>
    <label for="alertsSearch">Search vanished events</label><br>
    <input id="alertsSearch" type="search" placeholder="Search ticker, title, category, or check time">
    <div id="alertsTableWrap"></div>
    <div class="alerts-pagination" aria-label="Vanished-event pages">
      <span id="alertsPageInfo" class="alerts-page-info" aria-live="polite"></span>
      <div>
        <button id="alertsNewer" type="button" aria-label="Show newer vanished events">← Newer</button>
        <button id="alertsOlder" type="button" aria-label="Show older vanished events">Older →</button>
      </div>
    </div>
  </div>

  <p class="generated">Generated {generated_at} UTC · This page refreshes every 5 minutes.</p>

<script>
const alertsData = {alerts_json};
const ALERTS_PAGE_SIZE = 10;
let alertsPage = 0;
const alertsSearch = document.getElementById('alertsSearch');
const alertsTableWrap = document.getElementById('alertsTableWrap');
const alertsPageInfo = document.getElementById('alertsPageInfo');
const alertsNewer = document.getElementById('alertsNewer');
const alertsOlder = document.getElementById('alertsOlder');

function renderAlerts() {{
  const query = alertsSearch.value.trim().toLocaleLowerCase();
  const filteredAlerts = alertsData.filter(alert =>
    Object.values(alert).some(value => String(value ?? '').toLocaleLowerCase().includes(query))
  );
  const pageCount = Math.ceil(filteredAlerts.length / ALERTS_PAGE_SIZE);
  alertsPage = Math.min(alertsPage, Math.max(pageCount - 1, 0));
  const start = alertsPage * ALERTS_PAGE_SIZE;
  const pageAlerts = filteredAlerts.slice(start, start + ALERTS_PAGE_SIZE);

  if (!filteredAlerts.length) {{
    alertsTableWrap.innerHTML = '<p class="empty">' +
      (alertsData.length ? 'No vanished events match your search.' : 'No vanished-event checks yet — need at least two snapshots to diff.') +
      '</p>';
  }} else {{
    const table = document.createElement('table');
    const columns = Object.keys(alertsData[0]);
    const thead = table.createTHead();
    const headerRow = thead.insertRow();
    columns.forEach(column => {{
      const th = document.createElement('th');
      th.textContent = column;
      headerRow.appendChild(th);
    }});

    const tbody = table.createTBody();
    pageAlerts.forEach(alert => {{
      const row = tbody.insertRow();
      columns.forEach(column => {{
        const cell = row.insertCell();
        const value = alert[column];
        if (column === 'classification' && value) {{
          const badge = document.createElement('span');
          badge.className = 'badge ' + value;
          badge.textContent = value;
          cell.appendChild(badge);
        }} else {{
          cell.textContent = value == null ? '' : String(value);
        }}
      }});
    }});
    alertsTableWrap.replaceChildren(table);
  }}

  const firstResult = filteredAlerts.length ? start + 1 : 0;
  const lastResult = Math.min(start + ALERTS_PAGE_SIZE, filteredAlerts.length);
  alertsPageInfo.textContent = 'Showing ' + firstResult + '–' + lastResult +
    ' of ' + filteredAlerts.length + ' matching events (' + alertsData.length + ' total)';
  alertsNewer.disabled = alertsPage === 0;
  alertsOlder.disabled = alertsPage >= pageCount - 1;
}}

alertsSearch.addEventListener('input', () => {{
  alertsPage = 0;
  renderAlerts();
}});
alertsNewer.addEventListener('click', () => {{
  if (alertsPage > 0) {{
    alertsPage -= 1;
    renderAlerts();
  }}
}});
alertsOlder.addEventListener('click', () => {{
  alertsPage += 1;
  renderAlerts();
}});
renderAlerts();
</script>
</body>
</html>
"""


def _alerts_json(alerts: pd.DataFrame) -> str:
    if alerts is None or not len(alerts):
        return "[]"

    relevant = alerts[alerts["classification"].isin(["quiet_removal_suspected", "unclear", "early_settlement"])]
    if relevant.empty:
        return "[]"

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
    return (
        view.to_json(orient="records", date_format="iso")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


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
        alerts_json=_alerts_json(alerts),
        generated_at=pd.Timestamp.now("UTC").strftime("%Y-%m-%d %H:%M"),
    )
    out_path.write_text(html)
    return out_path


if __name__ == "__main__":
    path = build_dashboard()
    print(f"Wrote static dashboard: {path}")
