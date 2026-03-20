"""Slack Web API client for fetching channel history and thread replies.

Replaces LLM-based Slack data fetching with direct API calls using `requests`.
Reads SLACK_BOT_TOKEN from .mcp.json.

Functions:
    resolve_channel_id(bot_token, channel_name) — get channel ID from name
    fetch_channel_history(bot_token, channel_id, oldest_ts) — get messages after timestamp
    fetch_thread_replies(bot_token, channel_id, thread_ts) — get replies in a thread
    load_slack_credentials(mcp_json_path) — load bot token from .mcp.json
"""

import json
import os
import sys
from typing import Any

import requests


SLACK_API_BASE = "https://slack.com/api"


def _log(msg: str) -> None:
    """Log a message to stderr."""
    print(msg, file=sys.stderr)


def _slack_api(
    bot_token: str, method: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Make an authenticated request to the Slack Web API.

    Args:
        bot_token: Slack bot token (xoxb-...).
        method: Slack API method name (e.g. 'conversations.history').
        params: Optional request parameters.

    Returns:
        Parsed JSON response.

    Raises:
        RuntimeError: On HTTP errors, connection failures, or Slack API errors.
    """
    url = f"{SLACK_API_BASE}/{method}"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=params or {},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Slack API HTTP error ({resp.status_code}): {resp.text[:500]}") from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Cannot connect to Slack API: {e}") from e
    except requests.exceptions.Timeout as e:
        raise RuntimeError(f"Slack API request timed out: {method}") from e

    data = resp.json()
    if not data.get("ok", False):
        error = data.get("error", "unknown_error")
        raise RuntimeError(f"Slack API error ({method}): {error}")

    return data


def resolve_channel_id(bot_token: str, channel_name: str) -> str:
    """Resolve a Slack channel name to its channel ID.

    Handles channel names with or without the '#' prefix.

    Args:
        bot_token: Slack bot token.
        channel_name: Channel name (e.g. 'general' or '#general').

    Returns:
        Channel ID string.

    Raises:
        RuntimeError: If the channel cannot be found.
    """
    # Strip leading '#' if present
    name = channel_name.lstrip("#")

    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 200, "types": "public_channel,private_channel"}
        if cursor:
            params["cursor"] = cursor

        data = _slack_api(bot_token, "conversations.list", params)
        channels = data.get("channels", [])

        for ch in channels:
            if ch.get("name") == name:
                return ch["id"]

        # Handle pagination
        next_cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if next_cursor:
            cursor = next_cursor
        else:
            break

    raise RuntimeError(
        f"Slack channel '{channel_name}' not found. "
        "Ensure the bot is invited to the channel."
    )


def fetch_channel_history(
    bot_token: str, channel_id: str, oldest_ts: str = "0"
) -> list[dict[str, Any]]:
    """Fetch channel messages after the given timestamp.

    Handles pagination to retrieve all messages.

    Args:
        bot_token: Slack bot token.
        channel_id: Slack channel ID.
        oldest_ts: Only fetch messages after this timestamp (exclusive).

    Returns:
        List of message dicts from the Slack API, newest first.
    """
    all_messages: list[dict[str, Any]] = []
    cursor = None

    while True:
        params: dict[str, Any] = {
            "channel": channel_id,
            "oldest": oldest_ts,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor

        data = _slack_api(bot_token, "conversations.history", params)
        messages = data.get("messages", [])
        all_messages.extend(messages)

        next_cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if next_cursor and messages:
            cursor = next_cursor
        else:
            break

    return all_messages


def fetch_thread_replies(
    bot_token: str, channel_id: str, thread_ts: str
) -> list[dict[str, Any]]:
    """Fetch all replies in a Slack thread.

    Args:
        bot_token: Slack bot token.
        channel_id: Slack channel ID.
        thread_ts: Thread timestamp (ts of the parent message).

    Returns:
        List of message dicts in the thread (including the parent message).
    """
    all_messages: list[dict[str, Any]] = []
    cursor = None

    while True:
        params: dict[str, Any] = {
            "channel": channel_id,
            "ts": thread_ts,
            "limit": 200,
        }
        if cursor:
            params["cursor"] = cursor

        data = _slack_api(bot_token, "conversations.replies", params)
        messages = data.get("messages", [])
        all_messages.extend(messages)

        next_cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if next_cursor and messages:
            cursor = next_cursor
        else:
            break

    return all_messages


def fetch_user_display_name(bot_token: str, user_id: str) -> str:
    """Fetch a Slack user's display name by user ID.

    Args:
        bot_token: Slack bot token.
        user_id: Slack user ID (e.g. 'U01ABC123').

    Returns:
        Display name string, or user_id if lookup fails.
    """
    if not user_id:
        return "Unknown"
    try:
        data = _slack_api(bot_token, "users.info", {"user": user_id})
        profile = data.get("user", {}).get("profile", {})
        name = (
            profile.get("display_name")
            or profile.get("real_name")
            or data.get("user", {}).get("name")
            or user_id
        )
        return name
    except RuntimeError:
        return user_id


def get_message_permalink(bot_token: str, channel_id: str, message_ts: str) -> str:
    """Get the permalink URL for a Slack message.

    Args:
        bot_token: Slack bot token.
        channel_id: Slack channel ID.
        message_ts: Message timestamp string.

    Returns:
        Permalink URL string, or empty string if lookup fails.
    """
    if not channel_id or not message_ts:
        return ""
    try:
        data = _slack_api(
            bot_token, "chat.getPermalink", {"channel": channel_id, "message_ts": message_ts}
        )
        return data.get("permalink", "")
    except RuntimeError:
        return ""


def load_slack_credentials(mcp_json_path: str) -> dict[str, str]:
    """Load Slack credentials from .mcp.json.

    Args:
        mcp_json_path: Path to .mcp.json file.

    Returns:
        Dict with 'bot_token' key.

    Raises:
        RuntimeError: If SLACK_BOT_TOKEN is missing.
    """
    mcp_json_path = os.path.expanduser(os.path.abspath(mcp_json_path))
    try:
        with open(mcp_json_path, "r", encoding="utf-8") as f:
            mcp_config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        raise RuntimeError(f"Cannot read .mcp.json at {mcp_json_path}: {e}") from e

    slack_env = mcp_config.get("mcpServers", {}).get("slack", {}).get("env", {})
    bot_token = slack_env.get("SLACK_BOT_TOKEN", "")

    if not bot_token:
        raise RuntimeError(
            "Missing SLACK_BOT_TOKEN in .mcp.json. "
            "Run `scope-tracker init` to reconfigure."
        )

    return {"bot_token": bot_token}
