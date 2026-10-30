import unittest

import login

KEY = b"k" * 32
USERS = {"nipun": "$2a$14$storedhash"}


class LoginTests(unittest.TestCase):
    def test_session_token_round_trip_and_rejections(self):
        token = login.make_token(KEY, "dashboard", "nipun", USERS["nipun"], 1000)
        self.assertEqual(login.check_token(KEY, "dashboard", token, USERS, 2000), "nipun")
        self.assertIsNone(login.check_token(KEY, "govt_jobs", token, USERS, 2000))  # other site
        self.assertIsNone(login.check_token(b"x" * 32, "dashboard", token, USERS, 2000))  # other key
        self.assertIsNone(login.check_token(KEY, "dashboard", token, USERS, 1000 + login.MAX_AGE + 1))  # expired
        self.assertIsNone(login.check_token(KEY, "dashboard", token, {"nipun": "$2a$14$newhash"}, 2000))  # password reset
        self.assertIsNone(login.check_token(KEY, "dashboard", token, {}, 2000))  # login removed
        self.assertIsNone(login.check_token(KEY, "dashboard", token[:-1] + ("1" if token[-1] == "0" else "0"), USERS, 2000))  # tampered
        self.assertIsNone(login.check_token(KEY, "dashboard", "garbage", USERS, 2000))

    def test_next_stays_on_site(self):
        self.assertEqual(login.safe_next("/api/status"), "/api/status")
        for bad in ("https://evil.test", "//evil.test", "/\\evil.test", ""):
            self.assertEqual(login.safe_next(bad), "/")

    def test_failures_lock_out_then_expire(self):
        login.failures.clear()
        login.failures["1.2.3.4"] = [100.0] * login.FAIL_LIMIT
        self.assertTrue(login.too_many_failures("1.2.3.4", 200))
        self.assertFalse(login.too_many_failures("1.2.3.4", 100 + login.FAIL_WINDOW + 1))
        self.assertFalse(login.too_many_failures("5.6.7.8", 200))


if __name__ == "__main__":
    unittest.main()
