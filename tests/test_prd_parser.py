"""Tests for prd_parser.py — pure Python PRD extraction.

Tests:
    (a) Extracts features from markdown table with valid IDs
    (b) Skips rows with non-numeric IDs
    (c) Returns empty list when no "User Stories" section
    (d) Attaches comments correctly
    (e) Handles multiple tables (only extracts from User Stories section)
    (f) Handles pipe-delimited tables
"""

import pytest
from scope_tracker.scripts.prd_parser import (
    extract_features,
    _find_user_stories_section,
    _parse_tables,
    _is_valid_identifier,
    _infer_scope_decision,
)


SAMPLE_PRD = """# Product Requirements

## Overview

This is a sample product document.

## User Stories

| ID | User Story | Priority |
|----|-----------|----------|
| 1 | As a user, I want to log in via OAuth2 so I don't need a password. | High |
| 1.1 | As a user, I want two-factor authentication. | Medium |
| 2 | As a user, I want to see my live P&L updated every 30 seconds. | High |
| 2.1 | As a user, I want to switch between time periods on charts. | Medium |

## Technical Details

| Component | Technology |
|-----------|-----------|
| Frontend | React |
| Backend | Go |
"""

SAMPLE_PRD_WITH_INVALID_IDS = """# PRD

## User Stories

| Ref | Description | Priority |
|-----|-------------|----------|
| 1 | Valid feature one. | High |
| US-001 | Invalid identifier format. | Medium |
| F1 | Also invalid. | Low |
| 1.1 | Valid sub-feature. | High |
|  | Empty identifier. | Low |
| 2 | Another valid feature. | Medium |
"""

SAMPLE_COMMENTS = [
    {
        "anchor_text": "log in via OAuth2",
        "author": "Alice",
        "date": "2026-03-10T14:30:00Z",
        "comment_text": "Confirmed in scope for V1",
    },
    {
        "anchor_text": "live P&L",
        "author": "Bob",
        "date": "2026-03-08",
        "comment_text": "Descoped for V1 due to complexity",
    },
    {
        "anchor_text": "live P&L",
        "author": "Alice",
        "date": "2026-03-15",
        "comment_text": "Reinstated per stakeholder approval",
    },
]

ID_COLS = ["ID", "Identifier", "#", "Ref"]
STORY_COLS = ["User Story", "Story", "Feature", "Requirement", "Description"]


class TestFindUserStoriesSection:
    def test_finds_section(self):
        section = _find_user_stories_section(SAMPLE_PRD)
        assert section is not None
        assert "log in via OAuth2" in section
        assert "two-factor authentication" in section

    def test_excludes_other_sections(self):
        section = _find_user_stories_section(SAMPLE_PRD)
        assert section is not None
        assert "React" not in section
        assert "Technical Details" not in section

    def test_returns_none_when_missing(self):
        text = "# Overview\n\nNo stories here.\n"
        assert _find_user_stories_section(text) is None

    def test_case_insensitive(self):
        text = "# user stories\n\n| ID | Story |\n|---|---|\n| 1 | Test |\n"
        section = _find_user_stories_section(text)
        assert section is not None
        assert "Test" in section


class TestParseTables:
    def test_parses_pipe_table(self):
        section = "| ID | Story |\n|---|---|\n| 1 | Feature A |\n| 2 | Feature B |\n"
        tables = _parse_tables(section)
        assert len(tables) == 1
        assert len(tables[0]) == 3  # header + 2 data rows (separator excluded)
        # Wait - separator is excluded, so header + 2 data rows = 3
        # Actually, separator is excluded, so we have: header, row1, row2 = 3 rows
        assert tables[0][0] == ["ID", "Story"]
        assert tables[0][1] == ["1", "Feature A"]

    def test_multiple_tables(self):
        section = (
            "| A | B |\n|---|---|\n| 1 | x |\n\nSome text\n\n"
            "| C | D |\n|---|---|\n| 2 | y |\n"
        )
        tables = _parse_tables(section)
        assert len(tables) == 2


class TestIsValidIdentifier:
    @pytest.mark.parametrize("value", ["1", "1.1", "1.2.5", "10", "10.1", "2"])
    def test_valid(self, value):
        assert _is_valid_identifier(value) is True

    @pytest.mark.parametrize("value", ["US-001", "F1", "Feature 1", "1.", ".1", "", " "])
    def test_invalid(self, value):
        assert _is_valid_identifier(value) is False


class TestInferScopeDecision:
    def test_in_scope(self):
        assert _infer_scope_decision("confirmed in scope") == "In Scope"
        assert _infer_scope_decision("reinstate for v1") == "In Scope"

    def test_pushed_to_v2(self):
        assert _infer_scope_decision("pushed to v2") == "Pushed to V2"

    def test_parked(self):
        assert _infer_scope_decision("parked for now") == "Parked"

    def test_fast_follower(self):
        assert _infer_scope_decision("this is a fast follower") == "Fast Follower"

    def test_descoped(self):
        assert _infer_scope_decision("descoped from v1") == "Descoped"

    def test_no_decision(self):
        assert _infer_scope_decision("just a regular comment") is None


class TestExtractFeatures:
    def test_extracts_valid_features(self):
        """(a) Extracts features from markdown table with valid IDs."""
        features = extract_features(SAMPLE_PRD, [], ID_COLS, STORY_COLS)
        assert len(features) == 4
        assert features[0]["source_id"] == "PRD:1"
        assert features[0]["identifier"] == "1"
        assert "OAuth2" in features[0]["description"]
        assert features[1]["identifier"] == "1.1"
        assert features[2]["identifier"] == "2"
        assert features[3]["identifier"] == "2.1"

    def test_skips_non_numeric_ids(self):
        """(b) Skips rows with non-numeric IDs."""
        features = extract_features(SAMPLE_PRD_WITH_INVALID_IDS, [], ID_COLS, STORY_COLS)
        identifiers = [f["identifier"] for f in features]
        assert "1" in identifiers
        assert "1.1" in identifiers
        assert "2" in identifiers
        assert "US-001" not in identifiers
        assert "F1" not in identifiers

        # Check skipped_rows
        skipped = features[0].get("skipped_rows", [])
        assert any("US-001" in s for s in skipped)
        assert any("F1" in s for s in skipped)
        assert any("empty" in s.lower() for s in skipped)

    def test_returns_empty_when_no_section(self):
        """(c) Returns empty list when no 'User Stories' section."""
        text = "# Overview\n\nJust some text.\n\n# Appendix\n\nMore text.\n"
        features = extract_features(text, [], ID_COLS, STORY_COLS)
        assert features == []

    def test_attaches_comments(self):
        """(d) Attaches comments correctly."""
        features = extract_features(SAMPLE_PRD, SAMPLE_COMMENTS, ID_COLS, STORY_COLS)

        # Feature 1 (OAuth2) should have Alice's comment
        f1 = features[0]
        assert "Alice" in f1["prd_comments"]
        assert "Confirmed in scope" in f1["prd_comments"]
        assert f1["latest_comment_decision"] == "In Scope"

        # Feature 2 (P&L) should have both Bob and Alice's comments, latest decision wins
        f2 = features[2]
        assert "Bob" in f2["prd_comments"]
        assert "Alice" in f2["prd_comments"]
        # Latest comment is Alice's "Reinstated" → In Scope
        assert f2["latest_comment_decision"] == "In Scope"

    def test_multiple_comments_chronological(self):
        """Comments are concatenated chronologically."""
        features = extract_features(SAMPLE_PRD, SAMPLE_COMMENTS, ID_COLS, STORY_COLS)
        f2 = features[2]  # P&L feature
        # Bob's comment (March 8) should come before Alice's (March 15)
        bob_pos = f2["prd_comments"].find("Bob")
        alice_pos = f2["prd_comments"].find("Alice")
        assert bob_pos < alice_pos

    def test_only_user_stories_section(self):
        """(e) Handles multiple tables — only extracts from User Stories section."""
        features = extract_features(SAMPLE_PRD, [], ID_COLS, STORY_COLS)
        # Should NOT include Technical Details table entries
        descriptions = " ".join(f["description"] for f in features)
        assert "React" not in descriptions
        assert "Go" not in descriptions

    def test_pipe_delimited_table(self):
        """(f) Handles pipe-delimited tables."""
        text = """## User Stories

| # | Feature | Notes |
|---|---------|-------|
| 1 | Login feature | V1 |
| 2 | Dashboard | V1 |
"""
        features = extract_features(text, [], ID_COLS, STORY_COLS)
        assert len(features) == 2
        assert features[0]["identifier"] == "1"
        assert features[0]["description"] == "Login feature"

    def test_feature_name_truncated(self):
        """Feature name truncated to 80 chars."""
        long_story = "A" * 100
        text = f"## User Stories\n\n| ID | User Story |\n|---|---|\n| 1 | {long_story} |\n"
        features = extract_features(text, [], ID_COLS, STORY_COLS)
        assert len(features) == 1
        assert len(features[0]["feature_name"]) == 80
        assert len(features[0]["description"]) == 100

    def test_source_id_format(self):
        """source_id uses PRD: prefix."""
        features = extract_features(SAMPLE_PRD, [], ID_COLS, STORY_COLS)
        for f in features:
            assert f["source_id"].startswith("PRD:")
            assert f["source_id"] == f"PRD:{f['identifier']}"

    def test_empty_comments_default(self):
        """Features with no matching comments have empty prd_comments."""
        features = extract_features(SAMPLE_PRD, [], ID_COLS, STORY_COLS)
        for f in features:
            assert f["prd_comments"] == ""
            assert f["latest_comment_decision"] is None

    def test_orphan_comments_ignored(self):
        """Comments not matching any feature are ignored."""
        orphan_comments = [
            {
                "anchor_text": "text that appears nowhere",
                "author": "Ghost",
                "date": "2026-01-01",
                "comment_text": "This should not appear",
            }
        ]
        features = extract_features(SAMPLE_PRD, orphan_comments, ID_COLS, STORY_COLS)
        for f in features:
            assert "Ghost" not in f["prd_comments"]
