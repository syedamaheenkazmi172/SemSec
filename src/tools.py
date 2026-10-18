"""
tools.py - SemSec backend tools (KAN-19). Owner: Person B.

DUMB executors. Each function performs ONE action on db.py and nothing else.
There is NO authorization in here. A tool runs ONLY after policy.authorize()
returned ALLOW. The untrusted model never calls these directly. This separation
is the whole point of SemSec.

Matches the real db.py (KAN-18): in-memory SQLite, accounts(username, status,
permission_level), access(username, resource), all queries via db.run() with ?
placeholders. Names are lower-cased to match db.py's _name() normalisation.

Each returns {"ok": bool, "detail": str}. Never raises on a business problem.
"""

import db


def _n(name):
    return str(name or "").strip().lower()


def _exists(target):
    return db.get_account(target) is not None


def view_record(target, **kwargs):
    acc = db.get_account(target)
    if not acc:
        return {"ok": False, "detail": f"no such account: {target}"}
    return {"ok": True, "detail": f"{acc['username']}: status={acc['status']}, level={acc['permission_level']}"}


def disable_account(target, **kwargs):
    if not _exists(target):
        return {"ok": False, "detail": f"no such account: {target}"}
    db.run("UPDATE accounts SET status = 'disabled' WHERE username = ?", (_n(target),))
    return {"ok": True, "detail": f"{_n(target)} disabled"}


def enable_account(target, **kwargs):
    if not _exists(target):
        return {"ok": False, "detail": f"no such account: {target}"}
    db.run("UPDATE accounts SET status = 'active' WHERE username = ?", (_n(target),))
    return {"ok": True, "detail": f"{_n(target)} enabled"}


def delete_account(target, **kwargs):
    if not _exists(target):
        return {"ok": False, "detail": f"no such account: {target}"}
    db.run("DELETE FROM accounts WHERE username = ?", (_n(target),))
    db.run("DELETE FROM access WHERE username = ?", (_n(target),))
    return {"ok": True, "detail": f"{_n(target)} deleted"}


def reset_password(target, **kwargs):
    # accounts has no password column in the mock db; this is a no-op success.
    if not _exists(target):
        return {"ok": False, "detail": f"no such account: {target}"}
    return {"ok": True, "detail": f"{_n(target)} password reset"}


def change_permission(target, permission_level=None, **kwargs):
    if not _exists(target):
        return {"ok": False, "detail": f"no such account: {target}"}
    if not permission_level:
        return {"ok": False, "detail": "no permission_level given"}
    db.run("UPDATE accounts SET permission_level = ? WHERE username = ?", (permission_level, _n(target)))
    return {"ok": True, "detail": f"{_n(target)} permission level set to {permission_level}"}


def grant_access(target, resource="a resource", **kwargs):
    db.run("INSERT OR IGNORE INTO access VALUES (?, ?)", (_n(target), resource))
    return {"ok": True, "detail": f"{_n(target)} granted access to {resource}"}


def revoke_access(target, resource=None, **kwargs):
    if resource:
        db.run("DELETE FROM access WHERE username = ? AND resource = ?", (_n(target), resource))
        return {"ok": True, "detail": f"access to {resource} revoked for {_n(target)}"}
    db.run("DELETE FROM access WHERE username = ?", (_n(target),))
    return {"ok": True, "detail": f"all access revoked for {_n(target)}"}


TOOLS = {
    "view_record":       view_record,
    "disable_account":   disable_account,
    "enable_account":    enable_account,
    "delete_account":    delete_account,
    "reset_password":    reset_password,
    "change_permission": change_permission,
    "grant_access":      grant_access,
    "revoke_access":     revoke_access,
}


def run_tool(action, target, permission_level=None, resource=None):
    """Dispatch to the right dumb tool. Call ONLY after a decision of ALLOW."""
    fn = TOOLS.get(action)
    if not fn:
        return {"ok": False, "detail": f"unknown action: {action}"}
    return fn(target, permission_level=permission_level, resource=resource)
