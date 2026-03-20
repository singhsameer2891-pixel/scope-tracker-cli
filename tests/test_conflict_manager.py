"""Tests for conflict_manager.py.

Tests:
(a) no pending conflicts → returns no-pending
(b) conflict with no reply → returns pending unchanged
(c) conflict with reply → applies resolution to sheet and run_state
(d) resolved conflict not re-raised when source unchanged
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from scope_tracker.scripts import conflict_manager


@pytest.fixture
def project_setup(tmp_path):
    """Set up a minimal project structure for testing."""
    base_dir = tmp_path / "scope-tracker"
    project_dir = base_dir / "demo"
    system_dir = project_dir / "system"
    prompts_dir = base_dir / "prompts"
    system_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)

    # Write a minimal conflict_resolve.md prompt
    (prompts_dir / "conflict_resolve.md").write_text("resolve {{CONFLICT_JSON}} {{REPLY_TEXT}} {{OUTPUT_PATH}}")

    # Write .mcp.json with Slack credentials
    mcp_config = {
        "mcpServers": {
            "slack": {
                "command": "npx",
                "args": [],
                "env": {
                    "SLACK_BOT_TOKEN": "xoxb-test-token",
                    "SLACK_TEAM_ID": "T123",
                },
            }
        }
    }
    (base_dir / ".mcp.json").write_text(json.dumps(mcp_config))

    # Write config
    config = {
        "global_settings": {
            "reporting_slack_channel": "scope-tracker",
            "default_timezone": "Asia/Kolkata",
        },
        "sheet_config": {"uat_rounds": 5},
        "projects": [
            {
                "name": "demo",
                "enabled": True,
                "folder": "demo",
                "slack_channel": "demo-scope",
                "sheet_url": "https://docs.google.com/spreadsheets/d/abc123",
                "prd_source": {"type": "google-drive", "url": "https://docs.google.com/document/d/xyz"},
            }
        ],
    }
    config_path = base_dir / "scope_tracker_config.json"
    config_path.write_text(json.dumps(config))

    return {
        "base_dir": str(base_dir),
        "project_dir": str(project_dir),
        "system_dir": str(system_dir),
        "config_path": str(config_path),
        "prompts_dir": str(prompts_dir),
    }


def _write_run_state(system_dir: str, state: dict) -> None:
    """Write a run_state.json file."""
    path = os.path.join(system_dir, "demo_run_state.json")
    with open(path, "w") as f:
        json.dump(state, f)


def _read_run_state(system_dir: str) -> dict:
    """Read the run_state.json file."""
    path = os.path.join(system_dir, "demo_run_state.json")
    with open(path, "r") as f:
        return json.load(f)


class TestNoConflicts:
    """Test case (a): no pending conflicts."""

    def test_no_pending_conflicts(self, project_setup):
        """Returns no-pending when conflicts list is empty."""
        _write_run_state(project_setup["system_dir"], {
            "conflicts": [],
        })

        result = conflict_manager.run(
            project_setup["project_dir"],
            project_setup["config_path"],
            "demo",
        )

        assert result["status"] == "no pending conflicts"

    def test_no_pending_when_all_resolved(self, project_setup):
        """Returns no-pending when all conflicts are resolved."""
        _write_run_state(project_setup["system_dir"], {
            "conflicts": [
                {
                    "id": "PRD:1.3",
                    "resolved": True,
                    "slack_message_ts": "123.456",
                }
            ],
        })

        result = conflict_manager.run(
            project_setup["project_dir"],
            project_setup["config_path"],
            "demo",
        )

        assert result["status"] == "no pending conflicts"


class TestConflictNoReply:
    """Test case (b): conflict with no reply."""

    @patch("scope_tracker.scripts.conflict_manager.resolve_channel_id")
    @patch("scope_tracker.scripts.conflict_manager.fetch_thread_replies")
    def test_pending_unchanged_no_reply(self, mock_replies, mock_resolve, project_setup):
        """Conflict stays pending when no reply found in Slack thread."""
        _write_run_state(project_setup["system_dir"], {
            "conflicts": [
                {
                    "id": "PRD:1.3",
                    "source_a": "PRD",
                    "value_a": "Pushed to V2",
                    "source_b": "Sheet",
                    "value_b": "In Scope",
                    "raised_at": "2026-03-18T09:00:00+05:30",
                    "slack_message_ts": "1773906163.221689",
                    "resolved": False,
                }
            ],
        })

        mock_resolve.return_value = "C999"
        # Return thread with only the original message (no replies)
        mock_replies.return_value = [
            {"ts": "1773906163.221689", "user": "Bot", "text": "Conflict posted"},
        ]

        result = conflict_manager.run(
            project_setup["project_dir"],
            project_setup["config_path"],
            "demo",
        )

        assert result["status"] == "ok"
        assert result["resolved_count"] == 0
        assert result["pending_count"] == 1


class TestConflictWithReply:
    """Test case (c): conflict with reply → applies resolution."""

    @patch("scope_tracker.scripts.conflict_manager.call_llm")
    @patch("scope_tracker.scripts.conflict_manager.resolve_channel_id")
    @patch("scope_tracker.scripts.conflict_manager.fetch_thread_replies")
    def test_resolve_conflict(self, mock_replies, mock_resolve, mock_call_llm, project_setup):
        """Conflict is resolved when reply is found and parsed."""
        _write_run_state(project_setup["system_dir"], {
            "conflicts": [
                {
                    "id": "PRD:1.3",
                    "source_a": "PRD",
                    "value_a": "Pushed to V2",
                    "source_b": "Sheet",
                    "value_b": "In Scope",
                    "raised_at": "2026-03-18T09:00:00+05:30",
                    "slack_message_ts": "1773906163.221689",
                    "resolved": False,
                }
            ],
        })

        mock_resolve.return_value = "C999"
        # Return thread with original message + a reply
        mock_replies.return_value = [
            {"ts": "1773906163.221689", "user": "Bot", "text": "Conflict posted"},
            {"ts": "1773906164.000000", "user": "Sam", "text": "Sheet"},
        ]

        def llm_side_effect(prompt_file, placeholders, cwd, **kwargs):
            output_path = placeholders.get("OUTPUT_PATH", "")
            if "conflict_resolve" in prompt_file:
                resolution = {
                    "resolved": True,
                    "winning_source": "Sheet",
                    "resolved_value": "In Scope",
                    "resolution_text": "Sheet is correct, keeping In Scope",
                    "actor": "Sam",
                }
                with open(output_path, "w") as f:
                    json.dump(resolution, f)
            return ""

        mock_call_llm.side_effect = llm_side_effect

        result = conflict_manager.run(
            project_setup["project_dir"],
            project_setup["config_path"],
            "demo",
        )

        assert result["status"] == "ok"
        assert result["resolved_count"] == 1
        assert result["pending_count"] == 0

        # Verify run_state was updated
        state = _read_run_state(project_setup["system_dir"])
        assert state["conflicts"][0]["resolved"] is True

        # Verify call_llm was only called for conflict_resolve (LLM semantic task)
        mock_call_llm.assert_called_once()
        call_args = mock_call_llm.call_args
        assert "conflict_resolve" in call_args[1].get("prompt_file", "") or "conflict_resolve" in call_args[0][0]


class TestConflictSuppression:
    """Test case (d): resolved conflict not re-raised when source unchanged."""

    def test_resolved_conflict_stays_resolved(self, project_setup):
        """Already resolved conflicts are not processed again."""
        _write_run_state(project_setup["system_dir"], {
            "conflicts": [
                {
                    "id": "PRD:1.3",
                    "source_a": "PRD",
                    "value_a": "Pushed to V2",
                    "source_b": "Sheet",
                    "value_b": "In Scope",
                    "raised_at": "2026-03-18T09:00:00+05:30",
                    "slack_message_ts": "1773906163.221689",
                    "resolved": True,
                    "resolution": "[2026-03-18 Sam via Slack]: Sheet is correct",
                }
            ],
        })

        result = conflict_manager.run(
            project_setup["project_dir"],
            project_setup["config_path"],
            "demo",
        )

        # All conflicts are already resolved
        assert result["status"] == "no pending conflicts"
