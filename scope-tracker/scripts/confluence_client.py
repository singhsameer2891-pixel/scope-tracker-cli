"""Confluence REST API client for fetching page metadata, content, and comments.

Replaces LLM-based Confluence fetching with direct REST API calls using `requests`.
Reads credentials from .mcp.json (ATLASSIAN_SITE_NAME, ATLASSIAN_USER_EMAIL, ATLASSIAN_API_TOKEN).

Functions:
    get_page_id_from_url(url) — extract page ID from a Confluence URL
    fetch_page_metadata(site_name, email, api_token, page_id) — get modified_time
    fetch_page_content(site_name, email, api_token, page_id) — get plain text content
    fetch_page_comments(site_name, email, api_token, page_id) — get inline comments
"""

import json
import os
import re
import sys
from html.parser import HTMLParser
from typing import Any

import requests


class _HTMLTextExtractor(HTMLParser):
    """Extract plain text from HTML, stripping all tags."""

    def __init__(self) -> None:
        super().__init__()
        self._text_parts: list[str] = []
        self._skip_tags = {"script", "style"}
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._skip_depth += 1
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._text_parts.append("\n")
        if tag == "td" or tag == "th":
            self._text_parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._text_parts.append(data)

    def get_text(self) -> str:
        """Return extracted plain text."""
        return "".join(self._text_parts).strip()


def _strip_html(html: str) -> str:
    """Strip HTML tags and return plain text.

    Args:
        html: HTML string to strip.

    Returns:
        Plain text with HTML tags removed.
    """
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text()


def _log(msg: str) -> None:
    """Log a message to stderr."""
    print(msg, file=sys.stderr)


def get_page_id_from_url(url: str) -> str:
    """Extract the Confluence page ID from a Confluence URL.

    Supports URL formats:
        - https://site.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title
        - https://site.atlassian.net/wiki/spaces/SPACE/pages/123456

    Args:
        url: Confluence page URL.

    Returns:
        Page ID as a string.

    Raises:
        ValueError: If the URL format is not recognized.
    """
    # Match /pages/{pageId} pattern
    match = re.search(r"/pages/(\d+)", url)
    if match:
        return match.group(1)

    # Match pageId query parameter
    match = re.search(r"[?&]pageId=(\d+)", url)
    if match:
        return match.group(1)

    raise ValueError(
        f"Cannot extract page ID from Confluence URL: {url}. "
        "Expected format: https://site.atlassian.net/wiki/spaces/SPACE/pages/123456/Title"
    )


def _base_url(site_name: str) -> str:
    """Build the Confluence API base URL.

    Args:
        site_name: Atlassian site name (e.g. 'mycompany' for mycompany.atlassian.net).

    Returns:
        Base URL string.
    """
    # If site_name already looks like a full domain, use it
    if "." in site_name:
        return f"https://{site_name}/wiki/api/v2"
    return f"https://{site_name}.atlassian.net/wiki/api/v2"


def _make_request(
    site_name: str, email: str, api_token: str, endpoint: str, params: dict[str, str] | None = None
) -> dict[str, Any]:
    """Make an authenticated request to the Confluence REST API.

    Args:
        site_name: Atlassian site name.
        email: Atlassian user email.
        api_token: Atlassian API token.
        endpoint: API endpoint path (e.g. '/pages/123').
        params: Optional query parameters.

    Returns:
        Parsed JSON response.

    Raises:
        RuntimeError: On HTTP errors or connection failures.
    """
    url = f"{_base_url(site_name)}{endpoint}"
    try:
        resp = requests.get(
            url,
            auth=(email, api_token),
            params=params or {},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(
            f"Confluence API error ({resp.status_code}): {resp.text[:500]}"
        ) from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Cannot connect to Confluence at {url}: {e}") from e
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"Confluence API request timed out: {url}") from e


def fetch_page_metadata(site_name: str, email: str, api_token: str, page_id: str) -> dict[str, str]:
    """Fetch page metadata to get the last modified time.

    Args:
        site_name: Atlassian site name.
        email: Atlassian user email.
        api_token: Atlassian API token.
        page_id: Confluence page ID.

    Returns:
        Dict with 'modified_time' key (ISO 8601 string).
    """
    data = _make_request(
        site_name, email, api_token,
        f"/pages/{page_id}",
        params={"include": "version"},
    )

    # version.createdAt is the last modified time in v2 API
    version = data.get("version", {})
    modified_time = version.get("createdAt", "")

    if not modified_time:
        # Fallback: try version.when (v1 style)
        modified_time = version.get("when", "")

    return {"modified_time": modified_time}


def fetch_page_content(site_name: str, email: str, api_token: str, page_id: str) -> str:
    """Fetch the full page content as plain text.

    Args:
        site_name: Atlassian site name.
        email: Atlassian user email.
        api_token: Atlassian API token.
        page_id: Confluence page ID.

    Returns:
        Plain text content of the page (HTML stripped).
    """
    data = _make_request(
        site_name, email, api_token,
        f"/pages/{page_id}",
        params={"body-format": "storage"},
    )

    body = data.get("body", {}).get("storage", {}).get("value", "")
    return _strip_html(body)


def fetch_page_comments(
    site_name: str, email: str, api_token: str, page_id: str
) -> list[dict[str, str]]:
    """Fetch inline comments on a Confluence page.

    Args:
        site_name: Atlassian site name.
        email: Atlassian user email.
        api_token: Atlassian API token.
        page_id: Confluence page ID.

    Returns:
        List of comment dicts with keys: anchor_text, author, date, comment_text.
    """
    comments: list[dict[str, str]] = []
    cursor = None

    while True:
        params: dict[str, str] = {"body-format": "storage"}
        if cursor:
            params["cursor"] = cursor

        try:
            data = _make_request(
                site_name, email, api_token,
                f"/pages/{page_id}/inline-comments",
                params=params,
            )
        except RuntimeError:
            # If inline-comments endpoint is not available, try footer comments
            try:
                data = _make_request(
                    site_name, email, api_token,
                    f"/pages/{page_id}/footer-comments",
                    params=params,
                )
            except RuntimeError:
                _log("Could not fetch comments from Confluence (inline or footer).")
                break

        results = data.get("results", [])
        for comment in results:
            body_html = comment.get("body", {}).get("storage", {}).get("value", "")
            comment_text = _strip_html(body_html)

            # Extract properties for inline comment context
            properties = comment.get("properties", {})
            anchor_text = ""
            if "inline-marker-ref" in properties:
                anchor_text = properties["inline-marker-ref"].get("value", "")
            elif "inline-original-selection" in properties:
                anchor_text = properties["inline-original-selection"].get("value", "")

            version = comment.get("version", {})
            author_data = version.get("authorId", "")
            date = version.get("createdAt", version.get("when", ""))

            # Try to get display name from author
            author = comment.get("author", {})
            author_name = author.get("displayName", author.get("publicName", author_data))

            comments.append({
                "anchor_text": anchor_text,
                "author": author_name,
                "date": date,
                "comment_text": comment_text,
            })

        # Handle pagination
        links = data.get("_links", {})
        next_link = links.get("next", "")
        if next_link and results:
            # Extract cursor from next link
            cursor_match = re.search(r"cursor=([^&]+)", next_link)
            cursor = cursor_match.group(1) if cursor_match else None
            if not cursor:
                break
        else:
            break

    return comments


def load_confluence_credentials(mcp_json_path: str) -> dict[str, str]:
    """Load Confluence credentials from .mcp.json.

    Args:
        mcp_json_path: Path to .mcp.json file.

    Returns:
        Dict with 'site_name', 'email', 'api_token' keys.

    Raises:
        RuntimeError: If credentials are missing.
    """
    mcp_json_path = os.path.expanduser(os.path.abspath(mcp_json_path))
    try:
        with open(mcp_json_path, "r", encoding="utf-8") as f:
            mcp_config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Cannot read .mcp.json at {mcp_json_path}: {e}") from e

    confluence_env = mcp_config.get("mcpServers", {}).get("confluence", {}).get("env", {})

    site_name = confluence_env.get("ATLASSIAN_SITE_NAME", "")
    email = confluence_env.get("ATLASSIAN_USER_EMAIL", "")
    api_token = confluence_env.get("ATLASSIAN_API_TOKEN", "")

    missing = []
    if not site_name:
        missing.append("ATLASSIAN_SITE_NAME")
    if not email:
        missing.append("ATLASSIAN_USER_EMAIL")
    if not api_token:
        missing.append("ATLASSIAN_API_TOKEN")

    if missing:
        raise RuntimeError(
            f"Missing Confluence credentials in .mcp.json: {', '.join(missing)}. "
            "Run `scope-tracker init` to reconfigure."
        )

    return {"site_name": site_name, "email": email, "api_token": api_token}
