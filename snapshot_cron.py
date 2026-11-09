"""
Run this on a schedule (e.g. via GitHub Actions) to:
  1. pull the current open events from Kalshi
  2. save that as a new snapshot
  3. diff it against the previous snapshot
  4. verify any vanished events and save the result for the dashboard

Designed to be idempotent and cheap so it can run every N minutes.
"""

from kalshi_monitor import (
    diff_latest_two,
    load_snapshots,
    pull_open_events,
    save_alert,
    save_snapshot,
    verify_vanished,
)


def main():
    df = pull_open_events()
    path = save_snapshot(df)
    print(f"Saved snapshot: {path} ({len(df)} open events)")

    snapshots = load_snapshots()
    prev_ts, curr_ts, vanished_df = diff_latest_two(snapshots)

    if vanished_df is None:
        print("Not enough snapshots yet to diff.")
        return

    print(f"{prev_ts} -> {curr_ts}: {len(vanished_df)} events vanished")

    if len(vanished_df):
        verification = verify_vanished(vanished_df)
        alert_path = save_alert(verification, curr_ts)
        suspected = int((verification["classification"] == "quiet_removal_suspected").sum())
        print(f"Saved verification: {alert_path} ({suspected} quiet removals suspected)")
    else:
        print("No vanished events this run.")


if __name__ == "__main__":
    main()
