"""Tests for scope_tracker.runner module.

Tests run_project() and run_all() with mocked pipeline calls.
"""

import json
import os
from unittest import mock

import pytest

from scope_tracker import runner


@pytest.fixture
def sample_config(tmp_path):
    """Create a sample config file and directory structure."""
    st_dir = tmp_path / "scope-tracker"
    st_dir.mkdir()

    # Create project dirs
    project_dir = st_dir / "demo" / "system"
    project_dir.mkdir(parents=True)
    (st_dir / "demo" / "outputs").mkdir()

    config = {
        "global_settings": {
            "reporting_slack_channel": "scope-tracker",
            "reporting_slack_last_read": None,
            "default_timezone": "Asia/Kolkata",
        },
        "sheet_config": {
            "uat_rounds": 5,
            "status_options": ["To be tested", "Passed", "Failed", "Blocked"],
            "scope_decision_options": ["In Scope", "Pushed to V2"],
            "version_options": ["LIVE", "Next release"],
            "blocker_options": ["Yes", "No"],
            "prd_identifier_column_names": ["ID", "#"],
            "prd_story_column_names": ["User Story", "Feature"],
        },
        "projects": [
            {
                "name": "demo",
                "enabled": True,
                "folder": "demo",
                "slack_channel": "demo-scope",
                "sheet_url": "https://docs.google.com/spreadsheets/d/abc",
                "prd_source": {
                    "type": "google-drive",
                    "url": "https://docs.google.com/document/d/xyz",
                    "last_modified": None,
                },
                "slack_last_run_timestamp": None,
                "run_count": 0,
                "last_run_date": None,
            },
            {
                "name": "disabled-project",
                "enabled": False,
                "folder": "disabled-project",
                "slack_channel": "disabled",
                "sheet_url": "",
                "prd_source": {"type": "none", "url": "", "last_modified": None},
                "slack_last_run_timestamp": None,
                "run_count": 0,
                "last_run_date": None,
            },
        ],
    }

    config_path = st_dir / "scope_tracker_config.json"
    config_path.write_text(json.dumps(config, indent=2))

    return str(st_dir), str(config_path), config


MOCK_PIPELINE_RESULT = {
    "status": "completed",
    "steps_executed": 6,
    "dry_run": False,
    "summary": {
        "prd_status": "updated",
        "slack_status": "skipped",
        "prd_feature_count": 5,
        "slack_new_messages": 0,
        "slack_decisions_found": 0,
        "rows_added": 3,
        "rows_updated": 2,
        "conflicts_detected": 0,
    },
}


class TestRunProject:
    """Tests for runner.run_project()."""

    @mock.patch("scope_tracker.runner.run_pipeline")
    def test_passes_correct_args(self, mock_pipeline, sample_config):
        """run_project passes correct project_dir, config_path, and project_name."""
        st_dir, config_path, config = sample_config
        project = config["projects"][0]

        mock_pipeline.run.return_value = MOCK_PIPELINE_RESULT.copy()

        result = runner.run_project(project, config, st_dir)

        mock_pipeline.run.assert_called_once_with(
            project_dir=os.path.join(st_dir, "demo"),
            config_path=os.path.join(st_dir, "scope_tracker_config.json"),
            project_name="demo",
            dry_run=False,
            verbose=False,
        )
        assert result["status"] == "completed"
        assert result["project"] == "demo"

    @mock.patch("scope_tracker.runner.run_pipeline")
    def test_dry_run_flag_propagated(self, mock_pipeline, sample_config):
        """dry_run flag is passed through to run_pipeline.run()."""
        st_dir, config_path, config = sample_config
        project = config["projects"][0]

        mock_pipeline.run.return_value = {**MOCK_PIPELINE_RESULT, "dry_run": True}

        result = runner.run_project(project, config, st_dir, dry_run=True)

        call_kwargs = mock_pipeline.run.call_args
        assert call_kwargs.kwargs.get("dry_run") is True or call_kwargs[1].get("dry_run") is True

    @mock.patch("scope_tracker.runner.run_pipeline")
    def test_verbose_flag_propagated(self, mock_pipeline, sample_config):
        """verbose flag is passed through to run_pipeline.run()."""
        st_dir, config_path, config = sample_config
        project = config["projects"][0]

        mock_pipeline.run.return_value = MOCK_PIPELINE_RESULT.copy()

        runner.run_project(project, config, st_dir, verbose=True)

        call_kwargs = mock_pipeline.run.call_args
        assert call_kwargs.kwargs.get("verbose") is True or call_kwargs[1].get("verbose") is True

    @mock.patch("scope_tracker.runner.run_pipeline")
    def test_failed_pipeline_raises(self, mock_pipeline, sample_config):
        """RuntimeError is raised when pipeline fails."""
        st_dir, config_path, config = sample_config
        project = config["projects"][0]

        mock_pipeline.run.side_effect = Exception("LLM call timed out")

        with pytest.raises(RuntimeError, match="Pipeline failed for project 'demo'"):
            runner.run_project(project, config, st_dir)


class TestRunAll:
    """Tests for runner.run_all()."""

    @mock.patch("scope_tracker.runner.run_project")
    def test_runs_enabled_projects_only(self, mock_run_project, sample_config):
        """Only enabled projects are run."""
        st_dir, config_path, config = sample_config

        mock_run_project.return_value = MOCK_PIPELINE_RESULT.copy()

        results = runner.run_all(config_path)

        # Should only call for "demo", not "disabled-project"
        assert mock_run_project.call_count == 1
        call_args = mock_run_project.call_args
        assert call_args.kwargs.get("project") is not None or call_args[0][0]["name"] == "demo"

    @mock.patch("scope_tracker.runner.run_project")
    def test_project_filter(self, mock_run_project, sample_config):
        """project_filter limits to the specified project."""
        st_dir, config_path, config = sample_config

        mock_run_project.return_value = MOCK_PIPELINE_RESULT.copy()

        results = runner.run_all(config_path, project_filter="demo")
        assert len(results) == 1

    def test_project_filter_not_found(self, sample_config):
        """ValueError raised when filtered project doesn't exist."""
        st_dir, config_path, config = sample_config

        with pytest.raises(ValueError, match="not found or not enabled"):
            runner.run_all(config_path, project_filter="nonexistent")

    def test_config_not_found(self, tmp_path):
        """FileNotFoundError raised when config doesn't exist."""
        with pytest.raises(FileNotFoundError):
            runner.run_all(str(tmp_path / "missing_config.json"))

    @mock.patch("scope_tracker.runner.run_project")
    def test_collects_error_results(self, mock_run_project, sample_config):
        """Pipeline errors are captured in results, not raised."""
        st_dir, config_path, config = sample_config

        mock_run_project.side_effect = RuntimeError("Pipeline failed for project 'demo': timeout")

        results = runner.run_all(config_path)
        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "demo" in results[0]["project"]

    @mock.patch("scope_tracker.runner.run_project")
    def test_dry_run_propagated(self, mock_run_project, sample_config):
        """dry_run is propagated to run_project."""
        st_dir, config_path, config = sample_config

        mock_run_project.return_value = MOCK_PIPELINE_RESULT.copy()

        runner.run_all(config_path, dry_run=True)

        call_kwargs = mock_run_project.call_args
        assert call_kwargs.kwargs.get("dry_run") is True
