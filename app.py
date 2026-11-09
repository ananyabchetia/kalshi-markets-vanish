"""
Streamlit dashboard for the Kalshi quiet-removal monitor.

Reads the snapshot/alert history written by snapshot_cron.py (normally
committed to the repo by a scheduled GitHub Action) and displays it.

Run locally with:  streamlit run app.py
"""

import pandas as pd
import streamlit as st

from kalshi_monitor import load_alerts, load_snapshots

st.set_page_config(page_title="Kalshi Quiet-Removal Monitor", layout="wide")
st.title("Kalshi Quiet-Removal Monitor")
st.caption(
    "Tracks Kalshi's open events over time and flags events that vanish "
    "from the open list without resolving or running out the clock."
)

snapshots = load_snapshots()
alerts = load_alerts()
alerts = alerts[alerts["classification"].isin(["quiet_removal_suspected", "unclear", "early_settlement"])] if len(alerts) else alerts

if not snapshots:
    st.warning(
        "No snapshots found yet. Run `python snapshot_cron.py` locally, or "
        "wait for the scheduled GitHub Action to create the first one."
    )
    st.stop()

# --- Overview metrics ---
counts = pd.DataFrame(
    [{"snapshot_time": ts, "open_events": len(df)} for ts, df in snapshots.items()]
)

col1, col2, col3 = st.columns(3)
col1.metric("Snapshots collected", len(snapshots))
col2.metric("Latest open-event count", int(counts["open_events"].iloc[-1]))
suspected_total = (
    int((alerts["classification"] == "quiet_removal_suspected").sum()) if len(alerts) else 0
)
col3.metric("Quiet removals suspected (all time)", suspected_total)

st.subheader("Open events over time")
st.line_chart(counts.set_index("snapshot_time")["open_events"])

# --- Vanished-event checks ---
st.subheader("Vanished-event checks")
if len(alerts):
    display_cols = [
        "checked_at",
        "event_ticker",
        "title",
        "category",
        "classification",
        "still_had_time_left",
        "http_status",
    ]
    display_cols = [c for c in display_cols if c in alerts.columns]

    classes = ["All"] + sorted(alerts["classification"].dropna().unique().tolist())
    choice = st.selectbox("Filter by classification", classes)
    view = alerts if choice == "All" else alerts[alerts["classification"] == choice]

    st.dataframe(
        view[display_cols].sort_values("checked_at", ascending=False),
        use_container_width=True,
    )

    suspects = alerts[alerts["classification"] == "quiet_removal_suspected"]
    if len(suspects):
        st.error(
            f"{len(suspects)} event(s) flagged as suspected quiet removals across all checks."
        )
else:
    st.info("No vanished-event checks yet — need at least two snapshots to diff.")

# --- Raw snapshot browser ---
with st.expander("Browse a raw snapshot"):
    ts_choice = st.selectbox("Snapshot", sorted(snapshots.keys(), reverse=True))
    st.dataframe(snapshots[ts_choice], use_container_width=True)
