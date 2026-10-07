#!/usr/bin/env python3
"""Reply to /start and enroll private chats for Doomsday ticket alerts."""

import json
import logging
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from telegram_subscriptions import add, path_from_env, remove


load_dotenv(Path(__file__).with_name(".env"))
LOG = logging.getLogger("doomsday-telegram")
CURSOR_PATH = Path(__file__).with_name("telegram_cursor.json")
WELCOME = (
    "Welcome to the Doomsday Ticket Strike Force! Thanks for joining. "
    "We check Avengers: Doomsday tickets in Delhi/NCR on BookMyShow and District "
    "every 10 minutes. You will receive an alert here when we detect that bookings open. "
    "Send /stop to leave alerts."
)


def api_call(session: requests.Session, token: str, method: str, payload: dict, timeout: int) -> dict:
    response = session.post(
        f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=timeout,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Telegram {method} HTTP {response.status_code}")
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} rejected the request")
    return data


def get_updates(session: requests.Session, token: str, offset: int | None, wait: int) -> list[dict]:
    payload = {"timeout": wait, "limit": 100}
    if offset is not None:
        payload["offset"] = offset
    return api_call(session, token, "getUpdates", payload, wait + 15)["result"]


def send_message(session: requests.Session, token: str, chat_id: str, text: str) -> None:
    api_call(session, token, "sendMessage", {"chat_id": chat_id, "text": text}, 15)


def command_from_message(message: dict) -> str:
    words = str(message.get("text", "")).split(maxsplit=1)
    return words[0].split("@", 1)[0].lower() if words else ""


def handle_update(session: requests.Session, token: str, update: dict, owner_id: str) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return
    chat_id = str(chat["id"])
    command = command_from_message(message)
    if command == "/start":
        add(path_from_env(), chat_id)
        send_message(session, token, chat_id, WELCOME)
        LOG.info("Welcomed private chat %s", chat_id)
    elif command == "/stop":
        if chat_id == owner_id:
            send_message(session, token, chat_id, "This is the owner chat; remove TELEGRAM_CHAT_ID on the server to stop its alerts.")
        else:
            remove(path_from_env(), chat_id)
            send_message(session, token, chat_id, "You have left Doomsday ticket alerts. Send /start to join again.")
        LOG.info("Processed /stop for private chat %s", chat_id)


def read_cursor() -> int | None:
    if not CURSOR_PATH.exists():
        return None
    return int(json.loads(CURSOR_PATH.read_text(encoding="utf-8"))["offset"])


def save_cursor(offset: int) -> None:
    temp = CURSOR_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    temp.replace(CURSOR_PATH)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S %Z")
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    owner_id = os.getenv("TELEGRAM_CHAT_ID", "")
    session = requests.Session()
    offset = read_cursor()
    while True:
        try:
            updates = get_updates(session, token, offset, 30)
            if offset is None:
                # An old /start may have been sent before this listener existed.
                # Welcome each existing private chat once, then continue live.
                latest_starts = {}
                for update in updates:
                    message = update.get("message") or {}
                    chat = message.get("chat") or {}
                    command = command_from_message(message)
                    if chat.get("type") == "private" and command == "/start":
                        latest_starts[str(chat["id"])] = update
                for update in latest_starts.values():
                    handle_update(session, token, update, owner_id)
                if updates:
                    offset = max(item["update_id"] for item in updates) + 1
                    save_cursor(offset)
            else:
                for update in updates:
                    handle_update(session, token, update, owner_id)
                    offset = update["update_id"] + 1
                    save_cursor(offset)
        except Exception as exc:
            # requests exceptions can contain the token-bearing URL; never log
            # the exception text from this process.
            LOG.error("Telegram listener failure: %s", type(exc).__name__)
            time.sleep(10)


if __name__ == "__main__":
    main()
