"""Tests for update_state.py — run state persistence.

Tests:
    (a) basic merge updates prd.last_modified
    (b) slack.seen_thread_ids appends without overwriting
    (c) conflicts merge by id
    (d) sheet fields update correctly
    (e) empty updates file returns no-updates
"""

import json
import os

import pytest

from scope_tracker.scripts.update_state import run, _deep_merge_state


@pytest.fixture
def state_setup(tmp_path):
    """Create a minimal project structure for state update testing."""
    project_dir = tmp_path / "demo"
    system_dir = project_dir / "system"
    system_dir.mkdir(parents=True)

    config_path = tmp_path / "scope_tracker_config.json"
    config_path.write_text(json.dumps({"projects": [{"name": "demo"}]}))

    # Write initial run_state
    state_path = system_dir / "demo_run_state.json"
    initial_state = {
        "_meta": {
            "created": "2026-03-15T09:00:00+05:30",
            "last_updated": "2026-03-17T10:00:00+05:30",
        },
        "run_count": 2,
        "prd": {"last_modified": "2026-03-16T10:00:00Z", "feature_count": 10},
        "slack": {
            "last_run_timestamp": "1773900000.000000",
            "seen_thread_ids": ["1770359450.452919"],
        },
        "conflicts": [
            {
                "id": "PRD:1.3",
                "source_a": "PRD",
                "value_a": "Pushed to V2",
                "source_b": "Sheet",
                "value_b": "In Scope",
                "resolved": False,
            }
        ],
        "sheet": {"last_row_number": 5},
    }
    state_path.write_text(json.dumps(initial_state))

    return {
        "project_dir": str(project_dir),
        "config_path": str(config_path),
        "system_dir": str(system_dir),
        "state_path": str(state_path),
    }


class TestDeepMerge:
    """Test the _deep_merge_state function directly."""

    def test_prd_update(self):
        existing = {"prd": {"last_modified": "old", "feature_count": 5}}
        updates = {"prd": {"last_modified": "new"}}
        result = _deep_merge_state(existing, updates)
        assert result["prd"]["last_modified"] == "new"
        assert result["prd"]["feature_count"] == 5  # preserved

    def test_slack_seen_thread_ids_append(self):
        existing = {
            "slack": {
                "last_run_timestamp": "1000",
                "seen_thread_ids": ["aaa", "bbb"],
            }
        }
        updates = {
            "slack": {
                "last_run_timestamp": "2000",
                "seen_thread_ids": ["bbb", "ccc"],
            }
        }
        result = _deep_merge_state(existing, updates)
        assert result["slack"]["last_run_timestamp"] == "2000"
        ids = result["slack"]["seen_thread_ids"]
        assert "aaa" in ids
        assert "bbb" in ids
        assert "ccc" in ids
        assert len(ids) == 3

    def test_conflicts_merge_by_id(self):
        existing = {
            "conflicts": [
                {"id": "PRD:1.3", "resolved": False},
                {"id": "PRD:2.1", "resolved": False},
            ]
        }
        updates = {
            "conflicts": [
                {"id": "PRD:1.3", "resolved": True},  # update existing
                {"id": "SLACK:999", "resolved": False},  # add new
            ]
        }
        result = _deep_merge_state(existing, updates)
        conflicts_by_id = {c["id"]: c for c in result["conflicts"]}
        assert conflicts_by_id["PRD:1.3"]["resolved"] is True
        assert conflicts_by_id["PRD:2.1"]["resolved"] is False
        assert "SLACK:999" in conflicts_by_id

    def test_sheet_update(self):
        existing = {"sheet": {"last_row_number": 5}}
        updates = {"sheet": {"last_row_number": 8, "last_updated": "now"}}
        result = _deep_merge_state(existing, updates)
        assert result["sheet"]["last_row_number"] == 8
        assert result["sheet"]["last_updated"] == "now"

    def test_top_level_overwrite(self):
        existing = {"run_count": 2}
        updates = {"run_count": 3, "last_run_date": "2026-03-19"}
        result = _deep_merge_state(existing, updates)
        assert result["run_count"] == 3
        assert result["last_run_date"] == "2026-03-19"


class TestUpdateStateRun:
    """Test the full run() function with file I/O."""

    def test_basic_update(self, state_setup):
        setup = state_setup

        updates_file = os.path.join(setup["system_dir"], "updates.json")
        with open(updates_file, "w") as f:
            json.dump(
                {
                    "run_count": 3,
                    "prd": {"last_modified": "2026-03-19T10:00:00Z"},
                    "slack": {
                        "last_run_timestamp": "1774000000.000000",
                        "seen_thread_ids": ["1772790030.028369", "1774000000.000001"],
                    },
                    "sheet": {"last_row_number": 8},
                },
                f,
            )

        result = run(
            setup["project_dir"], setup["config_path"], "demo", updates_file
        )
        assert result["status"] == "updated"

        # Verify the state file
        with open(setup["state_path"]) as f:
            state = json.load(f)

        assert state["run_count"] == 3
        assert state["prd"]["last_modified"] == "2026-03-19T10:00:00Z"
        assert state["prd"]["feature_count"] == 10  # preserved from original
        assert state["slack"]["last_run_timestamp"] == "1774000000.000000"
        assert "1770359450.452919" in state["slack"]["seen_thread_ids"]  # original preserved
        assert "1774000000.000001" in state["slack"]["seen_thread_ids"]  # new added
        assert state["sheet"]["last_row_number"] == 8
        assert "_meta" in state
        assert "last_updated" in state["_meta"]

    def test_empty_updates(self, state_setup):
        setup = state_setup
        updates_file = os.path.join(setup["system_dir"], "empty_updates.json")
        # Don't create the file — simulates missing file
        result = run(
            setup["project_dir"], setup["config_path"], "demo", updates_file
        )
        assert result["status"] == "no updates"

    def test_creates_state_from_scratch(self, tmp_path):
        project_dir = tmp_path / "newproj"
        system_dir = project_dir / "system"
        system_dir.mkdir(parents=True)

        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({"projects": [{"name": "newproj"}]}))

        updates_file = str(system_dir / "updates.json")
        with open(updates_file, "w") as f:
            json.dump({"run_count": 1, "prd": {"last_modified": "2026-03-19T10:00:00Z"}}, f)

        result = run(str(project_dir), str(config_path), "newproj", updates_file)
        assert result["status"] == "updated"

        state_path = system_dir / "newproj_run_state.json"
        assert state_path.exists()
        with open(state_path) as f:
            state = json.load(f)
        assert state["run_count"] == 1
        assert "_meta" in state
