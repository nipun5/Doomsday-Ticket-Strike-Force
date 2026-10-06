#!/usr/bin/env python3
"""Configure Resend email alerts without putting the API key in shell history."""

import getpass
import os
import re
import sys
import tempfile
from pathlib import Path

import requests


ENV_PATH = Path(__file__).with_name(".env")
FROM = "Doomsday Watch <onboarding@resend.dev>"


def set_env(name: str, value: str, content: str) -> str:
    line = f"{name}={value}"
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.MULTILINE)
    return pattern.sub(line, content) if pattern.search(content) else content.rstrip() + "\n" + line + "\n"


def main() -> int:
    if not ENV_PATH.exists():
        print("Missing .env in the watcher directory", file=sys.stderr)
        return 1
    recipient = input("Email address used for your Resend account: ").strip()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", recipient):
        print("Invalid email address", file=sys.stderr)
        return 1
    key = getpass.getpass("Paste your Resend Sending-access API key (hidden): ").strip()
    if not key.startswith("re_"):
        print("That does not look like a Resend API key", file=sys.stderr)
        return 1
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json={"from": FROM, "to": [recipient],
                  "subject": "Doomsday monitor email test",
                  "text": "Your email alert channel is working. Avengers: Doomsday Delhi/NCR checks continue every 10 minutes."},
            timeout=20,
        )
        if response.status_code != 200 or not response.json().get("id"):
            message = response.json().get("message", "request was rejected")
            print(f"Resend rejected the test (HTTP {response.status_code}): {message}", file=sys.stderr)
            return 1
        content = ENV_PATH.read_text(encoding="utf-8")
        for name, value in (("RESEND_API_KEY", key), ("RESEND_FROM", FROM), ("EMAIL_TO", recipient)):
            content = set_env(name, value, content)
        fd, temp_path = tempfile.mkstemp(prefix=".env.", dir=ENV_PATH.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temp_path, ENV_PATH)
        print("Email test accepted by Resend and .env updated. Check your inbox, then restart doomsday-watch.")
        return 0
    except (requests.RequestException, ValueError) as exc:
        print(f"Could not send the email test: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
