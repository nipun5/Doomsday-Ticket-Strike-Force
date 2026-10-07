#!/usr/bin/env python3
"""Read the watcher's saved status without contacting ticket sites."""

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")


def display_time(timestamp):
    if not timestamp:
        return "never"
    return datetime.fromtimestamp(timestamp, IST).strftime("%d %b %Y, %I:%M:%S %p IST")


def service_status(name):
    result = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, check=False)
    return result.stdout.strip() or "unknown"


def main():
    state_path = ROOT / "state.json"
    if not state_path.exists():
        raise SystemExit("No state.json yet; the first check has not completed.")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    print("Doomsday Ticket Strike Force — Delhi/NCR")
    print("Watcher:", service_status("doomsday-watch"))
    print("Telegram bot:", service_status("doomsday-telegram"))
    print("Last check completed:", display_time(state.get("last_cycle_completed")))
    started = state.get("last_cycle_started")
    print("Next check due:", display_time(started + 600) if started else "unknown")
    if started and time.time() - started > 1200:
        print("WARNING: Last check is more than 20 minutes old.")
    for site in ("BookMyShow", "District"):
        check = state.get("last_checks", {}).get(site, {})
        print(f"{site}: {check.get('status', 'unknown')} — {check.get('detail', 'no saved result')}")
        print(f"  Checked: {display_time(check.get('checked_at'))}; consecutive errors: {state.get('failures', {}).get(site, 0)}")
    found = state.get("ticket_seen") or any(key.startswith("open:") for key in state.get("delivered", {}))
    print("Confirmed ticket opening:", "YES" if found else "no")
    print("Routine log:", ROOT / "watch.log")


if __name__ == "__main__":
    main()
