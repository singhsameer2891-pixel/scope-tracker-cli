"""Tests for sheet_manager.py.

Tests cover:
(a) create operation builds correct headers
(b) update adds new rows
(c) update does not modify user-owned columns
(d) effective status computed correctly for all status combinations
(e) conflict detected when Scope Decision differs and no existing resolution
(f) conflict suppressed when resolution exists and source unchanged
"""

import json
import os
from unittest.mock import patch, MagicMock

import pytest

from scope_tracker.scripts.sheet_manager import (
    build_headers,
    compute_effective_status,
    detect_conflicts,
    add_row,
    update_row,
    load_config,
    _build_row_from_item,
    _diff_prd_item,
    _diff_slack_item,
    _build_dropdown_spec,
    _build_conditional_formatting_spec,
    _build_formatting_spec,
    _get_band_color,
    _is_wrap_column,
    get_column_widths,
    BAND_IDENTITY_COLOR,
    BAND_SOURCE_COLOR,
    BAND_SCOPE_COLOR,
    BAND_UAT_COLOR,
)


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def sample_config():
    """Load sample config fixture."""
    with open(os.path.join(FIXTURES_DIR, "sample_config.json")) as f:
        return json.load(f)


@pytest.fixture
def sample_prd_features():
    """Load sample PRD features fixture."""
    with open(os.path.join(FIXTURES_DIR, "sample_prd_features.json")) as f:
        return json.load(f)


@pytest.fixture
def sample_slack_items():
    """Load sample Slack items fixture."""
    with open(os.path.join(FIXTURES_DIR, "sample_slack_items.json")) as f:
        return json.load(f)


class TestBuildHeaders:
    """Test build_headers produces correct column layout."""

    def test_default_5_uat_rounds(self, sample_config):
        """Headers with default 5 UAT rounds have correct count and order."""
        headers = build_headers(sample_config)

        # Band 1: 3 columns
        assert headers[0] == "#"
        assert headers[1] == "Feature Name"
        assert headers[2] == "Description"

        # Band 2: 5 columns
        assert headers[3] == "Source"
        assert headers[4] == "Source ID"
        assert headers[5] == "Source Text"
        assert headers[6] == "PRD Section"
        assert headers[7] == "PRD Comments"

        # Band 3: 5 columns
        assert headers[8] == "Scope Decision"
        assert headers[9] == "Target Version"
        assert headers[10] == "Conflict Resolution"
        assert headers[11] == "Added Run"
        assert headers[12] == "Last Updated"

        # Band 4: 10 UAT columns (5 rounds * 2) + 4 trailing
        assert headers[13] == "UAT #1 Status"
        assert headers[14] == "UAT #1 Notes"
        assert headers[15] == "UAT #2 Status"

        # Last 4 columns
        assert headers[-4] == "Effective Status"
        assert headers[-3] == "Blocker?"
        assert headers[-2] == "Tester"
        assert headers[-1] == "Test Date"

        # Total: 3 + 5 + 5 + 10 + 4 = 27
        assert len(headers) == 27

    def test_custom_uat_rounds(self, sample_config):
        """Headers with 3 UAT rounds produce fewer columns."""
        sample_config["sheet_config"]["uat_rounds"] = 3
        headers = build_headers(sample_config)

        # 3 + 5 + 5 + 6 + 4 = 23
        assert len(headers) == 23
        assert "UAT #3 Status" in headers
        assert "UAT #3 Notes" in headers
        assert "UAT #4 Status" not in headers

    def test_ends_with_effective_status_blocker_tester_date(self, sample_config):
        """Headers always end with the four trailing columns."""
        headers = build_headers(sample_config)
        assert headers[-4:] == ["Effective Status", "Blocker?", "Tester", "Test Date"]


class TestComputeEffectiveStatus:
    """Test effective status computation logic."""

    def test_all_empty_returns_to_be_tested(self):
        """All UAT status columns empty → 'To be tested'."""
        row = {}
        assert compute_effective_status(row, 5) == "To be tested"

    def test_all_to_be_tested_returns_to_be_tested(self):
        """All UAT status columns = 'To be tested' → 'To be tested'."""
        row = {f"UAT #{i} Status": "To be tested" for i in range(1, 6)}
        assert compute_effective_status(row, 5) == "To be tested"

    def test_highest_round_wins(self):
        """Highest non-empty, non-'To be tested' round wins."""
        row = {
            "UAT #1 Status": "Passed",
            "UAT #2 Status": "Failed",
            "UAT #3 Status": "",
            "UAT #4 Status": "",
            "UAT #5 Status": "",
        }
        assert compute_effective_status(row, 5) == "Failed"

    def test_single_round_passed(self):
        """Only UAT #1 has a value → that value is effective status."""
        row = {"UAT #1 Status": "Passed"}
        assert compute_effective_status(row, 5) == "Passed"

    def test_latest_round_passed_with_iteration(self):
        """Latest round with value 'Passed with iteration' wins."""
        row = {
            "UAT #1 Status": "Failed",
            "UAT #2 Status": "Passed with iteration",
            "UAT #3 Status": "To be tested",
            "UAT #4 Status": "",
            "UAT #5 Status": "",
        }
        assert compute_effective_status(row, 5) == "Passed with iteration"

    def test_blocked_status(self):
        """Blocked in latest round returns 'Blocked'."""
        row = {
            "UAT #1 Status": "Passed",
            "UAT #2 Status": "Blocked",
        }
        assert compute_effective_status(row, 3) == "Blocked"

    def test_to_be_tested_skipped_in_scan(self):
        """'To be tested' values are treated like empty during scan."""
        row = {
            "UAT #1 Status": "Passed",
            "UAT #2 Status": "To be tested",
            "UAT #3 Status": "To be tested",
        }
        assert compute_effective_status(row, 3) == "Passed"


class TestDetectConflicts:
    """Test conflict detection logic."""

    def test_conflict_when_scope_decision_differs(self):
        """Conflict detected when item decision differs from sheet row."""
        new_items = [{
            "source_id": "PRD:1.3",
            "source_text": "Some feature text",
            "latest_comment_decision": "Pushed to V2",
        }]
        sheet_rows = [{
            "Source ID": "PRD:1.3",
            "Scope Decision": "In Scope",
            "Conflict Resolution": "",
            "Source Text": "Some feature text",
        }]
        conflicts = detect_conflicts(new_items, sheet_rows, "PRD", {})
        assert len(conflicts) == 1
        assert conflicts[0]["id"] == "PRD:1.3"
        assert conflicts[0]["value_a"] == "Pushed to V2"
        assert conflicts[0]["value_b"] == "In Scope"

    def test_no_conflict_when_decisions_match(self):
        """No conflict when item decision matches sheet row."""
        new_items = [{
            "source_id": "PRD:1",
            "source_text": "Feature text",
            "latest_comment_decision": "In Scope",
        }]
        sheet_rows = [{
            "Source ID": "PRD:1",
            "Scope Decision": "In Scope",
            "Conflict Resolution": "",
            "Source Text": "Feature text",
        }]
        conflicts = detect_conflicts(new_items, sheet_rows, "PRD", {})
        assert len(conflicts) == 0

    def test_conflict_suppressed_when_resolution_exists_and_source_unchanged(self):
        """Conflict suppressed when resolution exists and source text unchanged."""
        new_items = [{
            "source_id": "PRD:2",
            "source_text": "Same text as before",
            "latest_comment_decision": "Pushed to V2",
        }]
        sheet_rows = [{
            "Source ID": "PRD:2",
            "Scope Decision": "In Scope",
            "Conflict Resolution": "[2026-03-18 Sam via Slack]: Sheet is correct",
            "Source Text": "Same text as before",
        }]
        conflicts = detect_conflicts(new_items, sheet_rows, "PRD", {})
        assert len(conflicts) == 0

    def test_conflict_re_raised_when_source_changed_after_resolution(self):
        """Conflict re-raised when source text changed after resolution."""
        new_items = [{
            "source_id": "PRD:2",
            "source_text": "Updated text with new information",
            "latest_comment_decision": "Pushed to V2",
        }]
        sheet_rows = [{
            "Source ID": "PRD:2",
            "Scope Decision": "In Scope",
            "Conflict Resolution": "[2026-03-18 Sam via Slack]: Sheet is correct",
            "Source Text": "Old text",
        }]
        conflicts = detect_conflicts(new_items, sheet_rows, "PRD", {})
        assert len(conflicts) == 1

    def test_no_conflict_when_no_matching_row(self):
        """No conflict for items that don't match any sheet row."""
        new_items = [{
            "source_id": "PRD:99",
            "source_text": "Brand new feature",
            "latest_comment_decision": "In Scope",
        }]
        sheet_rows = [{
            "Source ID": "PRD:1",
            "Scope Decision": "In Scope",
            "Conflict Resolution": "",
            "Source Text": "Existing feature",
        }]
        conflicts = detect_conflicts(new_items, sheet_rows, "PRD", {})
        assert len(conflicts) == 0

    def test_slack_conflict_uses_scope_decision_field(self):
        """Slack items use scope_decision field for conflict check."""
        new_items = [{
            "source_id": "SLACK:123.456",
            "source_text": "Slack discussion text",
            "scope_decision": "Fast Follower",
        }]
        sheet_rows = [{
            "Source ID": "SLACK:123.456",
            "Scope Decision": "In Scope",
            "Conflict Resolution": "",
            "Source Text": "Slack discussion text",
        }]
        conflicts = detect_conflicts(new_items, sheet_rows, "Slack", {})
        assert len(conflicts) == 1
        assert conflicts[0]["value_a"] == "Fast Follower"


class TestAddRow:
    """Test add_row builds correct row data."""

    def test_prd_row_sets_tool_columns(self, sample_config):
        """PRD row sets all tool-owned columns correctly."""
        headers = build_headers(sample_config)
        item = {
            "source_id": "PRD:1",
            "identifier": "1",
            "feature_name": "User login with OAuth2",
            "description": "Users can log in using OAuth2.",
            "source_text": "As a user, I want to log in using OAuth2.",
            "prd_comments": "[2026-03-10 Sam]: Approved",
            "latest_comment_decision": "In Scope",
        }
        row = add_row(item, 1, 1, "2026-03-19T10:00:00+05:30", headers, "PRD")

        row_dict = dict(zip(headers, row))
        assert row_dict["#"] == "1"
        assert row_dict["Feature Name"] == "User login with OAuth2"
        assert row_dict["Source"] == "PRD"
        assert row_dict["Source ID"] == "PRD:1"
        assert row_dict["PRD Section"] == "1"
        assert row_dict["PRD Comments"] == "[2026-03-10 Sam]: Approved"
        assert row_dict["Scope Decision"] == "In Scope"
        assert row_dict["Added Run"] == "1"

    def test_slack_row_sets_tool_columns(self, sample_config):
        """Slack row sets source and scope decision correctly."""
        headers = build_headers(sample_config)
        item = {
            "source_id": "SLACK:123.456",
            "feature_name": "Dark mode support",
            "description": "Dark mode toggle requested.",
            "source_text": "We should add dark mode.",
            "scope_decision": "Fast Follower",
            "target_version": "Next release",
        }
        row = add_row(item, 5, 2, "2026-03-19T10:00:00+05:30", headers, "Slack")

        row_dict = dict(zip(headers, row))
        assert row_dict["Source"] == "Slack"
        assert row_dict["Source ID"] == "SLACK:123.456"
        assert row_dict["Scope Decision"] == "Fast Follower"
        assert row_dict["Target Version"] == "Next release"
        assert row_dict["PRD Section"] == ""
        assert row_dict["PRD Comments"] == ""

    def test_user_owned_columns_are_empty(self, sample_config):
        """User-owned columns (UAT statuses, Blocker, Tester, Test Date) are empty."""
        headers = build_headers(sample_config)
        item = {
            "source_id": "PRD:1",
            "identifier": "1",
            "feature_name": "Test feature",
            "description": "Test desc",
            "source_text": "Test text",
            "prd_comments": "",
            "latest_comment_decision": "",
        }
        row = add_row(item, 1, 1, "2026-03-19T10:00:00+05:30", headers, "PRD")
        row_dict = dict(zip(headers, row))

        # UAT status columns should be empty
        for i in range(1, 6):
            assert row_dict[f"UAT #{i} Status"] == ""
            assert row_dict[f"UAT #{i} Notes"] == ""

        assert row_dict["Blocker?"] == ""
        assert row_dict["Tester"] == ""
        assert row_dict["Test Date"] == ""


class TestUpdateRow:
    """Test update_row preserves user-owned columns."""

    def test_updates_tool_owned_columns_only(self, sample_config):
        """update_row changes only specified tool columns."""
        headers = build_headers(sample_config)
        existing_row = {h: "" for h in headers}
        existing_row["#"] = "1"
        existing_row["Feature Name"] = "Old name"
        existing_row["Description"] = "Old desc"
        existing_row["UAT #1 Status"] = "Passed"
        existing_row["Blocker?"] = "Yes"
        existing_row["Tester"] = "Alice"

        changes = {
            "Description": "New description",
            "Last Updated": "2026-03-19T10:00:00+05:30",
        }

        result = update_row(existing_row, changes, headers)
        result_dict = dict(zip(headers, result))

        assert result_dict["Description"] == "New description"
        assert result_dict["Last Updated"] == "2026-03-19T10:00:00+05:30"

    def test_never_modifies_user_owned_columns(self, sample_config):
        """Even if changes dict includes user columns, they are not modified."""
        headers = build_headers(sample_config)
        existing_row = {h: "" for h in headers}
        existing_row["UAT #1 Status"] = "Passed"
        existing_row["Blocker?"] = "Yes"
        existing_row["Tester"] = "Alice"
        existing_row["Test Date"] = "2026-03-18"

        changes = {
            "UAT #1 Status": "Failed",  # should be rejected
            "Blocker?": "No",  # should be rejected
            "Tester": "Bob",  # should be rejected
            "Description": "Updated desc",  # should be accepted
        }

        result = update_row(existing_row, changes, headers)
        result_dict = dict(zip(headers, result))

        # User-owned columns preserved
        assert result_dict["UAT #1 Status"] == "Passed"
        assert result_dict["Blocker?"] == "Yes"
        assert result_dict["Tester"] == "Alice"
        assert result_dict["Test Date"] == "2026-03-18"

        # Tool-owned column updated
        assert result_dict["Description"] == "Updated desc"


class TestDiffPrdItem:
    """Test _diff_prd_item detects changes."""

    def test_no_changes_returns_empty(self):
        """Unchanged item returns empty dict."""
        item = {
            "description": "Same desc",
            "source_text": "Same text",
            "prd_comments": "Same comments",
            "feature_name": "Same name",
        }
        existing = {
            "Description": "Same desc",
            "Source Text": "Same text",
            "PRD Comments": "Same comments",
            "Feature Name": "Same name",
        }
        changes = _diff_prd_item(item, existing, "2026-03-19T10:00:00+05:30")
        assert changes == {}

    def test_changed_description(self):
        """Changed description detected."""
        item = {
            "description": "New desc",
            "source_text": "Same text",
            "prd_comments": "",
            "feature_name": "Same name",
        }
        existing = {
            "Description": "Old desc",
            "Source Text": "Same text",
            "PRD Comments": "",
            "Feature Name": "Same name",
        }
        changes = _diff_prd_item(item, existing, "2026-03-19T10:00:00+05:30")
        assert "Description" in changes
        assert "Last Updated" in changes


class TestFormatting:
    """Test formatting helper functions."""

    def test_band_colors_assigned_correctly(self, sample_config):
        """Each column gets the correct band color."""
        headers = build_headers(sample_config)
        assert _get_band_color(0, headers) == BAND_IDENTITY_COLOR
        assert _get_band_color(2, headers) == BAND_IDENTITY_COLOR
        assert _get_band_color(3, headers) == BAND_SOURCE_COLOR
        assert _get_band_color(7, headers) == BAND_SOURCE_COLOR
        assert _get_band_color(8, headers) == BAND_SCOPE_COLOR
        assert _get_band_color(12, headers) == BAND_SCOPE_COLOR

    def test_wrap_columns(self):
        """Correct columns have text wrapping."""
        assert _is_wrap_column("Description") is True
        assert _is_wrap_column("Source Text") is True
        assert _is_wrap_column("PRD Comments") is True
        assert _is_wrap_column("UAT #1 Notes") is True
        assert _is_wrap_column("Scope Decision") is False
        assert _is_wrap_column("#") is False

    def test_column_widths_complete(self, sample_config):
        """All headers have a width defined."""
        headers = build_headers(sample_config)
        widths = get_column_widths(sample_config)
        for h in headers:
            assert h in widths, f"Missing width for column: {h}"

    def test_dropdown_spec_covers_all_dropdown_columns(self, sample_config):
        """Dropdown spec includes Scope Decision, Target Version, UAT statuses, Blocker."""
        headers = build_headers(sample_config)
        dropdowns = _build_dropdown_spec(headers, sample_config)
        dropdown_names = {d["column_name"] for d in dropdowns}

        assert "Scope Decision" in dropdown_names
        assert "Target Version" in dropdown_names
        assert "Blocker?" in dropdown_names
        for i in range(1, 6):
            assert f"UAT #{i} Status" in dropdown_names

    def test_conditional_formatting_rules(self, sample_config):
        """Conditional formatting includes all required rules."""
        headers = build_headers(sample_config)
        rules = _build_conditional_formatting_spec(headers)

        values = {r["value"] for r in rules}
        assert "Passed" in values
        assert "Failed" in values
        assert "Blocked" in values
        assert "Passed with iteration" in values
        assert "Active Blocker" in values
        assert "Conflicting Signal" in values
        assert "Yes" in values  # Blocker = Yes


class TestLoadConfig:
    """Test config loading."""

    def test_load_valid_config(self):
        """Loads config and finds project by name."""
        config_path = os.path.join(FIXTURES_DIR, "sample_config.json")
        config, proj = load_config(config_path, "demo")
        assert proj["name"] == "demo"
        assert "sheet_config" in config

    def test_load_missing_project_raises(self):
        """Raises ValueError for unknown project name."""
        config_path = os.path.join(FIXTURES_DIR, "sample_config.json")
        with pytest.raises(ValueError, match="not found"):
            load_config(config_path, "nonexistent")

    def test_load_missing_file_raises(self):
        """Raises FileNotFoundError for missing config file."""
        with pytest.raises(FileNotFoundError):
            load_config("/tmp/nonexistent_config.json", "demo")
