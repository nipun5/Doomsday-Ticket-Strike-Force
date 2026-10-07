import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import watch


def district_html(dates, cinemas):
    payload = {
        "props": {"pageProps": {"data": {
            "contentId": "176735",
            "movieData": {"meta": {"movie": {"content_id": 176735, "name": "Avengers: Doomsday"}}},
            "serverState": {"movieData": {"176735": {"showDates": dates, "cinemas": cinemas}}},
        }}}
    }
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + "</script>"


def district_live_html():
    payload = {"props": {"pageProps": {"data": {
        "contentId": "176735", "cityName": "delhi-ncr",
        "serverState": {
            "mdpV2MovieData": {"176735": {
                "movie": {"content_id": 176735, "name": "Avengers: Doomsday"},
                "showDates": ["2026-12-18"], "cinemas": [],
            }},
            "movieSessions": {"today": {"arrangedSessions": [
                {"entityName": "Cinema", "sessions": [{"sid": "123", "showTime": "2026-12-18T06:00"}]}
            ]}},
        },
    }}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + "</script>"


class ParserTests(unittest.TestCase):
    def test_bms_probe_excludes_injected_date(self):
        html = (
            '<title>Avengers: Doomsday Movie Showtimes in Delhi-NCR</title>'
            'window.__INITIAL_STATE__'
            '"dateCode":"20991231" "dateCode":"20261218"'
        )
        self.assertEqual(watch.parse_bms_dates(html), ("20261218",))

    def test_bms_show_date_substitution_does_not_trigger(self):
        html = ('window.__INITIAL_STATE__ showtimesSections '
                '"additionalData":{"sessionId":"123","availStatus":"3",'
                '"showDateCode":"20261217"}')
        self.assertEqual(watch.parse_bms_shows(html, "20261218"), 0)
        self.assertEqual(watch.parse_bms_shows(html, "20261217"), 1)

    def test_bms_block_is_an_error(self):
        with self.assertRaises(watch.PageError):
            watch.parse_bms_dates("<html>Cloudflare challenge</html>")

    def test_district_open_requires_dates_and_cinemas(self):
        self.assertFalse(watch.parse_district(district_html([], [])).open)
        self.assertFalse(watch.parse_district(district_html(["2026-12-18"], [])).open)
        finding = watch.parse_district(district_html(["2026-12-18"], [{"name": "Cinema"}]))
        self.assertTrue(finding.open)
        self.assertEqual(finding.dates, ("2026-12-18",))

    def test_district_live_layout_uses_actual_sessions(self):
        finding = watch.parse_district(district_live_html())
        self.assertTrue(finding.open)
        self.assertEqual(finding.dates, ("2026-12-18",))
        self.assertIn("1 bookable show", finding.detail)

    def test_district_missing_booking_data_is_an_error(self):
        with self.assertRaises(watch.PageError):
            watch.parse_district("<html>Not the movie page</html>")


class AlertTests(unittest.TestCase):
    def test_routine_log_clears_until_opening_then_is_preserved(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            log = Path(directory) / "watch.log"
            log.write_text("old check\n", encoding="utf-8")
            state_path = Path(directory) / "state.json"
            state = watch.load_state(state_path)
            watch.begin_cycle_log(log, state)
            self.assertEqual(log.read_text(encoding="utf-8"), "")

            with patch.object(watch, "check_bms", return_value=watch.Finding(
                "BookMyShow", True, ("20261218",), "https://example.test", "1 confirmed show"
            )), patch.object(watch, "check_district", return_value=watch.Finding(
                "District", False, (), "https://example.test", "0 dates"
            )), patch.object(watch, "enabled_channels", return_value=[]):
                watch.run_once(state_path, state, object(), object())

            self.assertTrue(watch.load_state(state_path)["ticket_seen"])
            log.write_text("ticket found\n", encoding="utf-8")
            watch.begin_cycle_log(log, watch.load_state(state_path))
            self.assertEqual(log.read_text(encoding="utf-8"), "ticket found\n")

    def test_telegram_recipients_retry_independently(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "state.json"
            state = watch.load_state(path)
            sent = []

            def send(channel, *_):
                sent.append(channel)
                if channel == "telegram:friend" and sent.count(channel) == 1:
                    raise RuntimeError("temporary Telegram failure")

            with patch.object(watch, "enabled_channels", return_value=["telegram:owner", "telegram:friend"]), \
                    patch.object(watch, "send_channel", side_effect=send):
                watch.deliver_once(path, state, "open:District", "title", "body", "url")
                watch.deliver_once(path, watch.load_state(path), "open:District", "title", "body", "url")

            self.assertEqual(sent, ["telegram:owner", "telegram:friend", "telegram:friend"])
            self.assertEqual(watch.load_state(path)["delivered"]["open:District"],
                             ["telegram:owner", "telegram:friend"])

    def test_successful_channels_are_not_resent_after_restart(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            path = Path(directory) / "state.json"
            state = watch.load_state(path)
            sent = []

            def send(channel, *_):
                sent.append(channel)
                if channel == "email" and sent.count("email") == 1:
                    raise RuntimeError("temporary SMTP failure")

            with patch.object(watch, "enabled_channels", return_value=["telegram", "email"]), \
                    patch.object(watch, "send_channel", side_effect=send):
                watch.deliver_once(path, state, "open:BookMyShow", "title", "body", "url")
                self.assertEqual(watch.load_state(path)["delivered"]["open:BookMyShow"], ["telegram"])
                watch.deliver_once(path, watch.load_state(path), "open:BookMyShow", "title", "body", "url")

            self.assertEqual(sent, ["telegram", "email", "email"])
            self.assertEqual(watch.load_state(path)["delivered"]["open:BookMyShow"], ["telegram", "email"])


if __name__ == "__main__":
    unittest.main()
