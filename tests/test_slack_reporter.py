"""Tests for slack_reporter.py — Slack report builder and poster.

Tests:
    (a) Report includes project name and run date
    (b) Omits conflict section when count=0
    (c) Includes each conflict as bullet when count>0
    (d) post_report calls Slack API
"""

from unittest.mock import patch, MagicMock

import pytest
from scope_tracker.scripts.slack_reporter import build_report, post_report


SAMPLE_SUMMARY = {
    "prd_status": "updated",
    "prd_feature_count": 5,
    "slack_new_messages": 12,
    "slack_decisions_found": 3,
    "rows_added": 2,
    "rows_updated": 4,
    "conflicts_detected": 1,
}

SAMPLE_CONFLICTS = [
    {
        "source_id": "PRD:1.3",
        "feature_name": "Real-time P&L",
        "source_a": "PRD",
        "value_a": "In Scope",
        "source_b": "Sheet",
        "value_b": "Pushed to V2",
    },
    {
        "source_id": "SLACK:1234.5678",
        "feature_name": "CSV Export",
        "source_a": "Slack",
        "value_a": "Fast Follower",
        "source_b": "Sheet",
        "value_b": "In Scope",
    },
]


class TestBuildReport:
    def test_includes_project_name_and_date(self):
        """(a) Report includes project name and run date."""
        report = build_report(
            project_name="my-project",
            run_datetime="2026-03-19T14:30:00+05:30",
            steps_executed=5,
            run_summary=SAMPLE_SUMMARY,
            pending_conflicts=[],
        )
        assert "my-project" in report
        assert "19 Mar 2026" in report
        assert "14:30" in report

    def test_includes_summary_stats(self):
        report = build_report(
            project_name="test",
            run_datetime="2026-03-19T10:00:00",
            steps_executed=6,
            run_summary=SAMPLE_SUMMARY,
            pending_conflicts=[],
        )
        assert "updated" in report
        assert "5 features tracked" in report
        assert "12 new messages" in report
        assert "3 scope decisions found" in report
        assert "2 rows added" in report
        assert "4 rows updated" in report
        assert "6/6 (100%) executed" in report

    def test_steps_percentage_rounds_down(self):
        report = build_report(
            project_name="test",
            run_datetime="2026-03-19T10:00:00",
            steps_executed=5,
            run_summary=SAMPLE_SUMMARY,
            pending_conflicts=[],
        )
        assert "5/6 (83%) executed" in report

    def test_omits_conflict_section_when_no_conflicts(self):
        """(b) Omits conflict section when count=0."""
        report = build_report(
            project_name="test",
            run_datetime="2026-03-19T10:00:00",
            steps_executed=6,
            run_summary=SAMPLE_SUMMARY,
            pending_conflicts=[],
        )
        assert "Awaiting Your Input" not in report
        assert "Reply here" not in report

    def test_includes_conflicts_as_bullets(self):
        """(c) Includes each conflict as bullet when count>0."""
        report = build_report(
            project_name="test",
            run_datetime="2026-03-19T10:00:00",
            steps_executed=6,
            run_summary=SAMPLE_SUMMARY,
            pending_conflicts=SAMPLE_CONFLICTS,
        )
        assert "Awaiting Your Input (2)" in report
        assert 'PRD:1.3' in report
        assert '"Real-time P&L"' in report
        assert 'PRD says In Scope' in report
        assert 'Sheet says Pushed to V2' in report
        assert 'SLACK:1234.5678' in report
        assert '"CSV Export"' in report
        assert "Reply here" in report

    def test_conflict_numbering(self):
        report = build_report(
            project_name="test",
            run_datetime="2026-03-19T10:00:00",
            steps_executed=6,
            run_summary=SAMPLE_SUMMARY,
            pending_conflicts=SAMPLE_CONFLICTS,
        )
        assert "1. Conflict" in report
        assert "2. Conflict" in report


class TestPostReport:
    @patch("scope_tracker.scripts.slack_reporter.requests.post")
    def test_posts_to_slack_api(self, mock_post):
        """(d) post_report calls Slack API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "ts": "1234567890.123456"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = post_report("xoxb-test-token", "C12345", "Hello report")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "chat.postMessage" in call_kwargs[0][0] or "chat.postMessage" in str(call_kwargs)
        assert result["ok"] is True

    @patch("scope_tracker.scripts.slack_reporter.requests.post")
    def test_raises_on_api_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        with pytest.raises(RuntimeError, match="channel_not_found"):
            post_report("xoxb-test", "C12345", "report")

    @patch("scope_tracker.scripts.slack_reporter.requests.post")
    def test_sends_correct_payload(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        post_report("xoxb-token", "C99999", "My report text")

        call_kwargs = mock_post.call_args
        payload = call_kwargs.kwargs.get("json", call_kwargs[1].get("json", {}))
        assert payload["channel"] == "C99999"
        assert payload["text"] == "My report text"
