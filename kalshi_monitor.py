"""
Core logic for the Kalshi "quiet removal" monitor.

Pulls the current set of open Kalshi events, saves timestamped
snapshots to disk, and diffs consecutive snapshots to flag events
that disappeared from the open-events list without resolving or
running out the clock -- a signal that they may have been quietly
pulled rather than settled normally.
"""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
EXCLUDED_CATEGORIES = {"Sports"}
RELEVANT_ALERT_CLASSIFICATIONS = {
    "quiet_removal_suspected",
    "unclear",
    "early_settlement",
}

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
ALERTS_DIR = DATA_DIR / "alerts"


def filter_relevant_alerts(df: pd.DataFrame) -> pd.DataFrame:
    """Only keep the alert types relevant to quiet-removal tracking."""
    if df is None or df.empty:
        return df
    if "classification" not in df.columns:
        return df
    return df[df["classification"].isin(RELEVANT_ALERT_CLASSIFICATIONS)]


def filter_out_excluded_categories(df: pd.DataFrame) -> pd.DataFrame:
    """Remove unwanted categories from the data used for reporting."""
    if df is None or df.empty:
        return df
    if "category" not in df.columns:
        return df
    return df[~df["category"].fillna("").astype(str).isin(EXCLUDED_CATEGORIES)]


def pull_open_events() -> pd.DataFrame:
    """Fetch every open event from Kalshi, one row per event."""
    all_events = []
    cursor = None
    while True:
        params = {"status": "open", "limit": 200, "with_nested_markets": "true"}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{BASE}/events", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        all_events.extend(data["events"])
        cursor = data.get("cursor")
        if not cursor:
            break

    rows = []
    for event in all_events:
        # take everything the API gives us for this event, not a hand-picked subset
        row = dict(event)
        markets = row.pop("markets", [])
        row["market_count"] = len(markets)
        row["market_tickers"] = [m.get("ticker") for m in markets]

        close_times = [m.get("close_time") for m in markets if m.get("close_time")]
        row["min_market_close_time"] = min(close_times) if close_times else None
        row["max_market_close_time"] = max(close_times) if close_times else None

        row["market_results"] = [m.get("result") for m in markets]
        row["can_close_early"] = any(m.get("can_close_early") for m in markets)

        rows.append(row)

    df = pd.DataFrame(rows)
    df = filter_out_excluded_categories(df)
    df["snapshot_time"] = datetime.now(timezone.utc)
    return df


def save_snapshot(df: pd.DataFrame) -> Path:
    """Write a snapshot to disk as JSON, named by its timestamp."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = df["snapshot_time"].iloc[0]
    ts_str = pd.Timestamp(ts).strftime("%Y%m%dT%H%M%SZ")
    path = SNAPSHOT_DIR / f"{ts_str}.json"
    df.to_json(path, orient="records", date_format="iso")
    return path


def load_snapshots() -> dict:
    """Load all saved snapshots into {timestamp: DataFrame}, oldest first."""
    snapshots = {}
    if not SNAPSHOT_DIR.exists():
        return snapshots
    for path in sorted(SNAPSHOT_DIR.glob("*.json")):
        df = pd.read_json(path, orient="records", convert_dates=["snapshot_time"])
        if len(df):
            df = filter_out_excluded_categories(df)
            if len(df):
                ts = df["snapshot_time"].iloc[0]
                snapshots[ts] = df
    return dict(sorted(snapshots.items()))


def diff_latest_two(snapshots: dict):
    """Compare the two most recent snapshots and flag events that vanished."""
    ts_sorted = sorted(snapshots.keys())
    if len(ts_sorted) < 2:
        return None, None, None

    prev_ts, curr_ts = ts_sorted[-2], ts_sorted[-1]
    prev_df, curr_df = snapshots[prev_ts], snapshots[curr_ts]

    prev_events = set(prev_df["event_ticker"])
    curr_events = set(curr_df["event_ticker"])
    vanished = prev_events - curr_events

    vanished_df = prev_df[prev_df["event_ticker"].isin(vanished)].copy()

    vanished_df["max_market_close_time"] = pd.to_datetime(
        vanished_df["max_market_close_time"], utc=True
    )
    now = pd.Timestamp.now(tz="UTC")
    vanished_df["still_had_time_left"] = vanished_df["max_market_close_time"] > now

    vanished_df["all_resolved"] = vanished_df["market_results"].apply(
        lambda results: all(r is not None for r in results) if results else False
    )
    vanished_df["looks_removed"] = (~vanished_df["all_resolved"]) & vanished_df["still_had_time_left"]

    return prev_ts, curr_ts, vanished_df


def verify_vanished(vanished_df: pd.DataFrame) -> pd.DataFrame:
    """Re-check each vanished event directly against the API to classify it."""
    results = []
    for _, row in vanished_df.iterrows():
        r = requests.get(
            f"{BASE}/events/{row['event_ticker']}",
            params={"with_nested_markets": "true"},
            timeout=30,
        )

        if r.status_code == 200:
            e = r.json().get("event", {})
            markets = e.get("markets", [])
            statuses = [m.get("status") for m in markets]
            live_results = [m.get("result") for m in markets]
            all_resolved_now = all(res is not None for res in live_results) if live_results else False

            if row["still_had_time_left"] and not all_resolved_now:
                classification = "quiet_removal_suspected"
            elif all_resolved_now:
                classification = "early_settlement" if row["still_had_time_left"] else "normal_close"
            else:
                classification = "unclear"

        elif r.status_code == 404:
            classification = "quiet_removal_suspected"
            statuses = None

        else:
            classification = "lookup_error"
            statuses = None

        results.append({
            "event_ticker": row["event_ticker"],
            "title": row["title"],
            "category": row.get("category"),
            "max_market_close_time": row["max_market_close_time"],
            "still_had_time_left": row["still_had_time_left"],
            "http_status": r.status_code,
            "market_status_now": statuses,
            "classification": classification,
        })
    return pd.DataFrame(results)


def save_alert(verification_df: pd.DataFrame, curr_ts) -> Path:
    """Persist a verification run so the dashboard can show history."""
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    ts_str = pd.Timestamp(curr_ts).strftime("%Y%m%dT%H%M%SZ")
    path = ALERTS_DIR / f"{ts_str}.json"
    verification_df.to_json(path, orient="records", date_format="iso")
    return path


def load_alerts() -> pd.DataFrame:
    """Load every saved verification run into one combined DataFrame."""
    if not ALERTS_DIR.exists():
        return pd.DataFrame()
    frames = []
    for path in sorted(ALERTS_DIR.glob("*.json")):
        df = pd.read_json(path, orient="records", convert_dates=["max_market_close_time"])
        if len(df):
            df = filter_out_excluded_categories(df)
            df = filter_relevant_alerts(df)
            if len(df):
                df["checked_at"] = path.stem
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
