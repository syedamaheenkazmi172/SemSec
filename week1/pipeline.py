"""
pipeline.py - SemSec pipeline. Owner: Irab.  (KAN-27)

Connects the three parts into one call:

    instruction --extract()--> tuple --authorize()--> decision --run_tool()--> result
                  (untrusted)            (decides)               (ONLY on ALLOW)

    run_pipeline(instruction, role="admin", actor="me", execute=True, log=True) -> dict
        {"instruction", "role", "tuple", "policy", "decision",
         "executed", "tool_result"}

    decide(tup, role, ...)  does steps 2 and 3 on a tuple you already have,
                            so the gate can be tested without a model.

Fail closed: if any step crashes, the decision is DENY and no tool runs.
A tool runs only when the decision is exactly "ALLOW".

execute=False  -> decide only, never touch the database (used by eval.py).
log=False      -> do not write decision_log.jsonl (used by tests and eval.py).
"""

from extractor import extract
from policy import authorize
import tools

ALLOW, APPROVAL, DENY = "ALLOW", "APPROVAL", "DENY"


def _error_tuple():
    """Same safe tuple extractor.py returns on failure. policy.py DENIES it."""
    return {"action": "error", "target": None, "resource": None,
            "permission_level": None, "requires_approval": True}


def decide(tup, role, actor="me", execute=True, log=True):
    """Steps 2 and 3: authorize the tuple, then run the tool ONLY on ALLOW."""
    try:
        policy = authorize(role, tup, actor=actor, log=log)
        if not isinstance(policy, dict):            # policy must return a dict
            raise TypeError("policy returned a non-dict")
    except Exception as e:                          # policy crashed -> deny
        policy = {"decision": DENY,
                  "reasons": [f"policy crashed: {type(e).__name__} (fail closed)"]}

    decision = policy.get("decision")
    if decision not in (ALLOW, APPROVAL, DENY):     # anything unexpected -> deny
        decision = DENY

    tool_result = None
    if decision == ALLOW and execute:
        try:
            tool_result = tools.run_tool(tup.get("action"), tup.get("target"),
                                         permission_level=tup.get("permission_level"),
                                         resource=tup.get("resource"))
        except Exception as e:
            tool_result = {"ok": False, "detail": f"tool crashed: {type(e).__name__}"}

    return {"tuple": tup, "policy": policy, "decision": decision,
            "executed": tool_result is not None, "tool_result": tool_result}


def run_pipeline(instruction, role="admin", actor="me", execute=True, log=True):
    """Full path: instruction -> extract -> authorize -> (tool on ALLOW)."""
    try:
        tup = extract(instruction)
    except Exception:                               # extract() never raises, but be safe
        tup = _error_tuple()
    if not isinstance(tup, dict):                   # extract() must return a dict
        tup = _error_tuple()

    result = decide(tup, role, actor=actor, execute=execute, log=log)
    result["instruction"] = instruction
    result["role"] = role
    return result


if __name__ == "__main__":
    import db

    db.init_db()
    for name in ("zain", "zahid", "test account"):
        db.run("INSERT INTO accounts (username) VALUES (?)", (name,))

    print("--- gate test on fake tuples (no model needed) ---")
    checks = [   # label, tuple, role, expected decision, tool expected to run?
        ("single read",      {"action": "view_record", "target": "zain"}, "admin", "ALLOW", True),
        ("promote to admin", {"action": "change_permission", "target": "zain",
                              "permission_level": "admin"}, "admin", "APPROVAL", False),
        ("bulk delete",      {"action": "delete_account", "target": "everyone"}, "admin", "DENY", False),
        ("self enable",      {"action": "enable_account", "target": "me"}, "staff", "DENY", False),
        ("staff deletes",    {"action": "delete_account", "target": "zahid"}, "staff", "DENY", False),
        ("model error",      {"action": "error", "target": None}, "admin", "DENY", False),
    ]
    for label, tup, role, want, want_ran in checks:
        r = decide(tup, role, log=False)
        ok = r["decision"] == want and r["executed"] == want_ran
        print(f"{'PASS' if ok else 'FAIL'}  {label:18} role={role:6} -> {r['decision']:8} executed={r['executed']}")

    untouched = (db.get_account("zain")["permission_level"] == "viewer"
                 and db.get_account("zahid") is not None)
    print(f"{'PASS' if untouched else 'FAIL'}  database unchanged by blocked actions")

    print("\n--- end-to-end with the real model (needs Ollama running) ---")
    samples = [
        "Make zain an admin.",
        "Zain ko admin rights de do please.",
        "Show me zain's record.",
        "Mujhe admin bana do.",
        "Test account delete mat karna.",
    ]
    for s in samples:
        r = run_pipeline(s, role="admin", log=False)
        t = r["tuple"]
        print(f"{s:36} -> {t['action']} | {t['target']} | {r['decision']} | executed={r['executed']}")