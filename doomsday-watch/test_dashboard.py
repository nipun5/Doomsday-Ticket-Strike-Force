import json
import unittest

import dashboard


class DashboardTests(unittest.TestCase):
    def test_summary_shows_status_without_delivery_records(self):
        state = {
            "version": 1, "last_cycle_started": 1000, "last_cycle_completed": 1002,
            "delivered": {"open:District": ["telegram:123456789"]},
            "failures": {"BookMyShow": 2},
            "last_checks": {"District": {"status": "open", "detail": "3 bookable show(s)", "checked_at": 1001}},
        }
        result = dashboard.summary(state)
        self.assertNotIn("123456789", json.dumps(result))
        self.assertEqual(result["next_check_due"], 1600)
        self.assertTrue(result["ticket_seen"])
        self.assertEqual(result["sites"]["BookMyShow"], {
            "status": "unknown", "detail": "no saved result", "checked_at": None, "errors": 2,
        })
        self.assertEqual(result["sites"]["District"]["status"], "open")


if __name__ == "__main__":
    unittest.main()
