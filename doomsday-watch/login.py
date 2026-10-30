#!/usr/bin/env python3
"""Login pages and 30-day sessions for the private sites behind Caddy.

Caddy sends /login and /logout here and asks /verify before every other request
(forward_auth). Each site block names itself with the X-Login-Site header; its
accounts are the bcrypt lines in /etc/caddy/<site>_users, managed by
dashboard_user.sh. Listens on localhost only.
"""

import hashlib
import hmac
import html
import os
import re
import secrets
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

USERS_DIR = Path(os.getenv("LOGIN_USERS_DIR", "/etc/caddy"))
KEY_FILE = Path(os.getenv("STATE_DIRECTORY", "/var/lib/site-login")) / "secret.key"
COOKIE = "__Host-session"
MAX_AGE = 30 * 86400
SITE_RE = re.compile(r"[a-z0-9_]{1,32}")
FAIL_WINDOW, FAIL_LIMIT = 900, 10
failures: dict[str, list[float]] = {}


def load_key() -> bytes:
    if not KEY_FILE.exists():
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(secrets.token_bytes(32))
    return KEY_FILE.read_bytes()


def accounts(site: str) -> dict[str, str]:
    path = USERS_DIR / f"{site}_users"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return dict(line.split(" ", 1) for line in lines if " " in line)


def signature(key: bytes, site: str, user: str, expires: int, pw_hash: str) -> str:
    # Including the stored hash ends every session when a password is reset or removed.
    message = f"{site}|{user}|{expires}|{hashlib.sha256(pw_hash.encode()).hexdigest()}"
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def make_token(key: bytes, site: str, user: str, pw_hash: str, now: float) -> str:
    expires = int(now) + MAX_AGE
    return f"{user}.{expires}.{signature(key, site, user, expires, pw_hash)}"


def check_token(key: bytes, site: str, token: str, users: dict[str, str], now: float) -> str | None:
    try:
        user, expires, sig = token.rsplit(".", 2)
        expires = int(expires)
    except ValueError:
        return None
    if expires < now or user not in users:
        return None
    return user if hmac.compare_digest(sig, signature(key, site, user, expires, users[user])) else None


def safe_next(target: str) -> str:
    """Only same-site paths, so the login page can't be used as an open redirect."""
    return target if target.startswith("/") and not target.startswith("//") and "\\" not in target else "/"


def too_many_failures(ip: str, now: float) -> bool:
    recent = [t for t in failures.get(ip, []) if now - t < FAIL_WINDOW]
    failures[ip] = recent
    return len(recent) >= FAIL_LIMIT


THEMES = {
    "doom": ("Doomsday Ticket Strike Force", "Identify yourself to enter the war room.", """
      body { background: radial-gradient(900px 500px at 50% -10%, rgba(31,191,106,.28), transparent 60%), #040805;
             color: #e4f3e9; font: 500 17px/1.5 "Rajdhani", system-ui, sans-serif; }
      .card { background: rgba(10,22,14,.85); border: 1px solid rgba(57,255,136,.25); box-shadow: 0 0 60px rgba(57,255,136,.12); }
      h1 { font: 800 2rem/1.1 "Cinzel", Georgia, serif; letter-spacing: .08em; color: transparent;
           background: linear-gradient(180deg,#f4fbf6,#b9c9be 45%,#6f8577 55%,#dfe9e2); -webkit-background-clip: text; background-clip: text; }
      p, label { color: #a9bdb0; }
      input { background: rgba(0,0,0,.45); border: 1px solid rgba(57,255,136,.25); color: #e4f3e9; }
      input:focus { outline: 2px solid #39ff88; }
      button { background: #39ff88; color: #04140a; box-shadow: 0 0 22px rgba(57,255,136,.45); letter-spacing: .12em; text-transform: uppercase; }
      .err { color: #ff5a5f; border-color: #ff5a5f; }"""),
    "jobs": ("Govt Jobs Portal", "Sign in to see your matches, CVs and checks.", """
      body { background: #f4f6f9; color: #18202b; font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
      .card { background: #fff; border: 1px solid #dfe4ea; }
      h1 { font-size: 1.5rem; } p, label { color: #5b6676; }
      input { background: #fff; border: 1px solid #dfe4ea; color: #18202b; }
      input:focus { outline: 2px solid #1f5f99; }
      button { background: #1f5f99; color: #fff; }
      .err { color: #b42318; border-color: #b42318; }
      @media (prefers-color-scheme: dark) {
        body { background: #0f1318; color: #e5e9ef; } .card { background: #181e26; border-color: #2a333f; }
        p, label { color: #97a3b3; } input { background: #131920; border-color: #2a333f; color: #e5e9ef; }
        button { background: #72aee6; color: #0f1318; } .err { color: #f2857c; border-color: #f2857c; } }"""),
}


def login_page(theme: str, next_url: str, error: str = "") -> bytes:
    title, intro, css = THEMES.get(theme, THEMES["jobs"])
    fonts = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cinzel:wght@800'
             '&family=Rajdhani:wght@500;700&display=swap">') if theme == "doom" else ""
    err = f'<p class="err" role="alert">{html.escape(error)}</p>' if error else ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>Sign in · {html.escape(title)}</title>{fonts}<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px; }}
  .card {{ width: min(400px, 100%); border-radius: 16px; padding: 28px 24px; }}
  h1 {{ margin: 0 0 4px; }} p {{ margin: 0 0 20px; }}
  label {{ display: block; font-size: .9rem; margin: 14px 0 6px; }}
  input {{ width: 100%; padding: 12px 14px; border-radius: 10px; font: inherit; font-size: 16px; }}
  button {{ width: 100%; margin-top: 22px; padding: 13px; border: 0; border-radius: 10px; font: inherit; font-weight: 700; cursor: pointer; }}
  .err {{ border: 1px solid; border-radius: 10px; padding: 10px 12px; margin: 0 0 6px; }}
  {css}
</style></head><body><main class="card">
<h1>{html.escape(title)}</h1><p>{html.escape(intro)}</p>{err}
<form method="post" action="/login?next={quote(next_url, safe='/')}">
  <label for="u">Username</label><input id="u" name="username" autocomplete="username" autocapitalize="none" required autofocus>
  <label for="p">Password</label><input id="p" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
</form><p style="margin:16px 0 0;font-size:.85rem">You stay signed in on this device for 30 days.</p>
</main></body></html>""".encode()


def password_ok(password: str, stored: str | None) -> bool:
    import bcrypt  # python3-bcrypt; imported here so the token tests run without it
    try:
        # Unknown users are checked against a throwaway hash so they take as long as known ones.
        return bcrypt.checkpw(password.encode(), (stored or Handler.dummy).encode()) and stored is not None
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    key = b""
    dummy = ""

    def site(self) -> str | None:
        site = self.headers.get("X-Login-Site", "")
        return site if SITE_RE.fullmatch(site) else None

    def user(self, site: str) -> str | None:
        morsel = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
        return morsel and check_token(self.key, site, morsel.value, accounts(site), time.time())

    def send(self, code: int, body: bytes = b"", headers: dict | None = None) -> None:
        self.send_response(code)
        for name, value in {"Cache-Control": "no-store", "Content-Length": str(len(body)), **(headers or {})}.items():
            self.send_header(name, value)
        if body:
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        site, url = self.site(), urlsplit(self.path)
        if not site:
            return self.send(500, b"Login is not configured for this site")
        next_url = safe_next(parse_qs(url.query).get("next", ["/"])[0])
        if url.path == "/verify":
            if self.user(site):
                return self.send(204)
            uri = self.headers.get("X-Forwarded-Uri", "/")
            if uri.startswith("/api/"):
                return self.send(401)
            return self.send(302, headers={"Location": "/login?next=" + quote(safe_next(uri), safe="/")})
        if url.path == "/login":
            if self.user(site):
                return self.send(303, headers={"Location": next_url})
            return self.send(200, login_page(self.headers.get("X-Login-Theme", ""), next_url))
        if url.path == "/logout":
            return self.send(303, headers={"Location": "/login",
                                           "Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax"})
        self.send(404)

    def do_POST(self) -> None:
        site, url = self.site(), urlsplit(self.path)
        if not site or url.path != "/login":
            return self.send(404)
        theme, next_url = self.headers.get("X-Login-Theme", ""), safe_next(parse_qs(url.query).get("next", ["/"])[0])
        ip, now = self.headers.get("X-Forwarded-For", "").split(",")[-1].strip() or self.client_address[0], time.time()
        if too_many_failures(ip, now):
            return self.send(429, login_page(theme, next_url, "Too many wrong attempts. Try again in 15 minutes."))
        length = min(int(self.headers.get("Content-Length", 0) or 0), 4096)
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        user, password = form.get("username", [""])[0].strip(), form.get("password", [""])[0]
        users = accounts(site)
        if password and password_ok(password, users.get(user)):
            token = make_token(self.key, site, user, users[user], now)
            cookie = f"{COOKIE}={token}; Path=/; Max-Age={MAX_AGE}; Secure; HttpOnly; SameSite=Lax"
            return self.send(303, headers={"Location": next_url, "Set-Cookie": cookie})
        failures.setdefault(ip, []).append(now)
        self.send(401, login_page(theme, next_url, "Wrong username or password."))

    def log_message(self, *_) -> None:
        pass  # never log form bodies or cookies


if __name__ == "__main__":
    import bcrypt
    Handler.key = load_key()
    Handler.dummy = bcrypt.hashpw(secrets.token_bytes(16), bcrypt.gensalt(14)).decode()
    ThreadingHTTPServer(("127.0.0.1", int(os.getenv("LOGIN_PORT", "8099"))), Handler).serve_forever()
