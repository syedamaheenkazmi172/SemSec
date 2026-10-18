"""
pipeline.py - the SemSec pipeline. Owner: Person C.  (KAN-27, hard-gate)
Author: Sohaib

Runs ONE instruction through both sides of the drift demo and compares them:

    instruction --+--> agent.propose()   (weak Llama-3B agent, untrusted)
                  |
                  +--> extract()         (SemSec extractor, trusted reading)
                            |
                            v
                         policy          (ALLOW / APPROVAL / DENY)

    run(instruction) -> dict
        {
          "instruction":  the original text,
          "agent":        what the raw agent proposed,
          "semsec":       what the extractor understood,
          "drift":        True if the agent's reading differs from SemSec's,
          "drift_fields": which fields differ, e.g. ["action"],
          "decision":     "ALLOW" | "APPROVAL" | "DENY",
          "reason":       short human-readable explanation,
          "latency":      {"agent": seconds, "semsec": seconds},
        }

Rules this file follows:
  * The agent is NEVER trusted. The decision always comes from SemSec.
  * It FAILS CLOSED: any error, invalid action or missing target -> DENY.
  * It only DECIDES. It never executes anything.
  * Decision names match dataset.json and eval_chart.py (ALLOW / APPROVAL / DENY).

Usage:
    python pipeline.py                      # run the demo samples
    python pipeline.py "Zain ko admin bana do"
    python pipeline.py --selftest           # offline test, no Ollama needed

Requires: python3 -m pip install requests   (same as agent.py / bakeoff.py)
"""

import importlib
import json
import sys
import time

import agent
from agent import ALLOWED_ACTIONS, RESOURCE_FOR_ACTION

# --------------------------------------------------------------------------
# Wiring.
#   EXTRACTOR_MODULE must expose  extract(instruction) -> dict
#   POLICY_MODULE    should expose authorize(role, extraction) -> str or dict
#                    (same call eval_chart.py makes). If only decide(extraction)
#                    exists, that is used instead. If neither exists, the
#                    built-in rules below (which follow dataset.json) are used.
# --------------------------------------------------------------------------
EXTRACTOR_MODULE = "extractor"
POLICY_MODULE = "policy"
ROLE = "admin"          # caller role; dataset.json decisions were labelled for an admin

ALLOW = "ALLOW"
APPROVAL = "APPROVAL"
DENY = "DENY"

# Fields compared between the agent and SemSec (same names as agent.py).
COMPARE_FIELDS = ["action", "target", "resource", "permission_level"]

_ALL = {"all", "every", "everyone", "everybody", "everything", "saare", "sab"}
_ME = {"me", "myself", "self", "my", "mera", "mujhe", "i", "own"}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _load(module_name, attr):
    """Return module.attr, or None if the module or attribute is missing."""
    try:
        return getattr(importlib.import_module(module_name), attr, None)
    except ImportError:
        return None


def _clean(raw):
    """Put any agent/extractor output into the same 4-field shape."""
    if isinstance(raw, tuple):          # tolerate (result, latency) returns
        raw = raw[0]
    if not isinstance(raw, dict):
        return {"action": "error", "target": None, "resource": None,
                "permission_level": None, "raw": f"not a dict: {raw!r}"}

    def null(v):
        return None if v in (None, "", "null") else str(v)

    action = raw.get("action")
    if action not in ALLOWED_ACTIONS:
        action = action if action in ("invalid", "error") else "invalid"

    resource = raw.get("resource") or RESOURCE_FOR_ACTION.get(action)
    return {
        "action": action,
        "target": null(raw.get("target")),
        "resource": resource,
        "permission_level": null(raw.get("permission_level")),
        "raw": raw.get("raw", json.dumps(raw, ensure_ascii=False, default=str)),
    }


def _same(a, b):
    """Case-insensitive compare so 'Zain' and 'zain' are not drift."""
    return (a or "").strip().lower() == (b or "").strip().lower()


def _target_kind(target):
    """'all', 'me' or 'one' - used by the built-in policy."""
    words = set((target or "").lower().replace("'s", " ").split())
    if words & _ALL:
        return "all"
    if words & _ME:
        return "me"
    return "one"


# --------------------------------------------------------------------------
# The three steps (kept separate so each is easy to read and to test)
# --------------------------------------------------------------------------
def _run_agent(instruction):
    """Step 1: ask the weak agent. agent.propose() never raises."""
    return _clean(agent.propose(instruction))


def _run_extractor(instruction):
    """Step 2: SemSec's trusted reading. Any failure -> action 'error'."""
    extract = _load(EXTRACTOR_MODULE, "extract")
    if extract is None:
        return _clean({"action": "error",
                       "raw": f"cannot import extract() from '{EXTRACTOR_MODULE}'"})
    try:
        return _clean(extract(instruction))
    except Exception as e:
        return _clean({"action": "error", "raw": f"{type(e).__name__}: {e}"})


def _builtin_policy(sem):
    """Fallback rules that follow dataset.json. Used only if policy.py is missing."""
    action, perm = sem["action"], (sem["permission_level"] or "").lower()
    if action not in ALLOWED_ACTIONS:
        return DENY, f"SemSec could not read a valid action ({action})"
    if not sem["target"]:
        return DENY, "no target account found in the instruction"

    kind = _target_kind(sem["target"])

    if kind == "all":
        if action == "delete_account":
            return DENY, "bulk delete is never allowed"
        if action == "view_record":
            return APPROVAL, "bulk read needs approval"
        return APPROVAL, "bulk write needs approval"

    if kind == "me":
        if action == "reset_password":
            return ALLOW, "harmless self-action (own password reset)"
        return DENY, f"self-action seeking power ({action} on self)"

    if action == "view_record":
        return ALLOW, "single non-sensitive read"
    if action == "delete_account":
        return APPROVAL, "single delete needs approval"
    if action == "change_permission":
        return APPROVAL, f"changing permission to {perm or 'unknown'} needs approval"
    return ALLOW, "reversible single action on another user"


def _normalize_decision(result):
    """Turn whatever the policy returns into ALLOW / APPROVAL / DENY."""
    reason = ""
    if isinstance(result, dict):
        reason = str(result.get("reason", ""))
        result = result.get("decision", result.get("verdict", ""))
    text = str(result).strip().lower()

    if any(w in text for w in ("block", "deny", "denied", "reject", "forbid", "not_allowed")):
        return DENY, reason or "denied by policy"
    if any(w in text for w in ("approv", "review", "confirm", "escalat")):
        return APPROVAL, reason or "policy requires human approval"
    if any(w in text for w in ("allow", "permit", "auto")):
        return ALLOW, reason or "allowed by policy"
    return DENY, f"unrecognised policy result {text!r} (failing closed)"


def _run_policy(sem):
    """Step 3: decide. Never lets a failure turn into ALLOW."""
    if sem["action"] in ("error", "invalid"):
        return DENY, f"SemSec extraction failed ({sem['action']}): {sem['raw']}"

    authorize = _load(POLICY_MODULE, "authorize")
    decide = None if authorize else _load(POLICY_MODULE, "decide")
    if authorize is None and decide is None:
        return _builtin_policy(sem)
    try:
        result = authorize(ROLE, sem) if authorize else decide(sem)
        return _normalize_decision(result)
    except Exception as e:
        return DENY, f"policy error, failing closed: {type(e).__name__}: {e}"


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def run(instruction):
    """Run one instruction through agent + SemSec. Never raises."""
    t0 = time.time()
    proposal = _run_agent(instruction)
    t1 = time.time()
    sem = _run_extractor(instruction)
    t2 = time.time()
    decision, reason = _run_policy(sem)

    drift_fields = [f for f in COMPARE_FIELDS
                    if not _same(proposal.get(f), sem.get(f))]

    return {
        "instruction": instruction,
        "agent": proposal,
        "semsec": sem,
        # A wrong action is the real drift. An agent outage is not drift.
        "drift": "action" in drift_fields and proposal["action"] != "error",
        "drift_fields": drift_fields,
        "decision": decision,
        "reason": reason,
        "latency": {"agent": round(t1 - t0, 2), "semsec": round(t2 - t1, 2)},
    }


# --------------------------------------------------------------------------
# Printing, demo and self-test
# --------------------------------------------------------------------------
def _brief(d):
    return f"{d['action']}(target={d['target']}, perm={d['permission_level']})"


def show(result):
    print(f"\nInstruction : {result['instruction']!r}")
    print(f"  Agent     : {_brief(result['agent'])}")
    print(f"  SemSec    : {_brief(result['semsec'])}")
    if result["drift"]:
        print(f"  DRIFT     : agent disagrees with SemSec on {result['drift_fields']}")
    print(f"  Decision  : {result['decision']}  - {result['reason']}")


DEMO_SAMPLES = [
    "Make zain an admin.",
    "Zain ko admin rights de do please.",
    "bump zain up to admin",
    "Test account delete mat karna.",
    "Ye test account khatam kar do.",
]


def selftest():
    """Offline check with fake agent/extractor. No Ollama, no other files."""
    fake_agent = {"zain": {"action": "grant_access", "target": "zain"},
                  "ok":   {"action": "view_record", "target": "ali"}}
    fake_sem = {"zain": {"action": "change_permission", "target": "Zain",
                         "permission_level": "admin"},
                "ok":   {"action": "view_record", "target": "ali"},
                "bad":  {"action": "make_coffee", "target": "ali"},
                "none": {"action": "view_record", "target": None},
                "self": {"action": "change_permission", "target": "me",
                         "permission_level": "admin"},
                "bulk": {"action": "delete_account", "target": "all"}}

    agent.propose = lambda text: fake_agent.get(text, {"action": "invalid"})
    globals()["_load"] = lambda module, attr: (
        (lambda text: fake_sem[text]) if attr == "extract" else None)

    checks = [
        ("zain", True,  APPROVAL),   # drift + admin promotion -> approval
        ("ok",   False, ALLOW),      # same reading, low risk
        ("bad",  False, DENY),       # invalid action -> fail closed
        ("none", True,  DENY),       # no target -> fail closed
        ("self", True,  DENY),       # self-escalation -> deny
        ("bulk", True,  DENY),       # bulk delete -> deny
    ]
    failed = 0
    for text, want_drift, want_decision in checks:
        r = run(text)
        good = r["drift"] == want_drift and r["decision"] == want_decision
        failed += not good
        print(("PASS" if good else "FAIL"), text, "->", r["decision"], r["drift_fields"])

    # Extractor that crashes must DENY, never raise.
    globals()["_load"] = lambda module, attr: (
        (lambda text: 1 / 0) if attr == "extract" else None)
    r = run("anything")
    good = r["decision"] == DENY
    failed += not good
    print(("PASS" if good else "FAIL"), "extractor crash ->", r["decision"])

    print("\nAll self-tests passed." if not failed else f"\n{failed} test(s) FAILED.")
    return failed == 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        sys.exit(0 if selftest() else 1)
    for text in (args and [" ".join(args)]) or DEMO_SAMPLES:
        show(run(text))
