"""
auth-gateway — unified authentication service
Flask on port 4001. Telegram OTP + TOTP login, SQLite user store.
Exposes /auth/check for nginx auth_request (all apps on the network).
"""

import os
import random
import sqlite3
import time
import logging
from datetime import timedelta

import pyotp
import requests
from flask import (
    Flask, Blueprint, request, session,
    render_template, redirect, jsonify
)

VERSION = "1.1.0"

# ── Config ────────────────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = int(os.environ.get("TELEGRAM_CHAT_ID", "502550514"))
SECRET_KEY     = os.environ["SECRET_KEY"]
OTP_TTL        = int(os.environ.get("OTP_TTL", "300"))
SESSION_TTL    = int(os.environ.get("SESSION_TTL", "14400"))
DB_FILE        = os.environ.get("DB_FILE", "/home/uri/auth_gateway.db")
ADMIN_USER     = os.environ.get("ADMIN_USER", "uri")

# ── App setup ─────────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(seconds=SESSION_TTL)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("auth-gateway")

# ── Database ──────────────────────────────────────────────────────────────────

_db_conn: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        _db_conn.execute("PRAGMA journal_mode=WAL")
    return _db_conn


def init_db() -> None:
    get_db().executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT UNIQUE NOT NULL,
            totp_secret TEXT,
            is_admin   INTEGER DEFAULT 0,
            created_at REAL DEFAULT (unixepoch('now'))
        );
        CREATE TABLE IF NOT EXISTS otp_codes (
            username   TEXT PRIMARY KEY,
            code       TEXT NOT NULL,
            expires_at REAL NOT NULL
        );
    """)
    get_db().commit()


init_db()
log.info("Database ready: %s", DB_FILE)

# ── DB helpers ────────────────────────────────────────────────────────────────


def user_exists(username: str) -> bool:
    return get_db().execute(
        "SELECT 1 FROM users WHERE username = ?", (username,)
    ).fetchone() is not None


def get_totp_secret(username: str) -> str | None:
    row = get_db().execute(
        "SELECT totp_secret FROM users WHERE username = ?", (username,)
    ).fetchone()
    return row["totp_secret"] if row else None


def set_totp_secret(username: str, secret: str) -> None:
    get_db().execute(
        "UPDATE users SET totp_secret = ? WHERE username = ?", (secret, username)
    )
    get_db().commit()


def delete_totp_secret(username: str) -> None:
    get_db().execute(
        "UPDATE users SET totp_secret = NULL WHERE username = ?", (username,)
    )
    get_db().commit()


def list_users() -> list[dict]:
    rows = get_db().execute(
        "SELECT username, totp_secret, is_admin FROM users ORDER BY username"
    ).fetchall()
    return [dict(r) for r in rows]


def db_set_role(username: str, is_admin: int) -> None:
    get_db().execute(
        "UPDATE users SET is_admin = ? WHERE username = ?", (is_admin, username)
    )
    get_db().commit()


def db_add_user(username: str) -> None:
    try:
        get_db().execute("INSERT INTO users (username) VALUES (?)", (username,))
        get_db().commit()
    except sqlite3.IntegrityError:
        pass  # already exists


def db_remove_user(username: str) -> None:
    get_db().execute("DELETE FROM users WHERE username = ?", (username,))
    get_db().commit()


def store_otp(username: str, code: str) -> None:
    get_db().execute(
        "INSERT OR REPLACE INTO otp_codes (username, code, expires_at) VALUES (?, ?, ?)",
        (username, code, time.time() + OTP_TTL)
    )
    get_db().commit()


def verify_and_consume_otp(username: str, code: str) -> bool:
    """Returns True if code matches and is not expired; deletes the record on success."""
    row = get_db().execute(
        "SELECT code, expires_at FROM otp_codes WHERE username = ?", (username,)
    ).fetchone()
    if not row:
        return False
    if time.time() > row["expires_at"]:
        get_db().execute("DELETE FROM otp_codes WHERE username = ?", (username,))
        get_db().commit()
        return False
    if code != row["code"]:
        return False
    get_db().execute("DELETE FROM otp_codes WHERE username = ?", (username,))
    get_db().commit()
    return True


# ── Helpers ───────────────────────────────────────────────────────────────────


def _session_expired() -> bool:
    return (time.time() - session.get("session_created", 0)) > SESSION_TTL


def _send_telegram(text: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT, "text": text}, timeout=5)
        r.raise_for_status()
    except Exception as exc:
        log.error("Telegram send failed: %s", exc)


def _is_admin() -> bool:
    if not bool(session.get("authenticated")) or _session_expired():
        return False
    username = session.get("username")
    if username == ADMIN_USER:
        return True
    row = get_db().execute(
        "SELECT is_admin FROM users WHERE username = ?", (username,)
    ).fetchone()
    return bool(row and row["is_admin"])


def _safe_next(url: str) -> str:
    """Return url only if it's a safe relative path; otherwise empty string."""
    return url if (url and url.startswith("/") and not url.startswith("//")) else ""


def _post_auth_redirect() -> str:
    return session.pop("next_url", None) or "/alwayson/"


# ── Blueprint ─────────────────────────────────────────────────────────────────

bp = Blueprint("auth", __name__, url_prefix="/auth")

# ── Routes ────────────────────────────────────────────────────────────────────


@bp.route("/login")
def login():
    next_url = _safe_next(request.args.get("next", ""))
    if session.get("authenticated") and not _session_expired():
        return redirect(next_url or _post_auth_redirect())
    session.clear()
    if next_url:
        session["next_url"] = next_url
    return render_template("login.html")


@bp.route("/setup-totp")
def setup_totp():
    username = session.get("pending_totp_user")
    if not username:
        return redirect("/auth/login")
    secret = pyotp.random_base32()
    set_totp_secret(username, secret)
    totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name="Home")
    log.info("TOTP setup initiated for user=%s", username)
    return render_template("setup_totp.html", secret=secret, uri=totp_uri, username=username)


@bp.route("/verify-totp", methods=["POST"])
def verify_totp():
    username = session.get("pending_totp_user")
    if not username:
        return jsonify({"error": "Session expired"}), 401

    secret = get_totp_secret(username)
    if not secret:
        return jsonify({"error": "TOTP not set up"}), 401

    code = (request.form.get("code") or "").strip()
    if not code:
        return jsonify({"error": "Code required"}), 400

    if not pyotp.TOTP(secret).verify(code, valid_window=1):
        log.warning("Invalid TOTP attempt for user=%s", username)
        return jsonify({"error": "Invalid code"}), 401

    session["authenticated"] = True
    session["username"] = username
    session["session_created"] = time.time()
    session["auth_method"] = "totp"
    session.permanent = True
    log.info("User authenticated via TOTP: %s", username)
    return jsonify({"ok": True, "redirect": _post_auth_redirect()})


@bp.route("/request-otp", methods=["POST"])
def request_otp():
    username = (request.form.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Username required"}), 400
    if not user_exists(username):
        log.warning("Login attempt by unknown user=%s", username)
        return jsonify({"error": "Unknown user"}), 403
    session["pending_totp_user"] = username
    return jsonify({"ok": True})


@bp.route("/check-totp", methods=["POST"])
def check_totp():
    username = (request.form.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Username required"}), 400
    return jsonify({"has_totp": get_totp_secret(username) is not None})


@bp.route("/send-otp", methods=["POST"])
def send_otp():
    username = session.get("pending_totp_user")
    if not username:
        return jsonify({"error": "Session expired"}), 401
    code = str(random.randint(0, 999999)).zfill(6)
    store_otp(username, code)
    _send_telegram(f"Your code: {code}")
    log.info("OTP sent for user=%s", username)
    return jsonify({"ok": True})


@bp.route("/verify-otp", methods=["POST"])
def verify_otp():
    username = (request.form.get("username") or "").strip()
    otp      = (request.form.get("otp") or "").strip()

    if not verify_and_consume_otp(username, otp):
        # Check if there was any record at all (to give a better error)
        row = get_db().execute(
            "SELECT 1 FROM otp_codes WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            return jsonify({"error": "No code found — request a new one"}), 401
        log.warning("Invalid OTP attempt for user=%s", username)
        return jsonify({"error": "Invalid or expired code"}), 401

    if get_totp_secret(username) is not None:
        session["authenticated"] = True
        session["username"] = username
        session["session_created"] = time.time()
        session["auth_method"] = "telegram"
        session.permanent = True
        log.info("User authenticated via Telegram: %s", username)
        return jsonify({"ok": True, "redirect": _post_auth_redirect()})
    else:
        session["pending_totp_user"] = username
        log.info("First-timer via Telegram, offering TOTP choice: %s", username)
        return jsonify({"ok": True, "redirect": "/auth/totp-choice"})


@bp.route("/totp-choice")
def totp_choice():
    if not session.get("pending_totp_user"):
        return redirect("/auth/login")
    return render_template("totp_choice.html")


@bp.route("/skip-totp", methods=["POST"])
def skip_totp():
    username = session.get("pending_totp_user")
    if not username:
        return jsonify({"error": "Session expired"}), 401
    session["authenticated"] = True
    session["username"] = username
    session["session_created"] = time.time()
    session["auth_method"] = "telegram"
    session.permanent = True
    log.info("User skipped TOTP setup: %s", username)
    return jsonify({"ok": True, "redirect": _post_auth_redirect()})


@bp.route("/admin")
def admin():
    if not _is_admin():
        return redirect("/auth/login")
    users = list_users()
    return render_template("admin.html", users=users, admin_user=ADMIN_USER, version=VERSION)


@bp.route("/admin/add-user", methods=["POST"])
def admin_add_user():
    if not _is_admin():
        return jsonify({"error": "Forbidden"}), 403
    username = (request.form.get("username") or "").strip().lower()
    if not username:
        return jsonify({"error": "Username required"}), 400
    db_add_user(username)
    log.info("Admin added user=%s", username)
    return jsonify({"ok": True})


@bp.route("/admin/remove-user", methods=["POST"])
def admin_remove_user():
    if not _is_admin():
        return jsonify({"error": "Forbidden"}), 403
    username = (request.form.get("username") or "").strip()
    if username == ADMIN_USER:
        return jsonify({"error": "Cannot remove admin"}), 400
    db_remove_user(username)
    log.info("Admin removed user=%s", username)
    return jsonify({"ok": True})


@bp.route("/admin/revoke-totp", methods=["POST"])
def admin_revoke_totp():
    if not _is_admin():
        return jsonify({"error": "Forbidden"}), 403
    username = (request.form.get("username") or "").strip()
    if not username:
        return jsonify({"error": "Username required"}), 400
    delete_totp_secret(username)
    log.info("Admin revoked TOTP for user=%s", username)
    return jsonify({"ok": True})


@bp.route("/admin/set-role", methods=["POST"])
def admin_set_role():
    if not _is_admin():
        return jsonify({"error": "Forbidden"}), 403
    username = (request.form.get("username") or "").strip()
    role     = (request.form.get("role") or "").strip()
    if not username or role not in ("admin", "user"):
        return jsonify({"error": "username and role (admin|user) required"}), 400
    if username == ADMIN_USER:
        return jsonify({"error": "Cannot change primary admin role"}), 400
    db_set_role(username, 1 if role == "admin" else 0)
    log.info("Admin set role=%s for user=%s", role, username)
    return jsonify({"ok": True})


@bp.route("/check")
def auth_check():
    """nginx auth_request subrequest endpoint — returns 200 with X-Auth-User or 401."""
    if session.get("authenticated") and not _session_expired():
        username = session.get("username", "")
        return "", 200, {"X-Auth-User": username}
    return "", 401


@bp.route("/revoke-totp", methods=["POST"])
def revoke_totp():
    username = session.get("username")
    if not username or not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    delete_totp_secret(username)
    session.clear()
    log.info("TOTP revoked for user=%s", username)
    return jsonify({"ok": True})


@bp.route("/logout")
def logout():
    session.clear()
    return redirect("/auth/login")


@bp.route("/version")
def version():
    return jsonify({"version": VERSION, "service": "auth-gateway"})


app.register_blueprint(bp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4001, debug=False)
