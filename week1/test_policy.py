"""
test_policy.py - Unit tests for policy.py authorize() engine. Owner: Person C (KAN-26).

Tests authorize() across:
  1. Role x Action Matrix (admin vs staff vs guest)
  2. 6 Decision Rules from intent.json:
     - Rule 1: Single non-sensitive read (ALLOW), sensitive read (APPROVAL), bulk read (APPROVAL)
     - Rule 2: Reversible single action on another user (ALLOW)
     - Rule 3: Delete single (APPROVAL), bulk delete (DENY)
     - Rule 4: Bulk write (APPROVAL)
     - Rule 5: Privilege escalation to admin (APPROVAL), privilege lowering (ALLOW)
     - Rule 6: Self-action seeking power (DENY), harmless self-action (ALLOW)
  3. Fail-Closed Guarantees:
     - Unknown roles -> DENY
     - Invalid / non-allowed actions -> DENY
     - Malformed / non-dict inputs -> DENY
  4. Decision Logging verification (ts, fields, format)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__) or ".")
from policy import authorize, ALLOW, APPROVAL, DENY, ALLOWED_ACTIONS, clear_log, get_log


class TestPolicyMatrix(unittest.TestCase):
    """Test role ceiling matrix permissions."""

    def test_admin_full_matrix_access(self):
        for action in ALLOWED_ACTIONS:
            res = authorize("admin", {"action": action, "target": "user1"}, log=False)
            self.assertIn(res["decision"], [ALLOW, APPROVAL])
            self.assertNotEqual(res["decision"], DENY)

    def test_staff_matrix_restrictions(self):
        # Staff can do reversible single actions, view, reset, grant, revoke
        res = authorize("staff", {"action": "view_record", "target": "user1"}, log=False)
        self.assertEqual(res["decision"], ALLOW)

        # Staff can NEVER delete_account or change_permission
        res_del = authorize("staff", {"action": "delete_account", "target": "user1"}, log=False)
        self.assertEqual(res_del["decision"], DENY)
        self.assertTrue(any("may not perform" in r for r in res_del["reasons"]))

        res_perm = authorize("staff", {"action": "change_permission", "target": "user1", "permission_level": "viewer"}, log=False)
        self.assertEqual(res_perm["decision"], DENY)

    def test_guest_matrix_restrictions(self):
        # Guest can only view_record and reset_password
        res_view = authorize("guest", {"action": "view_record", "target": "user1"}, log=False)
        self.assertEqual(res_view["decision"], ALLOW)

        res_reset = authorize("guest", {"action": "reset_password", "target": "user1"}, log=False)
        self.assertEqual(res_reset["decision"], ALLOW)

        # Guest cannot do any state modification / account lifecycle actions
        for forbidden in ["disable_account", "enable_account", "delete_account", "change_permission", "grant_access", "revoke_access"]:
            res = authorize("guest", {"action": forbidden, "target": "user1"}, log=False)
            self.assertEqual(res["decision"], DENY, f"Guest should be DENIED for {forbidden}")


class TestPolicyIntentRules(unittest.TestCase):
    """Test the 6 decision rules from intent.json."""

    def test_rule_1_reads(self):
        # Single non-sensitive read -> ALLOW
        res = authorize("admin", {"action": "view_record", "target": "dave"}, log=False)
        self.assertEqual(res["decision"], ALLOW)

        # Sensitive read -> APPROVAL
        res_sens = authorize("admin", {"action": "view_record", "target": "dave salary"}, log=False)
        self.assertEqual(res_sens["decision"], APPROVAL)
        self.assertTrue(res_sens["sensitive"])

        # Bulk read -> APPROVAL
        res_bulk = authorize("admin", {"action": "view_record", "target": "all users"}, log=False)
        self.assertEqual(res_bulk["decision"], APPROVAL)
        self.assertTrue(res_bulk["is_bulk"])

    def test_rule_2_reversible_single_action(self):
        # Reversible action on another user -> ALLOW
        for action in ["disable_account", "enable_account", "reset_password", "grant_access", "revoke_access"]:
            res = authorize("admin", {"action": action, "target": "dave"}, log=False)
            self.assertEqual(res["decision"], ALLOW, f"{action} should be ALLOW")

    def test_rule_3_delete_account(self):
        # Single delete -> APPROVAL
        res_single = authorize("admin", {"action": "delete_account", "target": "dave"}, log=False)
        self.assertEqual(res_single["decision"], APPROVAL)

        # Bulk delete -> DENY
        res_bulk = authorize("admin", {"action": "delete_account", "target": "all inactive"}, log=False)
        self.assertEqual(res_bulk["decision"], DENY)
        self.assertTrue(res_bulk["is_bulk"])

    def test_rule_4_bulk_write(self):
        # Bulk write operations -> APPROVAL
        res = authorize("admin", {"action": "disable_account", "target": "everyone"}, log=False)
        self.assertEqual(res["decision"], APPROVAL)

        res_reset = authorize("admin", {"action": "reset_password", "target": "tamam accounts"}, log=False)
        self.assertEqual(res_reset["decision"], APPROVAL)

    def test_rule_5_permission_changes(self):
        # Promote to admin -> APPROVAL
        res_admin = authorize("admin", {"action": "change_permission", "target": "dave", "permission_level": "admin"}, log=False)
        self.assertEqual(res_admin["decision"], APPROVAL)

        # Demote / privilege down to viewer -> ALLOW
        res_viewer = authorize("admin", {"action": "change_permission", "target": "dave", "permission_level": "viewer"}, log=False)
        self.assertEqual(res_viewer["decision"], ALLOW)

    def test_rule_6_self_actions(self):
        # Self-action seeking power (re-enable self, self-escalate, self-grant) -> DENY
        res_enable = authorize("admin", {"action": "enable_account", "target": "me"}, actor="dave", log=False)
        self.assertEqual(res_enable["decision"], DENY)

        res_escalate = authorize("admin", {"action": "change_permission", "target": "apna", "permission_level": "admin"}, actor="dave", log=False)
        self.assertEqual(res_escalate["decision"], DENY)

        res_grant = authorize("admin", {"action": "grant_access", "target": "mujhe"}, actor="dave", log=False)
        self.assertEqual(res_grant["decision"], DENY)

        # Harmless self-action (reset own password) -> ALLOW
        res_reset = authorize("admin", {"action": "reset_password", "target": "self"}, actor="dave", log=False)
        self.assertEqual(res_reset["decision"], ALLOW)


class TestPolicyFailClosed(unittest.TestCase):
    """Test fail-closed guarantees on bad, unknown, or corrupted data."""

    def test_unknown_role(self):
        for bad_role in ["superuser", "root", "unknown", "", None]:
            res = authorize(bad_role, {"action": "view_record", "target": "dave"}, log=False)
            self.assertEqual(res["decision"], DENY)
            self.assertTrue(any("unknown role" in r for r in res["reasons"]))

    def test_invalid_action(self):
        for bad_action in ["drop_table", "invalid", "error", "format_disk", "", None]:
            res = authorize("admin", {"action": bad_action, "target": "dave"}, log=False)
            self.assertEqual(res["decision"], DENY)
            self.assertTrue(any("unknown/invalid action" in r for r in res["reasons"]))

    def test_malformed_tuple(self):
        for bad_tup in [None, "not a dict", 123, []]:
            res = authorize("admin", bad_tup, log=False)
            self.assertEqual(res["decision"], DENY)


class TestPolicyLogging(unittest.TestCase):
    """Test in-memory decision logging."""

    def setUp(self):
        clear_log()

    def test_logging_records_entry(self):
        self.assertEqual(len(get_log()), 0)
        res = authorize("admin", {"action": "view_record", "target": "dave"}, log=True)
        log = get_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["decision"], res["decision"])
        self.assertEqual(log[0]["action"], "view_record")
        self.assertIn("ts", log[0])


if __name__ == "__main__":
    unittest.main()
