"""
test_pipeline_wiring.py - Unit tests for pipeline wiring and fail-closed gate.

Verifies run_pipeline() handling of extract() tuples without requiring Ollama:
  - action "error" -> DENY, executed False
  - action "invalid" -> DENY, executed False
  - extract raising an exception -> DENY, executed False
  - tuple with is_bulk=True and action delete_account -> DENY, executed False
  - tuple with sensitive=True and action view_record -> APPROVAL, executed False
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__) or ".")
import pipeline
from policy import ALLOW, APPROVAL, DENY


class TestPipelineWiring(unittest.TestCase):
    """Test pipeline wiring with monkeypatched extract."""

    @patch("pipeline.extract")
    def test_action_error(self, mock_extract):
        mock_extract.return_value = {
            "action": "error",
            "target": None,
            "resource": None,
            "permission_level": None,
            "requires_approval": True,
            "is_bulk": False,
            "sensitive": False,
        }
        res = pipeline.run_pipeline("broken prompt", log=False)
        self.assertEqual(res["decision"], DENY)
        self.assertFalse(res["executed"])

    @patch("pipeline.extract")
    def test_action_invalid(self, mock_extract):
        mock_extract.return_value = {
            "action": "invalid",
            "target": None,
            "resource": None,
            "permission_level": None,
            "requires_approval": True,
            "is_bulk": False,
            "sensitive": False,
        }
        res = pipeline.run_pipeline("bad format", log=False)
        self.assertEqual(res["decision"], DENY)
        self.assertFalse(res["executed"])

    @patch("pipeline.extract")
    def test_extract_raises_exception(self, mock_extract):
        mock_extract.side_effect = RuntimeError("Ollama connection failed")
        res = pipeline.run_pipeline("any instruction", log=False)
        self.assertEqual(res["decision"], DENY)
        self.assertFalse(res["executed"])

    @patch("pipeline.extract")
    def test_bulk_delete_denied(self, mock_extract):
        mock_extract.return_value = {
            "action": "delete_account",
            "target": "harmless_user",
            "resource": "account",
            "permission_level": None,
            "requires_approval": True,
            "is_bulk": True,
            "sensitive": False,
        }
        res = pipeline.run_pipeline("delete everyone", log=False)
        self.assertEqual(res["decision"], DENY)
        self.assertFalse(res["executed"])

    @patch("pipeline.extract")
    def test_sensitive_view_approval(self, mock_extract):
        mock_extract.return_value = {
            "action": "view_record",
            "target": "harmless_user",
            "resource": "record",
            "permission_level": None,
            "requires_approval": True,
            "is_bulk": False,
            "sensitive": True,
        }
        res = pipeline.run_pipeline("view salary", log=False)
        self.assertEqual(res["decision"], APPROVAL)
        self.assertFalse(res["executed"])


if __name__ == "__main__":
    unittest.main()

