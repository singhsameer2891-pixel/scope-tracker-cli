"""Tests for diff_prd.py — PRD change detection.

Tests:
    (a) mtime unchanged → returns skipped
    (b) mtime changed → calls prd_fetch_content, writes files, returns changed
    (c) type none → returns not-configured
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from scope_tracker.scripts.diff_prd import run


@pytest.fixture
def project_setup(tmp_path):
    """Create a minimal project structure for testing."""
    # Create project dir with system subfolder
    project_dir = tmp_path / "demo"
    system_dir = project_dir / "system"
    system_dir.mkdir(parents=True)

    # Create scope-tracker root structure (project_dir's grandparent + prompts)
    scope_root = tmp_path
    prompts_dir = scope_root / "prompts"
    prompts_dir.mkdir(exist_ok=True)

    # Write stub prompt files
    (prompts_dir / "prd_fetch_meta.md").write_text("Fetch meta for {{DOC_URL}}")
    (prompts_dir / "prd_fetch_content.md").write_text("Fetch content for {{DOC_URL}}")

    # Write config
    config_path = scope_root / "scope_tracker_config.json"
    config = {
        "projects": [
            {
                "name": "demo",
                "enabled": True,
                "folder": "demo",
                "slack_channel": "demo-scope",
                "sheet_url": "",
                "prd_source": {
                    "type": "google-drive",
                    "url": "https://docs.google.com/document/d/xyz789/edit",
                    "last_modified": None,
                },
                "slack_last_run_timestamp": None,
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
        "scope_root": str(scope_root),
        "prompts_dir": str(prompts_dir),
    }


class TestDiffPrdTypeNone:
    """Test that type=none returns not-configured."""

    def test_not_configured(self, tmp_path):
        config = {
            "projects": [
                {
                    "name": "demo",
                    "prd_source": {"type": "none"},
                }
            ]
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        project_dir = tmp_path / "demo"
        project_dir.mkdir()

        result = run(str(project_dir), str(config_path), "demo")
        assert result["status"] == "not configured"


class TestDiffPrdUnchanged:
    """Test that unchanged mtime returns skipped."""

    def test_skipped_when_unchanged(self, project_setup):
        setup = project_setup
        stored_mtime = "2026-03-17T10:23:00Z"

        # Write existing run_state with matching mtime
        state_path = os.path.join(setup["system_dir"], "demo_run_state.json")
        with open(state_path, "w") as f:
            json.dump({"prd": {"last_modified": stored_mtime}}, f)

        def mock_call_llm(prompt_file, placeholders, cwd, timeout=300):
            # Meta call returns same mtime
            output_path = placeholders.get("OUTPUT_PATH", "")
            if output_path:
                with open(output_path, "w") as f:
                    json.dump({"modified_time": stored_mtime}, f)
            return ""

        with patch("scope_tracker.scripts.diff_prd.call_llm", side_effect=mock_call_llm):
            result = run(setup["project_dir"], setup["config_path"], "demo")

        assert result["status"] == "skipped (unchanged)"
        assert result["last_modified"] == stored_mtime


class TestDiffPrdChanged:
    """Test that changed mtime triggers content fetch."""

    def test_changed_fetches_content(self, project_setup):
        setup = project_setup
        old_mtime = "2026-03-17T10:23:00Z"
        new_mtime = "2026-03-18T14:00:00Z"

        # Write existing run_state with old mtime
        state_path = os.path.join(setup["system_dir"], "demo_run_state.json")
        with open(state_path, "w") as f:
            json.dump({"prd": {"last_modified": old_mtime}}, f)

        call_count = {"meta": 0, "content": 0}

        def mock_call_llm(prompt_file, placeholders, cwd, timeout=300):
            if "prd_fetch_meta" in prompt_file:
                call_count["meta"] += 1
                output_path = placeholders.get("OUTPUT_PATH", "")
                if output_path:
                    with open(output_path, "w") as f:
                        json.dump({"modified_time": new_mtime}, f)
            elif "prd_fetch_content" in prompt_file:
                call_count["content"] += 1
                content_path = placeholders.get("CONTENT_OUTPUT_PATH", "")
                comments_path = placeholders.get("COMMENTS_OUTPUT_PATH", "")
                if content_path:
                    with open(content_path, "w") as f:
                        f.write("PRD raw content here")
                if comments_path:
                    with open(comments_path, "w") as f:
                        json.dump([{"anchor_text": "test", "author": "Sam", "date": "2026-03-18", "comment_text": "Looks good"}], f)
            return ""

        with patch("scope_tracker.scripts.diff_prd.call_llm", side_effect=mock_call_llm):
            result = run(setup["project_dir"], setup["config_path"], "demo")

        assert result["status"] == "changed"
        assert result["last_modified"] == new_mtime
        assert "raw_path" in result
        assert "comments_path" in result
        assert call_count["meta"] == 1
        assert call_count["content"] == 1

        # Verify files were written
        assert os.path.exists(result["raw_path"])
        assert os.path.exists(result["comments_path"])
