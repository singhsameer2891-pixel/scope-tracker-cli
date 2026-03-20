"""Tests for diff_slack.py — Slack message change detection using direct API.

Tests:
    (a) no new messages → returns skipped
    (b) new messages → writes raw file, returns changed
"""

import json
import os
from unittest.mock import patch

import pytest

from scope_tracker.scripts.diff_slack import run


@pytest.fixture
def slack_setup(tmp_path):
    """Create a minimal project structure for Slack diff testing."""
    base_dir = tmp_path / "scope-tracker"
    project_dir = base_dir / "demo"
    system_dir = project_dir / "system"
    system_dir.mkdir(parents=True)

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

    config_path = base_dir / "scope_tracker_config.json"
    config = {
        "projects": [
            {
                "name": "demo",
                "enabled": True,
                "folder": "demo",
                "slack_channel": "demo-scope",
                "sheet_url": "",
                "prd_source": {"type": "google-drive", "url": "", "last_modified": None},
                "slack_last_run_timestamp": "1773901583.351119",
                "run_count": 0,
                "last_run_date": None,
            }
        ]
    }
    config_path.write_text(json.dumps(config))

    return {
        "project_dir": str(project_dir),
        "config_path": str(config_path),
        "system_dir": str(system_dir),
        "base_dir": str(base_dir),
    }


class TestDiffSlackNoNew:
    """Test that no new messages returns skipped."""

    @patch("scope_tracker.scripts.diff_slack.fetch_channel_history")
    @patch("scope_tracker.scripts.diff_slack.resolve_channel_id")
    def test_skipped_when_no_new_messages(self, mock_resolve, mock_history, slack_setup):
        setup = slack_setup
        mock_resolve.return_value = "C123"
        mock_history.return_value = []

        result = run(setup["project_dir"], setup["config_path"], "demo")

        assert result["status"] == "skipped (no new messages)"
        mock_resolve.assert_called_once_with("xoxb-test-token", "demo-scope")
        mock_history.assert_called_once_with("xoxb-test-token", "C123", "1773901583.351119")


class TestDiffSlackNewMessages:
    """Test that new messages writes raw file and returns changed."""

    @patch("scope_tracker.scripts.diff_slack.fetch_channel_history")
    @patch("scope_tracker.scripts.diff_slack.resolve_channel_id")
    def test_changed_with_new_messages(self, mock_resolve, mock_history, slack_setup):
        setup = slack_setup
        mock_resolve.return_value = "C123"
        mock_history.return_value = [
            {
                "ts": "1773910000.000001",
                "thread_ts": "1773910000.000001",
                "user": "U123",
                "text": "Let's descope chart switching for V1",
            },
            {
                "ts": "1773910001.000001",
                "user": "U456",
                "text": "Agreed, pushing to V2",
            },
            {
                "ts": "1773910002.000001",
                "thread_ts": "1773910002.000001",
                "user": "U789",
                "text": "New feature request: dark mode",
            },
        ]

        result = run(setup["project_dir"], setup["config_path"], "demo")

        assert result["status"] == "changed"
        assert result["new_message_count"] == 3
        assert "raw_path" in result
        assert os.path.exists(result["raw_path"])

        # Verify the raw file content
        with open(result["raw_path"]) as f:
            data = json.load(f)
        assert data["new_message_count"] == 3
        assert len(data["threads"]) >= 1

    @patch("scope_tracker.scripts.diff_slack.fetch_thread_replies")
    @patch("scope_tracker.scripts.diff_slack.fetch_channel_history")
    @patch("scope_tracker.scripts.diff_slack.resolve_channel_id")
    def test_re_reads_seen_threads(self, mock_resolve, mock_history, mock_replies, slack_setup):
        """Tests that seen threads are re-read for new replies."""
        setup = slack_setup

        # Write run_state with seen threads
        state_path = os.path.join(setup["system_dir"], "demo_run_state.json")
        with open(state_path, "w") as f:
            json.dump({
                "slack": {
                    "last_run_timestamp": "1773901583.351119",
                    "seen_thread_ids": ["1773900000.000001"],
                }
            }, f)

        mock_resolve.return_value = "C123"
        mock_history.return_value = []  # No new messages
        mock_replies.return_value = [
            {"ts": "1773900000.000001", "user": "U001", "text": "Original thread"},
            {"ts": "1773900000.000002", "user": "U002", "text": "New reply"},
        ]

        result = run(setup["project_dir"], setup["config_path"], "demo")

        # No new messages in history, so result is skipped
        assert result["status"] == "skipped (no new messages)"
        # But thread replies should have been fetched
        mock_replies.assert_called_once_with("xoxb-test-token", "C123", "1773900000.000001")
