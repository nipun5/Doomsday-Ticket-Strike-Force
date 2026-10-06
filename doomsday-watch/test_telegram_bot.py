import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telegram_bot
import watch
from telegram_subscriptions import load


class TelegramSubscriptionTests(unittest.TestCase):
    def test_start_welcomes_and_enrolls_friend_then_stop_removes_them(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "subscribers.json"
            env = {"TELEGRAM_SUBSCRIBERS_FILE": str(path), "TELEGRAM_BOT_TOKEN": "test-token",
                   "TELEGRAM_CHAT_ID": "100", "TELEGRAM_EXTRA_CHAT_IDS": ""}
            start = {"message": {"chat": {"type": "private", "id": 200}, "text": "/start"}}
            stop = {"message": {"chat": {"type": "private", "id": 200}, "text": "/stop"}}
            with patch.dict(os.environ, env), patch.object(telegram_bot, "send_message") as send:
                telegram_bot.handle_update(None, "test-token", start, "100")
                self.assertEqual(load(path), ["200"])
                self.assertIn("telegram:100", watch.enabled_channels())
                self.assertIn("telegram:200", watch.enabled_channels())
                self.assertIn("Welcome to the Doomsday Ticket Strike Force", send.call_args.args[3])
                telegram_bot.handle_update(None, "test-token", stop, "100")
                self.assertEqual(load(path), [])
                self.assertNotIn("telegram:200", watch.enabled_channels())


if __name__ == "__main__":
    unittest.main()
