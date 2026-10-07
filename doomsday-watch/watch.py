#!/usr/bin/env python3
"""Ten-minute, two-site Avengers: Doomsday ticket monitor for Delhi/NCR.

Only a verified BookMyShow show or District's populated booking data triggers an
alert. Failed fetches and changed page formats are errors, never "no tickets".
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import smtplib
import sys
import time
from dataclasses import dataclass
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests
from curl_cffi import requests as browser_requests
from dotenv import load_dotenv
from telegram_subscriptions import load as load_telegram_subscribers, path_from_env as subscriber_path

load_dotenv(Path(__file__).with_name(".env"))


BMS_URL = (
    "https://in.bookmyshow.com/movies/national-capital-region-ncr/"
    "avengers-doomsday/buytickets/ET00439706/"
)
DISTRICT_URL = (
    "https://www.district.in/movies/"
    "avengers-doomsday-movie-tickets-in-delhi-ncr-MV176735"
)
PROBE_DATE = "20991231"
DEFAULT_INTERVAL = 600
LOG = logging.getLogger("doomsday-watch")


class PageError(RuntimeError):
    """The site could not be read with enough confidence to report availability."""


@dataclass(frozen=True)
class Finding:
    site: str
    open: bool
    dates: tuple[str, ...]
    url: str
    detail: str


class NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_next = False
        self.content: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.in_next = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_next = False

    def handle_data(self, data: str) -> None:
        if self.in_next:
            self.content.append(data)


def parse_bms_dates(html: str) -> tuple[str, ...]:
    if "window.__INITIAL_STATE__" not in html or not re.search(
        r"<title>Avengers: Doomsday Movie Showtimes", html, re.I
    ):
        raise PageError("BookMyShow returned an unrecognized page or challenge")
    dates = set(re.findall(r'"dateCode":"(\d{8})"', html))
    dates.discard(PROBE_DATE)
    return tuple(sorted(dates))


def parse_bms_shows(html: str, date: str) -> int:
    if "window.__INITIAL_STATE__" not in html:
        raise PageError("BookMyShow showtime response is not an app page")
    if "showtimesSections" not in html:
        return 0
    # The requested URL may silently display another date. Inspect each show's
    # showDateCode, never the URL, page header, or a generic "Book" label.
    sessions = re.findall(
        r'"additionalData":\{"sessionId":"\d+","availStatus":"\d+",'
        r'[^}]*?"showDateCode":"(\d{8})"',
        html,
    )
    if '"sessionId":"' in html and not sessions:
        raise PageError("BookMyShow has sessions in a changed format")
    return sum(show_date == date for show_date in sessions)


def parse_district(html: str) -> Finding:
    parser = NextDataParser()
    parser.feed(html)
    if not parser.content:
        raise PageError("District did not return __NEXT_DATA__")
    try:
        page = json.loads("".join(parser.content))["props"]["pageProps"]
        data = page["data"]
        if str(data["contentId"]) != "176735":
            raise PageError("District returned a different movie")
        city = data.get("cityName", "")
        if city and city.lower() != "delhi-ncr":
            raise PageError(f"District returned the wrong city: {city}")
        server = data["serverState"]
        if "mdpV2MovieData" in server:
            # District's live-booking layout: actual sessions are stored in a
            # separate per-date map, while mdpV2MovieData.cinemas may be [].
            state = server["mdpV2MovieData"]["176735"]
            movie = state["movie"]
            dates = state["showDates"]
            session_groups = server["movieSessions"]
            sessions = [session for group in session_groups.values()
                        for cinema in group.get("arrangedSessions", [])
                        for session in cinema.get("sessions", [])]
            count = len(sessions)
            found_dates = tuple(sorted({str(s["showTime"])[:10] for s in sessions if s.get("showTime")}))
            detail = f"{count} bookable show(s) on {len(found_dates)} date(s)"
        else:
            # Upcoming-movie layout; its booking arrays are empty until sale.
            state = server["movieData"]["176735"]
            movie = data["movieData"]["meta"]["movie"]
            dates = state["showDates"]
            cinemas = state["cinemas"]
            count = len(cinemas)
            found_dates = tuple(sorted(set(re.findall(r"20\d{2}-?\d{2}-?\d{2}", json.dumps(dates)))))
            detail = f"{len(dates)} bookable date(s), {len(cinemas)} cinema(s)"
    except (KeyError, TypeError, ValueError) as exc:
        raise PageError("District booking data changed shape") from exc
    if movie.get("content_id") != 176735 or movie.get("name") != "Avengers: Doomsday":
        raise PageError("District returned a different movie")
    if not isinstance(dates, list):
        raise PageError("District showDates are not a list")
    # A release-date label is not a booking signal. Require actual sessions in
    # the live layout, or populated booking dates and cinemas in the upcoming one.
    is_open = bool(count and dates)
    return Finding(
        site="District", open=is_open, dates=found_dates, url=DISTRICT_URL,
        detail=detail,
    )


def check_bms(session: Any) -> Finding:
    response = session.get(BMS_URL + PROBE_DATE, timeout=30)
    if response.status_code != 200:
        raise PageError(f"BookMyShow HTTP {response.status_code}")
    dates = parse_bms_dates(response.text)
    if not dates:
        return Finding("BookMyShow", False, (), BMS_URL + PROBE_DATE, "no bookable dates")
    # Confirm the earliest available date against actual showDateCode values.
    earliest = dates[0]
    response = session.get(BMS_URL + earliest, timeout=30)
    if response.status_code != 200:
        raise PageError(f"BookMyShow showtimes HTTP {response.status_code}")
    count = parse_bms_shows(response.text, earliest)
    if not count:
        raise PageError("BookMyShow lists a date but no matching show was confirmed")
    return Finding("BookMyShow", True, dates, BMS_URL + earliest, f"{count} confirmed show(s) on {earliest}")


def check_district(session: requests.Session) -> Finding:
    response = session.get(DISTRICT_URL, timeout=30)
    if response.status_code != 200:
        raise PageError(f"District HTTP {response.status_code}")
    return parse_district(response.text)


def enabled_channels() -> list[str]:
    channels = []
    if os.getenv("NTFY_TOPIC"):
        channels.append("ntfy")
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        chat_ids = [os.getenv("TELEGRAM_CHAT_ID", "")]
        chat_ids.extend(os.getenv("TELEGRAM_EXTRA_CHAT_IDS", "").split(","))
        try:
            chat_ids.extend(load_telegram_subscribers(subscriber_path()))
        except (OSError, ValueError) as exc:
            LOG.error("Cannot read Telegram subscriber list: %s", exc)
        for chat_id in dict.fromkeys(value.strip() for value in chat_ids if value.strip()):
            channels.append(f"telegram:{chat_id}")
    if os.getenv("DISCORD_BOT_TOKEN") and os.getenv("DISCORD_USER_ID"):
        channels.append("discord_dm")
    if os.getenv("RESEND_API_KEY") and os.getenv("EMAIL_TO"):
        channels.append("resend_email")
    if os.getenv("SMTP_HOST") and os.getenv("EMAIL_TO") and os.getenv("EMAIL_FROM"):
        channels.append("email")
    return channels


def send_channel(channel: str, title: str, body: str, url: str) -> None:
    text = f"{title}\n{body}\n{url}"
    if channel == "ntfy":
        base = os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
        headers = {"Title": title, "Priority": "urgent", "Click": url, "Tags": "ticket"}
        token = os.getenv("NTFY_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        r = requests.post(f"{base}/{os.environ['NTFY_TOPIC']}", data=body.encode(), headers=headers, timeout=15)
        r.raise_for_status()
    elif channel.startswith("telegram:"):
        chat_id = channel.partition(":")[2]
        r = requests.post(
            f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
            timeout=15,
        )
        r.raise_for_status()
        if not r.json().get("ok"):
            raise RuntimeError("Telegram rejected the message")
    elif channel == "discord_dm":
        headers = {"Authorization": f"Bot {os.environ['DISCORD_BOT_TOKEN']}"}
        r = requests.post(
            "https://discord.com/api/v10/users/@me/channels",
            json={"recipient_id": os.environ["DISCORD_USER_ID"]}, headers=headers, timeout=15,
        )
        r.raise_for_status()
        channel_id = r.json()["id"]
        r = requests.post(
            f"https://discord.com/api/v10/channels/{channel_id}/messages",
            json={"content": text[:2000]}, headers=headers, timeout=15,
        )
        r.raise_for_status()
    elif channel == "resend_email":
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
            json={
                "from": os.getenv("RESEND_FROM", "Doomsday Watch <onboarding@resend.dev>"),
                "to": [os.environ["EMAIL_TO"]],
                "subject": title,
                "text": text,
            },
            timeout=15,
        )
        r.raise_for_status()
        if not r.json().get("id"):
            raise RuntimeError("Resend accepted the request without an email ID")
    elif channel == "email":
        mail = EmailMessage()
        mail["Subject"] = title
        mail["From"] = os.environ["EMAIL_FROM"]
        mail["To"] = os.environ["EMAIL_TO"]
        mail.set_content(text)
        port = int(os.getenv("SMTP_PORT", "587"))
        with smtplib.SMTP(os.environ["SMTP_HOST"], port, timeout=20) as smtp:
            smtp.starttls()
            if os.getenv("SMTP_USER"):
                smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(mail)
    else:
        raise ValueError(f"unknown channel {channel}")


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "delivered": {}, "failures": {}, "fault_sequence": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["version"] != 1 or not isinstance(data["delivered"], dict):
            raise ValueError("incompatible state")
        data.setdefault("failures", {})
        data.setdefault("fault_sequence", {})
        return data
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Cannot read state {path}; refusing to reset sent alerts") from exc


def tickets_found(state: dict[str, Any]) -> bool:
    """Keep logs after any confirmed opening, including one from older state files."""
    return bool(state.get("ticket_seen")) or any(
        event.startswith("open:") for event in state.get("delivered", {})
    )


def begin_cycle_log(log_path: Path | None, state: dict[str, Any]) -> None:
    """Keep only the current cycle's routine log until an opening is found."""
    if log_path is not None and not tickets_found(state):
        log_path.write_text("", encoding="utf-8")


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def deliver_once(path: Path, state: dict[str, Any], event: str, title: str, body: str, url: str) -> None:
    sent = state["delivered"].setdefault(event, [])
    for channel in enabled_channels():
        if channel in sent:
            continue
        try:
            send_channel(channel, title, body, url)
            sent.append(channel)
            save_state(path, state)
            LOG.info("Delivered %s via %s", event, channel)
        except Exception as exc:
            LOG.error("Alert delivery via %s failed: %s", channel, exc)


def run_once(path: Path, state: dict[str, Any], bms: Any, district: requests.Session) -> None:
    # Persist the start time so a service restart does not poll again early.
    state["last_cycle_started"] = time.time()
    save_state(path, state)
    for site, check in (("BookMyShow", lambda: check_bms(bms)), ("District", lambda: check_district(district))):
        try:
            finding = check()
            state["failures"][site] = 0
            state.setdefault("last_checks", {})[site] = {
                "checked_at": time.time(), "status": "open" if finding.open else "waiting",
                "detail": finding.detail,
            }
            LOG.info("%s: %s", site, finding.detail)
            if finding.open:
                state["ticket_seen"] = True
                save_state(path, state)
                date_text = ", ".join(finding.dates[:5]) or "check the listing for dates"
                deliver_once(
                    path, state, f"open:{site}", f"Avengers: Doomsday tickets open on {site}",
                    f"Delhi/NCR: {finding.detail}. Dates: {date_text}. Book promptly.", finding.url,
                )
        except Exception as exc:
            if state["failures"].get(site, 0) == 0:
                state["fault_sequence"][site] = state["fault_sequence"].get(site, 0) + 1
            failures = state["failures"].get(site, 0) + 1
            state["failures"][site] = failures
            state.setdefault("last_checks", {})[site] = {
                "checked_at": time.time(), "status": "error", "detail": str(exc),
            }
            LOG.error("%s check failed (%s in a row): %s", site, failures, exc)
            if failures >= 3:
                deliver_once(
                    path, state, f"fault:{site}:{state['fault_sequence'][site]}:{failures // 60}",
                    f"Doomsday monitor cannot check {site}",
                    f"{failures} consecutive checks failed. This is not a no-tickets result. Error: {exc}",
                    BMS_URL + PROBE_DATE if site == "BookMyShow" else DISTRICT_URL,
                )
    state["last_cycle_completed"] = time.time()
    save_state(path, state)


def ping_healthcheck() -> None:
    """Report that a complete polling cycle ran; site failures have their own alerts."""
    url = os.getenv("HEALTHCHECK_URL", "").strip()
    if not url:
        return
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        LOG.warning("External heartbeat failed: %s", exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="check both sites once and exit")
    parser.add_argument("--test-alert", action="store_true", help="send a test through configured channels")
    args = parser.parse_args()
    log_path = Path(os.environ["WATCH_LOG_FILE"]) if os.getenv("WATCH_LOG_FILE") else None
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_path, encoding="utf-8")
        log_path.chmod(0o600)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S %Z", handlers=[handler])
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S %Z")
    if not enabled_channels():
        parser.error("configure at least one alert channel; see .env.example")
    interval = max(600, int(os.getenv("POLL_SECONDS", str(DEFAULT_INTERVAL))))
    path = Path(os.getenv("STATE_FILE", "state.json"))
    state = load_state(path)
    if args.test_alert:
        for channel in enabled_channels():
            send_channel(channel, "Doomsday monitor test", "Your alert channel is working.", DISTRICT_URL)
            LOG.info("Test delivered via %s", channel)
        return 0
    bms = browser_requests.Session(impersonate="safari")
    district = requests.Session()
    try:
        if not args.once and state.get("last_cycle_started"):
            remaining = interval - (time.time() - state["last_cycle_started"])
            if remaining > 0:
                LOG.info("Waiting %.0f seconds to preserve the polling interval", remaining)
                time.sleep(remaining)
        while True:
            started = time.monotonic()
            begin_cycle_log(log_path, state)
            run_once(path, state, bms, district)
            ping_healthcheck()
            if args.once:
                break
            time.sleep(max(0, interval - (time.monotonic() - started)))
    finally:
        bms.close()
        district.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
