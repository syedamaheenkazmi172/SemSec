# SemSec Contracts (FROZEN)

Changing anything here needs agreement from all 4 members.

## Actions and resources

| action | resource |
|---|---|
| view_record | record |
| disable_account | account |
| enable_account | account |
| delete_account | account |
| reset_password | password |
| change_permission | permission |
| grant_access | access |
| revoke_access | access |

Roles: `admin`, `staff`, `guest`. Decisions: `ALLOW`, `APPROVAL`, `DENY`.

## 1. extract(instruction) -> dict   (week1/extractor.py)

Input: one sentence in any language or style. Never raises.

    {"action": "<one of the 8 actions above>",
     "target": "<the account / user the action applies to>",
     "resource": "account | permission | record | password | access",
     "permission_level": "<string or null; only for change_permission>",
     "requires_approval": true}

If the model output is unusable, action is "invalid" (not one of the 8) or
"error" (model unreachable / bad JSON). policy.py DENIES both.

## 2. authorize(role, tup, actor=None, log=True) -> dict   (week1/policy.py)

Input: the role and the dict from extract(). No LLM inside. Never raises.

    {"decision", "reasons", "role", "action", "target", "resource",
     "permission_level", "is_self", "is_bulk", "sensitive", "ts"}

decision is ALLOW, APPROVAL or DENY.

## 3. propose(instruction) -> dict   (week1/agent.py)

The weak agent. It only proposes, it never authorizes or executes.

    {"action", "target", "resource", "permission_level", "raw"}

## 4. db.py   (week1/db.py)

In-memory SQLite with tables users(username, role),
accounts(username, status, permission_level), access(username, resource).
Functions: init_db(), run(sql, params), get_user_role(name),
get_account(name), list_accounts(). Queries always use ? placeholders.

## 5. run_pipeline(instruction, role="admin", actor="me", execute=True, log=True) -> dict   (week1/pipeline.py)

instruction -> extract() -> authorize() -> tools.run_tool() (only on ALLOW).
Never raises. Any crash means DENY and no tool runs.

    {"instruction", "role", "tuple", "policy", "decision", "executed", "tool_result"}

"tuple" is the dict from extract(), "policy" is the dict from authorize(),
"decision" is ALLOW, APPROVAL or DENY, "executed" is true only if a tool ran.
execute=False decides without touching the database (used by eval.py).
log=False skips writing decision_log.jsonl.

tools.run_tool(action, target, permission_level=None, resource=None)
-> {"ok": bool, "detail": str}   (week1/tools.py). Call it only after ALLOW.

## Rules

1. The model's output is untrusted. Only policy.py decides.
2. Anything unknown, invalid or failing is DENIED.