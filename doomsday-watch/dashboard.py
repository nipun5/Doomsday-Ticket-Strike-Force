#!/usr/bin/env python3
"""Private dashboard: serves the watcher's saved state; never contacts ticket sites.

Listens on localhost only. Caddy provides HTTPS and login in front of it.
"""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_PATH = ROOT / "state.json"
PAGE = (ROOT / "dashboard.html").read_bytes()
SITES = ("BookMyShow", "District")
INTERVAL = 600


def summary(state: dict) -> dict:
    """Pick display fields only; delivery records hold Telegram chat IDs."""
    started = state.get("last_cycle_started")
    checks = state.get("last_checks", {})
    return {
        "last_cycle_completed": state.get("last_cycle_completed"),
        "next_check_due": started + INTERVAL if started else None,
        "ticket_seen": bool(state.get("ticket_seen")) or any(
            event.startswith("open:") for event in state.get("delivered", {})
        ),
        "sites": {
            site: {
                "status": checks.get(site, {}).get("status", "unknown"),
                "detail": checks.get(site, {}).get("detail", "no saved result"),
                "checked_at": checks.get(site, {}).get("checked_at"),
                "errors": state.get("failures", {}).get(site, 0),
            }
            for site in SITES
        },
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self.reply(200, "text/html; charset=utf-8", PAGE)
        elif self.path == "/api/status":
            try:
                body = summary(json.loads(STATE_PATH.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                body = {"error": "Watcher state is not available yet"}
            self.reply(200, "application/json", json.dumps(body).encode())
        else:
            self.reply(404, "text/plain", b"Not found")

    def reply(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_) -> None:
        pass  # Caddy already logs requests; keep the journal quiet.


if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", "8090"))
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
