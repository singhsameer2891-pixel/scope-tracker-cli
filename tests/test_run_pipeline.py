"""Tests for run_pipeline.py.

Tests:
(a) all steps run in correct order
(b) steps 1a+1b run in parallel (via ThreadPoolExecutor)
(c) step 2a skipped when PRD unchanged
(d) step 2b skipped when no new Slack
(e) steps_executed increments correctly including skipped steps
(f) dry-run does not call sheet_manager update
(g) dry-run does not call slack_report
"""

import json
import os
import threading
from unittest.mock import patch, MagicMock, call

import pytest

from scope_tracker.scripts import run_pipeline


@pytest.fixture
def pipeline_setup(tmp_path):
    """Set up a minimal project structure for pipeline testing."""
    base_dir = tmp_path / "scope-tracker"
    project_dir = base_dir / "demo"
    system_dir = project_dir / "system"
    prompts_dir = base_dir / "prompts"
    system_dir.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)

    # Write minimal prompt files
    for prompt in [
        "prd_fetch_meta.md", "prd_fetch_content.md", "prd_extract.md",
        "slack_fetch.md", "slack_classify.md", "slack_match.md",
        "conflict_resolve.md", "slack_report.md",
    ]:
        (prompts_dir / prompt).write_text(f"# {prompt}")

    # Write config
    config = {
        "global_settings": {
            "reporting_slack_channel": "scope-tracker",
            "default_timezone": "Asia/Kolkata",
        },
        "sheet_config": {
            "uat_rounds": 5,
            "prd_identifier_column_names": ["ID", "Identifier", "#", "Ref"],
            "prd_story_column_names": ["User Story", "Story", "Feature", "Requirement", "Description"],
        },
        "projects": [
            {
                "name": "demo",
                "enabled": True,
                "folder": "demo",
                "slack_channel": "demo-scope",
                "sheet_url": "https://docs.google.com/spreadsheets/d/abc123",
                "prd_source": {
                    "type": "google-drive",
                    "url": "https://docs.google.com/document/d/xyz",
                },
                "slack_last_run_timestamp": "1773901583.351119",
                "run_count": 2,
            }
        ],
    }
    config_path = base_dir / "scope_tracker_config.json"
    config_path.write_text(json.dumps(config))

    # Write initial run_state
    run_state = {
        "_meta": {"created": "2026-03-15T09:00:00+05:30"},
        "run_count": 2,
        "last_run_date": "2026-03-18",
        "prd": {"last_modified": "2026-03-17T10:23:00Z"},
        "slack": {"last_run_timestamp": "1773901583.351119", "seen_thread_ids": []},
        "conflicts": [],
        "sheet": {"last_row_number": 5},
    }
    (system_dir / "demo_run_state.json").write_text(json.dumps(run_state))

    return {
        "base_dir": str(base_dir),
        "project_dir": str(project_dir),
        "system_dir": str(system_dir),
        "config_path": str(config_path),
    }


class TestStepOrder:
    """Test (a): all steps run in correct order."""

    @patch("scope_tracker.scripts.run_pipeline.call_llm")
    @patch("scope_tracker.scripts.run_pipeline.conflict_manager")
    @patch("scope_tracker.scripts.run_pipeline.diff_prd")
    @patch("scope_tracker.scripts.run_pipeline.diff_slack")
    @patch("scope_tracker.scripts.run_pipeline.sheet_manager")
    @patch("scope_tracker.scripts.run_pipeline.update_state")
    def test_all_steps_execute(
        self, mock_update, mock_sheet, mock_slack, mock_prd, mock_conflict, mock_llm,
        pipeline_setup,
    ):
        """All 6 steps execute in the correct order."""
        mock_conflict.run.return_value = {"status": "no pending conflicts"}
        mock_prd.run.return_value = {"status": "skipped (unchanged)", "last_modified": "2026-03-17T10:23:00Z"}
        mock_slack.run.return_value = {"status": "skipped (no new messages)"}
        mock_sheet.load_config.return_value = ({}, {})
        mock_sheet.update_sheet.return_value = {
            "status": "updated", "rows_added": 0, "rows_updated": 0, "conflicts_detected": 0,
        }
        mock_update.run.return_value = {"status": "updated"}

        result = run_pipeline.run(
            pipeline_setup["project_dir"],
            pipeline_setup["config_path"],
            "demo",
            verbose=True,
        )

        assert result["status"] == "completed"
        assert result["steps_executed"] == 6

        # Verify step order: conflict_manager first
        mock_conflict.run.assert_called_once()
        # diff_prd and diff_slack called
        mock_prd.run.assert_called_once()
        mock_slack.run.assert_called_once()
        # update_state called
        mock_update.run.assert_called_once()

        # Verify steps_executed.json was written
        steps_path = os.path.join(pipeline_setup["system_dir"], "demo_steps_executed.json")
        assert os.path.exists(steps_path)
        with open(steps_path) as f:
            steps_data = json.load(f)
        assert steps_data["steps_executed"] == 6


class TestParallelExecution:
    """Test (b): steps 1a+1b run in parallel."""

    @patch("scope_tracker.scripts.run_pipeline.call_llm")
    @patch("scope_tracker.scripts.run_pipeline.conflict_manager")
    @patch("scope_tracker.scripts.run_pipeline.sheet_manager")
    @patch("scope_tracker.scripts.run_pipeline.update_state")
    def test_diff_steps_run_in_parallel(
        self, mock_update, mock_sheet, mock_conflict, mock_llm, pipeline_setup,
    ):
        """Steps 1a and 1b run in different threads."""
        mock_conflict.run.return_value = {"status": "no pending conflicts"}
        mock_sheet.load_config.return_value = ({}, {})
        mock_sheet.update_sheet.return_value = {
            "status": "updated", "rows_added": 0, "rows_updated": 0, "conflicts_detected": 0,
        }
        mock_update.run.return_value = {"status": "updated"}

        threads_seen = []

        def mock_prd_run(*args, **kwargs):
            threads_seen.append(("prd", threading.current_thread().ident))
            return {"status": "skipped (unchanged)"}

        def mock_slack_run(*args, **kwargs):
            threads_seen.append(("slack", threading.current_thread().ident))
            return {"status": "skipped (no new messages)"}

        with patch("scope_tracker.scripts.run_pipeline.diff_prd") as mock_prd, \
             patch("scope_tracker.scripts.run_pipeline.diff_slack") as mock_slack_mod:
            mock_prd.run.side_effect = mock_prd_run
            mock_slack_mod.run.side_effect = mock_slack_run

            result = run_pipeline.run(
                pipeline_setup["project_dir"],
                pipeline_setup["config_path"],
                "demo",
            )

        assert result["status"] == "completed"
        # Both should have been called
        assert len(threads_seen) == 2
        names = {t[0] for t in threads_seen}
        assert "prd" in names
        assert "slack" in names


class TestPRDSkipped:
    """Test (c): step 2a skipped when PRD unchanged."""

    @patch("scope_tracker.scripts.run_pipeline.call_llm")
    @patch("scope_tracker.scripts.run_pipeline.conflict_manager")
    @patch("scope_tracker.scripts.run_pipeline.diff_prd")
    @patch("scope_tracker.scripts.run_pipeline.diff_slack")
    @patch("scope_tracker.scripts.run_pipeline.sheet_manager")
    @patch("scope_tracker.scripts.run_pipeline.update_state")
    def test_prd_extract_skipped(
        self, mock_update, mock_sheet, mock_slack, mock_prd, mock_conflict, mock_llm,
        pipeline_setup,
    ):
        """PRD extraction is skipped when PRD is unchanged."""
        mock_conflict.run.return_value = {"status": "no pending conflicts"}
        mock_prd.run.return_value = {"status": "skipped (unchanged)"}
        mock_slack.run.return_value = {"status": "skipped (no new messages)"}
        mock_sheet.load_config.return_value = ({}, {})
        mock_sheet.update_sheet.return_value = {
            "status": "updated", "rows_added": 0, "rows_updated": 0, "conflicts_detected": 0,
        }
        mock_update.run.return_value = {"status": "updated"}

        result = run_pipeline.run(
            pipeline_setup["project_dir"],
            pipeline_setup["config_path"],
            "demo",
        )

        # call_llm should not have been called with prd_extract prompt
        for c in mock_llm.call_args_list:
            prompt_arg = c.kwargs.get("prompt_file", "") if c.kwargs else ""
            if not prompt_arg and c.args:
                prompt_arg = c.args[0]
            assert "prd_extract" not in os.path.basename(str(prompt_arg))

        # Steps still executed (skipped counts as executed)
        assert result["steps_executed"] == 6


class TestSlackSkipped:
    """Test (d): step 2b skipped when no new Slack."""

    @patch("scope_tracker.scripts.run_pipeline.call_llm")
    @patch("scope_tracker.scripts.run_pipeline.conflict_manager")
    @patch("scope_tracker.scripts.run_pipeline.diff_prd")
    @patch("scope_tracker.scripts.run_pipeline.diff_slack")
    @patch("scope_tracker.scripts.run_pipeline.sheet_manager")
    @patch("scope_tracker.scripts.run_pipeline.update_state")
    def test_slack_classify_skipped(
        self, mock_update, mock_sheet, mock_slack, mock_prd, mock_conflict, mock_llm,
        pipeline_setup,
    ):
        """Slack classification is skipped when no new messages."""
        mock_conflict.run.return_value = {"status": "no pending conflicts"}
        mock_prd.run.return_value = {"status": "skipped (unchanged)"}
        mock_slack.run.return_value = {"status": "skipped (no new messages)"}
        mock_sheet.load_config.return_value = ({}, {})
        mock_sheet.update_sheet.return_value = {
            "status": "updated", "rows_added": 0, "rows_updated": 0, "conflicts_detected": 0,
        }
        mock_update.run.return_value = {"status": "updated"}

        result = run_pipeline.run(
            pipeline_setup["project_dir"],
            pipeline_setup["config_path"],
            "demo",
        )

        # call_llm should not have been called with slack_classify prompt
        for c in mock_llm.call_args_list:
            prompt_arg = c.kwargs.get("prompt_file", "") if c.kwargs else ""
            if not prompt_arg and c.args:
                prompt_arg = c.args[0]
            assert "slack_classify" not in os.path.basename(str(prompt_arg))


class TestStepsExecuted:
    """Test (e): steps_executed increments correctly."""

    @patch("scope_tracker.scripts.run_pipeline.call_llm")
    @patch("scope_tracker.scripts.run_pipeline.conflict_manager")
    @patch("scope_tracker.scripts.run_pipeline.diff_prd")
    @patch("scope_tracker.scripts.run_pipeline.diff_slack")
    @patch("scope_tracker.scripts.run_pipeline.sheet_manager")
    @patch("scope_tracker.scripts.run_pipeline.update_state")
    def test_steps_counter(
        self, mock_update, mock_sheet, mock_slack, mock_prd, mock_conflict, mock_llm,
        pipeline_setup,
    ):
        """steps_executed reaches 6 even when steps are skipped."""
        mock_conflict.run.return_value = {"status": "no pending conflicts"}
        mock_prd.run.return_value = {"status": "skipped (unchanged)"}
        mock_slack.run.return_value = {"status": "skipped (no new messages)"}
        mock_sheet.load_config.return_value = ({}, {})
        mock_sheet.update_sheet.return_value = {
            "status": "updated", "rows_added": 0, "rows_updated": 0, "conflicts_detected": 0,
        }
        mock_update.run.return_value = {"status": "updated"}

        result = run_pipeline.run(
            pipeline_setup["project_dir"],
            pipeline_setup["config_path"],
            "demo",
        )

        assert result["steps_executed"] == 6

        # Verify the steps_executed.json file
        steps_path = os.path.join(pipeline_setup["system_dir"], "demo_steps_executed.json")
        with open(steps_path) as f:
            steps_data = json.load(f)
        assert steps_data["steps_executed"] == 6
        # Should have entries for all steps
        step_names = [s["step"] for s in steps_data["steps"]]
        assert "0" in step_names
        assert "1a" in step_names
        assert "1b" in step_names
        assert "2a" in step_names
        assert "2b" in step_names
        assert "3" in step_names
        assert "4" in step_names
        assert "5" in step_names


class TestDryRun:
    """Tests (f) and (g): dry-run skips sheet writes and Slack report."""

    @patch("scope_tracker.scripts.run_pipeline.call_llm")
    @patch("scope_tracker.scripts.run_pipeline.conflict_manager")
    @patch("scope_tracker.scripts.run_pipeline.diff_prd")
    @patch("scope_tracker.scripts.run_pipeline.diff_slack")
    @patch("scope_tracker.scripts.run_pipeline.sheet_manager")
    @patch("scope_tracker.scripts.run_pipeline.update_state")
    def test_dry_run_skips_sheet_update(
        self, mock_update, mock_sheet, mock_slack, mock_prd, mock_conflict, mock_llm,
        pipeline_setup,
    ):
        """Dry-run does not call sheet_manager.update_sheet."""
        mock_conflict.run.return_value = {"status": "no pending conflicts"}
        mock_prd.run.return_value = {"status": "skipped (unchanged)"}
        mock_slack.run.return_value = {"status": "skipped (no new messages)"}
        mock_update.run.return_value = {"status": "updated"}

        result = run_pipeline.run(
            pipeline_setup["project_dir"],
            pipeline_setup["config_path"],
            "demo",
            dry_run=True,
        )

        assert result["dry_run"] is True
        # sheet_manager.update_sheet should NOT be called
        mock_sheet.update_sheet.assert_not_called()
        mock_sheet.load_config.assert_not_called()

    @patch("scope_tracker.scripts.run_pipeline.call_llm")
    @patch("scope_tracker.scripts.run_pipeline.conflict_manager")
    @patch("scope_tracker.scripts.run_pipeline.diff_prd")
    @patch("scope_tracker.scripts.run_pipeline.diff_slack")
    @patch("scope_tracker.scripts.run_pipeline.sheet_manager")
    @patch("scope_tracker.scripts.run_pipeline.update_state")
    def test_dry_run_skips_slack_report(
        self, mock_update, mock_sheet, mock_slack, mock_prd, mock_conflict, mock_llm,
        pipeline_setup,
    ):
        """Dry-run does not call slack_report LLM."""
        mock_conflict.run.return_value = {"status": "no pending conflicts"}
        mock_prd.run.return_value = {"status": "skipped (unchanged)"}
        mock_slack.run.return_value = {"status": "skipped (no new messages)"}
        mock_update.run.return_value = {"status": "updated"}

        result = run_pipeline.run(
            pipeline_setup["project_dir"],
            pipeline_setup["config_path"],
            "demo",
            dry_run=True,
        )

        # call_llm should not have been called with slack_report prompt
        for c in mock_llm.call_args_list:
            prompt_arg = c.kwargs.get("prompt_file", "") if c.kwargs else ""
            if not prompt_arg and c.args:
                prompt_arg = c.args[0]
            assert "slack_report" not in os.path.basename(str(prompt_arg))

        # Verify steps_executed still shows dry-run status
        steps_path = os.path.join(pipeline_setup["system_dir"], "demo_steps_executed.json")
        with open(steps_path) as f:
            steps_data = json.load(f)

        step5 = [s for s in steps_data["steps"] if s["step"] == "5"][0]
        assert step5["status"] == "dry-run"
