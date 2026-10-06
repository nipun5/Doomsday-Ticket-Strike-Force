#!/usr/bin/env python3
"""Configure a Telegram alert without putting the bot token in shell history."""

import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


ENV_PATH = Path(__file__).with_name(".env")


def api_call(token: str, method: str, payload: dict | None = None, timeout: int = 15) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=timeout) as response:
            result = json.load(response)
    except (urllib.error.URLError, ValueError):
        raise RuntimeError(f"Telegram {method} failed; check the token and your connection") from None
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} rejected the request")
    return result


def set_env(name: str, value: str, content: str) -> str:
    line = f"{name}={value}"
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.MULTILINE)
    return pattern.sub(line, content) if pattern.search(content) else content.rstrip() + "\n" + line + "\n"


def main() -> int:
    if not ENV_PATH.exists():
        print("Missing .env in the watcher directory", file=sys.stderr)
        return 1
    token = getpass.getpass("Paste the BotFather token (hidden): ").strip()
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token):
        print("That does not look like a Telegram bot token", file=sys.stderr)
        return 1
    try:
        bot = api_call(token, "getMe")["result"]
        print(f"Token belongs to @{bot['username']}.")
        print("Send a fresh message to this bot now; waiting up to 30 seconds...", flush=True)
        updates = api_call(token, "getUpdates?timeout=30", timeout=40)["result"]
        chats = [item["message"]["chat"] for item in updates
                 if item.get("message", {}).get("chat", {}).get("type") == "private"]
        if not chats:
            print(f"No private message reached @{bot['username']}. Check that you messaged this exact bot, then rerun.")
            return 1
        chat_id = str(chats[-1]["id"])
        api_call(token, "sendMessage", {"chat_id": chat_id,
                                      "text": "Doomsday monitor Telegram test: alerts can reach this chat."})
        content = ENV_PATH.read_text(encoding="utf-8")
        content = set_env("TELEGRAM_BOT_TOKEN", token, content)
        content = set_env("TELEGRAM_CHAT_ID", chat_id, content)
        temp = ENV_PATH.with_suffix(".env.tmp")
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        temp.replace(ENV_PATH)
        print("Telegram test sent and .env updated. Restart doomsday-watch to activate it.")
        return 0
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
