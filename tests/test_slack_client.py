"""Tests for slack_client.py — Slack Web API client.

Tests:
    (a) channel history returns messages
    (b) thread replies returns replies
    (c) channel name resolves to ID
    (d) pagination handled
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from scope_tracker.scripts.slack_client import (
    resolve_channel_id,
    fetch_channel_history,
    fetch_thread_replies,
    load_slack_credentials,
)


def _mock_slack_response(data: dict, ok: bool = True) -> MagicMock:
    """Create a mock requests.post response for Slack API."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    response_data = {"ok": ok, **data}
    mock_resp.json.return_value = response_data
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestResolveChannelId:
    """Test channel name to ID resolution."""

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_resolves_channel_name(self, mock_post):
        mock_post.return_value = _mock_slack_response({
            "channels": [
                {"id": "C123", "name": "general"},
                {"id": "C456", "name": "demo-scope"},
            ],
            "response_metadata": {"next_cursor": ""},
        })

        result = resolve_channel_id("xoxb-token", "demo-scope")
        assert result == "C456"

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_strips_hash_prefix(self, mock_post):
        mock_post.return_value = _mock_slack_response({
            "channels": [{"id": "C789", "name": "scope-tracker"}],
            "response_metadata": {"next_cursor": ""},
        })

        result = resolve_channel_id("xoxb-token", "#scope-tracker")
        assert result == "C789"

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_not_found_raises(self, mock_post):
        mock_post.return_value = _mock_slack_response({
            "channels": [{"id": "C123", "name": "other"}],
            "response_metadata": {"next_cursor": ""},
        })

        with pytest.raises(RuntimeError, match="not found"):
            resolve_channel_id("xoxb-token", "nonexistent")

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_pagination(self, mock_post):
        """Channel found on second page."""
        mock_post.side_effect = [
            _mock_slack_response({
                "channels": [{"id": "C001", "name": "alpha"}],
                "response_metadata": {"next_cursor": "page2cursor"},
            }),
            _mock_slack_response({
                "channels": [{"id": "C002", "name": "target"}],
                "response_metadata": {"next_cursor": ""},
            }),
        ]

        result = resolve_channel_id("xoxb-token", "target")
        assert result == "C002"
        assert mock_post.call_count == 2


class TestFetchChannelHistory:
    """Test channel history fetching."""

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_returns_messages(self, mock_post):
        messages = [
            {"ts": "1773910000.000001", "text": "Hello", "user": "U123"},
            {"ts": "1773910001.000001", "text": "World", "user": "U456"},
        ]
        mock_post.return_value = _mock_slack_response({
            "messages": messages,
            "response_metadata": {"next_cursor": ""},
        })

        result = fetch_channel_history("xoxb-token", "C123", "0")
        assert len(result) == 2
        assert result[0]["text"] == "Hello"
        assert result[1]["text"] == "World"

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_pagination(self, mock_post):
        """Messages spread across two pages."""
        mock_post.side_effect = [
            _mock_slack_response({
                "messages": [{"ts": "1.0", "text": "Page 1"}],
                "response_metadata": {"next_cursor": "cursor2"},
            }),
            _mock_slack_response({
                "messages": [{"ts": "2.0", "text": "Page 2"}],
                "response_metadata": {"next_cursor": ""},
            }),
        ]

        result = fetch_channel_history("xoxb-token", "C123", "0")
        assert len(result) == 2
        assert mock_post.call_count == 2

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_empty_history(self, mock_post):
        mock_post.return_value = _mock_slack_response({
            "messages": [],
            "response_metadata": {"next_cursor": ""},
        })

        result = fetch_channel_history("xoxb-token", "C123", "0")
        assert result == []

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_passes_oldest_param(self, mock_post):
        mock_post.return_value = _mock_slack_response({
            "messages": [],
            "response_metadata": {"next_cursor": ""},
        })

        fetch_channel_history("xoxb-token", "C123", "1773901583.351119")

        call_data = mock_post.call_args[1].get("data", {})
        assert call_data["oldest"] == "1773901583.351119"


class TestFetchThreadReplies:
    """Test thread replies fetching."""

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_returns_replies(self, mock_post):
        messages = [
            {"ts": "1773910000.000001", "text": "Parent message", "user": "U123"},
            {"ts": "1773910000.000002", "text": "Reply 1", "user": "U456"},
            {"ts": "1773910000.000003", "text": "Reply 2", "user": "U789"},
        ]
        mock_post.return_value = _mock_slack_response({
            "messages": messages,
            "response_metadata": {"next_cursor": ""},
        })

        result = fetch_thread_replies("xoxb-token", "C123", "1773910000.000001")
        assert len(result) == 3
        assert result[0]["text"] == "Parent message"
        assert result[2]["text"] == "Reply 2"

    @patch("scope_tracker.scripts.slack_client.requests.post")
    def test_api_error_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": False, "error": "channel_not_found"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        with pytest.raises(RuntimeError, match="channel_not_found"):
            fetch_thread_replies("xoxb-token", "C123", "1.0")


class TestLoadSlackCredentials:
    """Test credential loading from .mcp.json."""

    def test_loads_token(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(json.dumps({
            "mcpServers": {
                "slack": {
                    "command": "npx",
                    "args": [],
                    "env": {"SLACK_BOT_TOKEN": "xoxb-test-token", "SLACK_TEAM_ID": "T123"},
                }
            }
        }))

        result = load_slack_credentials(str(mcp_path))
        assert result["bot_token"] == "xoxb-test-token"

    def test_missing_token_raises(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(json.dumps({"mcpServers": {"slack": {"env": {}}}}))

        with pytest.raises(RuntimeError, match="Missing SLACK_BOT_TOKEN"):
            load_slack_credentials(str(mcp_path))
