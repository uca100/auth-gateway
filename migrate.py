#!/usr/bin/env python3
"""
migrate.py — one-time migration from alwayson JSON files to auth-gateway SQLite DB.

Usage:
    python migrate.py \
        --users /home/uri/alwayson_allowed.json \
        --totp  /home/uri/alwayson_totp.json \
        --db    /home/uri/auth_gateway.db
"""

import argparse
import json
import os
import sqlite3


def main():
    parser = argparse.ArgumentParser(description="Migrate alwayson JSON data to auth-gateway SQLite")
    parser.add_argument("--users", default="/home/uri/alwayson_allowed.json")
    parser.add_argument("--totp",  default="/home/uri/alwayson_totp.json")
    parser.add_argument("--db",    default="/home/uri/auth_gateway.db")
    args = parser.parse_args()

    if os.path.exists(args.db):
        print(f"Database already exists at {args.db} — migration skipped.")
        print("Delete it first if you want to re-run migration.")
        return

    conn = sqlite3.connect(args.db)
    conn.executescript("""
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
    conn.commit()

    users = []
    if os.path.exists(args.users):
        with open(args.users) as f:
            users = json.load(f)
        print(f"Loaded {len(users)} users from {args.users}")
    else:
        print(f"No users file at {args.users} — starting with empty user list")

    totp_secrets = {}
    if os.path.exists(args.totp):
        with open(args.totp) as f:
            totp_secrets = json.load(f)
        print(f"Loaded {len(totp_secrets)} TOTP secrets from {args.totp}")
    else:
        print(f"No TOTP file at {args.totp} — no secrets to migrate")

    for username in users:
        secret = totp_secrets.get(username)
        conn.execute(
            "INSERT OR IGNORE INTO users (username, totp_secret) VALUES (?, ?)",
            (username, secret)
        )

    # Import any TOTP secrets for users not in the allowed list
    for username, secret in totp_secrets.items():
        if username not in users:
            conn.execute(
                "INSERT OR IGNORE INTO users (username, totp_secret) VALUES (?, ?)",
                (username, secret)
            )

    conn.commit()

    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"\nMigration complete: {count} users written to {args.db}")

    os.chmod(args.db, 0o600)
    conn.close()


if __name__ == "__main__":
    main()
