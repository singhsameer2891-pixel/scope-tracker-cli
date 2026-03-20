"""Tests for diff_slack.py — Slack message change detection.

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
    project_dir = tmp_path / "demo"
    system_dir = project_dir / "system"
    system_dir.mkdir(parents=True)

    scope_root = tmp_path
    prompts_dir = scope_root / "prompts"
    prompts_dir.mkdir(exist_ok=True)

    (prompts_dir / "slack_fetch.md").write_text(
        "Fetch Slack for {{CHANNEL}} after {{WATERMARK_TS}}"
    )

    config_path = scope_root / "scope_tracker_config.json"
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
    }


class TestDiffSlackNoNew:
    """Test that no new messages returns skipped."""

    def test_skipped_when_no_new_messages(self, slack_setup):
        setup = slack_setup

        def mock_call_llm(prompt_file, placeholders, cwd, timeout=300):
            output_path = placeholders.get("OUTPUT_PATH", "")
            if output_path:
                with open(output_path, "w") as f:
                    json.dump({"new_message_count": 0, "threads": []}, f)
            return ""

        with patch("scope_tracker.scripts.diff_slack.call_llm", side_effect=mock_call_llm):
            result = run(setup["project_dir"], setup["config_path"], "demo")

        assert result["status"] == "skipped (no new messages)"


class TestDiffSlackNewMessages:
    """Test that new messages writes raw file and returns changed."""

    def test_changed_with_new_messages(self, slack_setup):
        setup = slack_setup

        def mock_call_llm(prompt_file, placeholders, cwd, timeout=300):
            output_path = placeholders.get("OUTPUT_PATH", "")
            if output_path:
                with open(output_path, "w") as f:
                    json.dump(
                        {
                            "new_message_count": 3,
                            "threads": [
                                {
                                    "thread_ts": "1773910000.000001",
                                    "is_new": True,
                                    "messages": [
                                        {
                                            "ts": "1773910000.000001",
                                            "author": "Sam",
                                            "text": "Let's descope chart switching for V1",
                                        }
                                    ],
                                }
                            ],
                        },
                        f,
                    )
            return ""

        with patch("scope_tracker.scripts.diff_slack.call_llm", side_effect=mock_call_llm):
            result = run(setup["project_dir"], setup["config_path"], "demo")

        assert result["status"] == "changed"
        assert result["new_message_count"] == 3
        assert "raw_path" in result
        assert os.path.exists(result["raw_path"])

        # Verify the raw file content
        with open(result["raw_path"]) as f:
            data = json.load(f)
        assert data["new_message_count"] == 3
        assert len(data["threads"]) == 1
