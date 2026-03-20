"""Tests for confluence_client.py — Confluence REST API client.

Tests:
    (a) metadata returns modified_time
    (b) content returns plain text (HTML stripped)
    (c) comments returns list of comment dicts
    (d) invalid URL raises clear error
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from scope_tracker.scripts.confluence_client import (
    get_page_id_from_url,
    fetch_page_metadata,
    fetch_page_content,
    fetch_page_comments,
    load_confluence_credentials,
    _strip_html,
)


class TestGetPageIdFromUrl:
    """Test URL parsing for page ID extraction."""

    def test_standard_url(self):
        url = "https://mysite.atlassian.net/wiki/spaces/PROJ/pages/123456/My+Page"
        assert get_page_id_from_url(url) == "123456"

    def test_url_without_title(self):
        url = "https://mysite.atlassian.net/wiki/spaces/PROJ/pages/789012"
        assert get_page_id_from_url(url) == "789012"

    def test_url_with_query_param(self):
        url = "https://mysite.atlassian.net/wiki/page?pageId=555666"
        assert get_page_id_from_url(url) == "555666"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError, match="Cannot extract page ID"):
            get_page_id_from_url("https://mysite.atlassian.net/wiki/spaces/PROJ/overview")


class TestStripHtml:
    """Test HTML stripping."""

    def test_strips_tags(self):
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_preserves_line_breaks(self):
        text = _strip_html("<p>Line one</p><p>Line two</p>")
        assert "Line one" in text
        assert "Line two" in text

    def test_strips_script(self):
        assert _strip_html("<script>alert('hi')</script>Hello") == "Hello"


class TestFetchPageMetadata:
    """Test metadata fetching."""

    @patch("scope_tracker.scripts.confluence_client.requests.get")
    def test_returns_modified_time(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "123456",
            "version": {
                "createdAt": "2026-03-18T10:00:00.000Z",
                "number": 5,
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_page_metadata("mysite", "user@example.com", "token123", "123456")

        assert result["modified_time"] == "2026-03-18T10:00:00.000Z"
        mock_get.assert_called_once()
        call_args = mock_get.call_args
        assert "123456" in call_args[0][0]

    @patch("scope_tracker.scripts.confluence_client.requests.get")
    def test_http_error_raises_runtime(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "Not Found"
        mock_resp.raise_for_status.side_effect = Exception("404")
        mock_get.return_value = mock_resp

        # The function catches HTTPError specifically, but generic Exception
        # from raise_for_status will propagate differently. Let's test properly.
        import requests as req
        mock_resp.raise_for_status.side_effect = req.exceptions.HTTPError("404")
        mock_get.return_value = mock_resp

        with pytest.raises(RuntimeError, match="Confluence API error"):
            fetch_page_metadata("mysite", "user@example.com", "token123", "123456")


class TestFetchPageContent:
    """Test content fetching."""

    @patch("scope_tracker.scripts.confluence_client.requests.get")
    def test_returns_plain_text(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "123456",
            "body": {
                "storage": {
                    "value": "<h1>User Stories</h1><p>Feature A: <b>important</b> stuff</p>",
                }
            },
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_page_content("mysite", "user@example.com", "token123", "123456")

        assert "User Stories" in result
        assert "Feature A" in result
        assert "important" in result
        # HTML tags should be stripped
        assert "<h1>" not in result
        assert "<b>" not in result


class TestFetchPageComments:
    """Test comment fetching."""

    @patch("scope_tracker.scripts.confluence_client.requests.get")
    def test_returns_comment_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "body": {"storage": {"value": "<p>This needs clarification</p>"}},
                    "properties": {
                        "inline-original-selection": {"value": "Feature A description"},
                    },
                    "version": {
                        "createdAt": "2026-03-19T12:00:00.000Z",
                        "authorId": "user123",
                    },
                    "author": {"displayName": "Jane Doe"},
                }
            ],
            "_links": {},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_page_comments("mysite", "user@example.com", "token123", "123456")

        assert len(result) == 1
        assert result[0]["comment_text"] == "This needs clarification"
        assert result[0]["anchor_text"] == "Feature A description"
        assert result[0]["author"] == "Jane Doe"
        assert result[0]["date"] == "2026-03-19T12:00:00.000Z"

    @patch("scope_tracker.scripts.confluence_client.requests.get")
    def test_empty_comments(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": [], "_links": {}}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        result = fetch_page_comments("mysite", "user@example.com", "token123", "123456")
        assert result == []


class TestLoadConfluenceCredentials:
    """Test credential loading from .mcp.json."""

    def test_loads_credentials(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(json.dumps({
            "mcpServers": {
                "confluence": {
                    "command": "npx",
                    "args": [],
                    "env": {
                        "ATLASSIAN_SITE_NAME": "mysite",
                        "ATLASSIAN_USER_EMAIL": "user@example.com",
                        "ATLASSIAN_API_TOKEN": "secret",
                    },
                }
            }
        }))

        result = load_confluence_credentials(str(mcp_path))
        assert result["site_name"] == "mysite"
        assert result["email"] == "user@example.com"
        assert result["api_token"] == "secret"

    def test_missing_credentials_raises(self, tmp_path):
        mcp_path = tmp_path / ".mcp.json"
        mcp_path.write_text(json.dumps({"mcpServers": {}}))

        with pytest.raises(RuntimeError, match="Missing Confluence credentials"):
            load_confluence_credentials(str(mcp_path))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="Cannot read .mcp.json"):
            load_confluence_credentials(str(tmp_path / "nonexistent.json"))
