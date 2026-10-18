"""
db.py - the mock database. Owner: Irab.  (KAN-18)

In-memory SQLite: it lives while the program runs and resets on restart,
so every demo starts clean. Three tables:
    users    - who is TALKING to the system (the caller) and their role
    accounts - the things actions are applied TO
    access   - which account has access to which resource

SECURITY NOTE: every query uses ? placeholders, never f-strings, so a name like
"x'; DROP TABLE accounts;--" is treated as plain text (no SQL injection).
"""

import sqlite3

_conn = sqlite3.connect(":memory:", check_same_thread=False)
_conn.row_factory = sqlite3.Row


def init_db():
    """Create empty tables. Calling it again wipes everything (basically a reset)."""
    _conn.executescript("""
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS accounts;
        DROP TABLE IF EXISTS access;

        CREATE TABLE users (
            username TEXT PRIMARY KEY,
            role     TEXT NOT NULL CHECK (role IN ('admin', 'staff', 'guest'))
        );
        CREATE TABLE accounts (
            username         TEXT PRIMARY KEY,
            status           TEXT NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active', 'disabled')),
            permission_level TEXT NOT NULL DEFAULT 'viewer'
        );
        CREATE TABLE access (
            username TEXT NOT NULL,
            resource TEXT NOT NULL,
            PRIMARY KEY (username, resource)
        );
    """)
    _conn.commit()


def run(sql, params=()):
    """Run one query. Returns a list of dicts (empty for INSERT/UPDATE/DELETE)."""
    cur = _conn.execute(sql, params)
    _conn.commit()
    return [dict(row) for row in cur.fetchall()]


def _name(username):
    return str(username).strip().lower()


def get_user_role(username):
    """Role of a caller ('admin' / 'staff' / 'guest'), or None if unknown."""
    rows = run("SELECT role FROM users WHERE username = ?", (_name(username),))
    return rows[0]["role"] if rows else None


def get_account(username):
    """One account as a dict, or None if it does not exist."""
    rows = run("SELECT * FROM accounts WHERE username = ?", (_name(username),))
    return rows[0] if rows else None


def list_accounts():
    return run("SELECT * FROM accounts ORDER BY username")


init_db()   # ready to use as soon as it is imported


if __name__ == "__main__":
    run("INSERT INTO users VALUES (?, ?)", ("alice", "admin"))
    run("INSERT INTO accounts (username) VALUES (?)", ("zara",))
    print("role of Alice :", get_user_role("Alice"))
    print("zara         :", get_account("ZARA"))
    print("nobody        :", get_account("nobody"))
    print("injection     :", get_account("x'; DROP TABLE accounts;--"))
    print("accounts still exist:", list_accounts())