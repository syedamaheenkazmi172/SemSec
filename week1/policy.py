"""
policy.py - SemSec reference monitor (deterministic policy engine). Owner: Person C.  (KAN-25)

Takes the canonical tuple from extract() plus the caller's role and returns a
decision: ALLOW / APPROVAL / DENY. No LLM in here - same input, same output.

    authorize(role, tup, actor=None) -> dict
        {"decision", "reasons", "role", "action", "target", "resource",
         "permission_level", "is_self", "is_bulk", "sensitive", "ts"}

Decision = the MOST RESTRICTIVE of:
    1. role x action matrix   (can this role ever do this action?)
    2. intent rules           (the 6 decision_rules in intent.json)
    3. extractor's requires_approval flag (only if HONOR_EXTRACTOR_APPROVAL;
       can only raise ALLOW -> APPROVAL, never lower a decision)
Fail closed: unknown role, unknown/invalid/error action -> DENY.

Every call is written to the decision log (in memory + decision_log.jsonl).

Names follow bakeoff.py (ALLOWED_ACTIONS, RESOURCE_FOR_ACTION, RISKY_ACTIONS).
"""

import json
import time

ALLOWED_ACTIONS = [
    "view_record", "disable_account", "enable_account", "delete_account",
    "reset_password", "change_permission", "grant_access", "revoke_access",
]

RESOURCE_FOR_ACTION = {
    "view_record": "record",
    "disable_account": "account",
    "enable_account": "account",
    "delete_account": "account",
    "reset_password": "password",
    "change_permission": "permission",
    "grant_access": "access",
    "revoke_access": "access",
}

RISKY_ACTIONS = {"delete_account", "disable_account", "change_permission",
                 "grant_access", "revoke_access", "reset_password"}

ALLOW, APPROVAL, DENY = "ALLOW", "APPROVAL", "DENY"

# The LLM's own requires_approval flag is UNTRUSTED model output. In the bake-off
# prompt it is set to true on almost every example, so honoring it blindly turns
# every decision into APPROVAL and hides the ALLOW cases defined in intent.json.
# Default False: the deterministic rules decide. Set True only once extractor.py
# sets the flag for genuinely ambiguous / negated / unsupported inputs.
HONOR_EXTRACTOR_APPROVAL = False
_SEVERITY = {ALLOW: 0, APPROVAL: 1, DENY: 2}

# ---------------------------------------------------------------------------
# 1. Role x action matrix: the CEILING for each role.
#    "ALLOW" = role may attempt it (rules below still apply); "DENY" = never.
# ---------------------------------------------------------------------------
ROLES = ["admin", "staff", "guest"]

ROLE_MATRIX = {
    #                 view  disable enable delete reset  perm   grant  revoke
    "admin": dict(view_record=ALLOW, disable_account=ALLOW, enable_account=ALLOW,
                  delete_account=ALLOW, reset_password=ALLOW, change_permission=ALLOW,
                  grant_access=ALLOW, revoke_access=ALLOW),
    "staff": dict(view_record=ALLOW, disable_account=ALLOW, enable_account=ALLOW,
                  delete_account=DENY, reset_password=ALLOW, change_permission=DENY,
                  grant_access=ALLOW, revoke_access=ALLOW),
    "guest": dict(view_record=ALLOW, disable_account=DENY, enable_account=DENY,
                  delete_account=DENY, reset_password=ALLOW, change_permission=DENY,
                  grant_access=DENY, revoke_access=DENY),
}

# ---------------------------------------------------------------------------
# Scope detection helpers. Preferred: extractor supplies is_self / is_bulk /
# sensitive in the tuple. Fallback: simple keyword heuristics on `target`.
# ---------------------------------------------------------------------------
SELF_WORDS = {"me", "myself", "self", "mujhe", "mera", "meri", "apna", "apne", "khud"}
BULK_WORDS = {"everyone", "everybody", "all", "team", "group", "sab", "sabko", "sabhi",
              "all users", "all accounts", "inactive", "everyone's", "tamam"}
SENSITIVE_WORDS = {"salary", "payroll", "password hash", "hash", "ssn", "bank",
                   "finance", "medical", "confidential", "guest", "external"}
LOWER_LEVELS = {"viewer", "view", "read", "read-only", "readonly", "guest", "none", "no access"}


def _words(text):
    return str(text or "").lower().replace("-", " ").replace("_", " ")


def _is_self(tup, actor):
    if "is_self" in tup and tup["is_self"] is not None:
        return bool(tup["is_self"])
    tgt = str(tup.get("target") or "").strip().lower()
    return bool(tgt) and (tgt in SELF_WORDS or (actor is not None and tgt == str(actor).lower()))


def _is_bulk(tup):
    if "is_bulk" in tup and tup["is_bulk"] is not None:
        return bool(tup["is_bulk"])
    tgt = _words(tup.get("target"))
    return any(w in tgt.split() or w == tgt for w in BULK_WORDS)


def _is_sensitive(tup):
    if "sensitive" in tup and tup["sensitive"] is not None:
        return bool(tup["sensitive"])
    tgt = _words(tup.get("target"))
    return any(w in tgt for w in SENSITIVE_WORDS)


# ---------------------------------------------------------------------------
# 2. Intent rules (from intent.json decision_rules). Returns (decision, reason).
# ---------------------------------------------------------------------------
def _rule_decision(action, perm, is_self, is_bulk, sensitive):
    # Rule 6: self-action seeking power = DENY
    if is_self and action in ("enable_account", "grant_access"):
        return DENY, "R6 self power-seeking (self enable/grant)"
    if is_self and action == "change_permission" and not _is_lower(perm):
        return DENY, "R6 self-escalation"

    if action == "view_record":                                   # Rule 1
        if is_bulk:
            return APPROVAL, "R1 bulk read"
        if sensitive:
            return APPROVAL, "R1 sensitive read"
        return ALLOW, "R1 single read"

    if action == "delete_account":                                # Rule 3
        return (DENY, "R3 bulk delete") if is_bulk else (APPROVAL, "R3 delete single")

    if is_bulk:                                                   # Rule 4
        return APPROVAL, "R4 bulk write"

    if action == "change_permission":                             # Rule 5
        if _is_lower(perm):
            return ALLOW, "privilege down"
        if str(perm or "").lower() == "admin":
            return APPROVAL, "R5 raise to admin"
        return APPROVAL, "privilege up / unknown level (conservative)"

    if action == "grant_access" and sensitive:
        return APPROVAL, "R1 sensitive grant"

    if is_self and action in ("disable_account",):
        return APPROVAL, "self-disable not in catalog (conservative)"

    return ALLOW, "R2 reversible single action"                   # Rule 2


def _is_lower(perm):
    return str(perm or "").lower().replace(" ", "-") in LOWER_LEVELS or _words(perm) in LOWER_LEVELS


def _worst(a, b):
    return a if _SEVERITY[a] >= _SEVERITY[b] else b


# ---------------------------------------------------------------------------
# Decision logger
# ---------------------------------------------------------------------------
LOG_PATH = "decision_log.jsonl"   # set to None to disable file logging
DECISION_LOG = []                 # in-memory log, read by the Streamlit dashboard


def log_decision(entry):
    DECISION_LOG.append(entry)
    if LOG_PATH:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass  # logging must never break authorization
    return entry


def get_log():
    return list(DECISION_LOG)


def clear_log():
    DECISION_LOG.clear()


# ---------------------------------------------------------------------------
# 3. authorize()
# ---------------------------------------------------------------------------
def authorize(role, tup, actor=None, log=True):
    """Return the policy decision for `tup` made by `role`. Never raises."""
    tup = tup if isinstance(tup, dict) else {}
    action = tup.get("action")
    perm = tup.get("permission_level")
    reasons = []

    is_self = _is_self(tup, actor)
    is_bulk = _is_bulk(tup)
    sensitive = _is_sensitive(tup)

    role_key = str(role or "").lower()
    if role_key not in ROLE_MATRIX:
        decision = DENY
        reasons.append(f"unknown role {role!r} (fail closed)")
    elif action not in ALLOWED_ACTIONS:
        decision = DENY
        reasons.append(f"unknown/invalid action {action!r} (fail closed)")
    else:
        decision = ALLOW
        # 1. role matrix
        if ROLE_MATRIX[role_key][action] == DENY:
            decision = DENY
            reasons.append(f"role '{role_key}' may not perform {action}")
        # 2. intent rules
        rule_dec, rule_reason = _rule_decision(action, perm, is_self, is_bulk, sensitive)
        decision = _worst(decision, rule_dec)
        reasons.append(rule_reason)
        # 3. extractor's own flag can only make it stricter
        if HONOR_EXTRACTOR_APPROVAL and tup.get("requires_approval") is True and decision == ALLOW:
            decision = APPROVAL
            reasons.append("extractor set requires_approval (fail closed)")

    result = {
        "decision": decision,
        "reasons": reasons,
        "role": role_key or role,
        "action": action,
        "target": tup.get("target"),
        "resource": RESOURCE_FOR_ACTION.get(action),
        "permission_level": perm,
        "is_self": is_self,
        "is_bulk": is_bulk,
        "sensitive": sensitive,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if log:
        log_decision(result)
    return result


if __name__ == "__main__":
    LOG_PATH = None
    demo = [
        ("admin", {"action": "change_permission", "target": "zain", "permission_level": "admin"}),
        ("admin", {"action": "grant_access", "target": "zain"}),
        ("staff", {"action": "delete_account", "target": "testacc"}),
        ("admin", {"action": "delete_account", "target": "all inactive"}),
        ("guest", {"action": "view_record", "target": "ali"}),
        ("admin", {"action": "invalid", "target": None}),
    ]
    for role, t in demo:
        r = authorize(role, t, log=False)
        print(f"{role:6} {t['action']:18} {str(t.get('target')):14} -> {r['decision']:8} {r['reasons']}")
