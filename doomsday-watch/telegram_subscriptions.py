"""Atomic storage for private Telegram chats that opted in with /start."""

import json
import os
import tempfile
from pathlib import Path


DEFAULT_PATH = Path(__file__).with_name("telegram_subscribers.json")


def path_from_env() -> Path:
    return Path(os.getenv("TELEGRAM_SUBSCRIBERS_FILE", str(DEFAULT_PATH)))


def load(path: Path) -> list[str]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not all(isinstance(item, str) and item.isdecimal() for item in data):
        raise ValueError("Invalid Telegram subscriber file")
    return list(dict.fromkeys(data))


def save(path: Path, ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".telegram_subscribers.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(sorted(set(ids)), stream)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def add(path: Path, chat_id: str) -> bool:
    ids = load(path)
    if chat_id in ids:
        return False
    save(path, ids + [chat_id])
    return True


def remove(path: Path, chat_id: str) -> bool:
    ids = load(path)
    if chat_id not in ids:
        return False
    save(path, [item for item in ids if item != chat_id])
    return True
