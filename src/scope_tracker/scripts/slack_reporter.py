"""Slack report builder and poster for scope-tracker.

Replaces the LLM-based slack_report.md prompt with pure Python string
formatting and direct Slack API posting.

Functions:
    build_report(project_name, run_datetime, steps_executed, run_summary, pending_conflicts) — formatted Slack message
    post_report(bot_token, channel_id, report_text) — posts to Slack via API
"""

import json
import math
import os
import sys
from datetime import datetime
from typing import Any

import requests


SLACK_API_BASE = "https://slack.com/api"
TOTAL_STEPS = 6


def _log(msg: str) -> None:
    """Log a message to stderr."""
    print(msg, file=sys.stderr)


def build_report(
    project_name: str,
    run_datetime: str,
    steps_executed: int,
    run_summary: dict[str, Any],
    pending_conflicts: list[dict[str, Any]],
) -> str:
    """Build a formatted Slack report message.

    Args:
        project_name: Name of the project.
        run_datetime: ISO format datetime string of the run.
        steps_executed: Number of pipeline steps executed.
        run_summary: Dict with prd_status, slack_new_messages, slack_decisions_found,
            rows_added, rows_updated, conflicts_detected, prd_feature_count.
        pending_conflicts: List of unresolved conflict dicts.

    Returns:
        Formatted Slack mrkdwn message string.
    """
    # Parse datetime
    try:
        dt = datetime.fromisoformat(run_datetime)
    except (ValueError, TypeError):
        dt = datetime.now()

    date_str = dt.strftime("%d %b %Y")
    time_str = dt.strftime("%H:%M")

    # PRD status
    prd_status = run_summary.get("prd_status", "unchanged")
    prd_feature_count = run_summary.get("prd_feature_count", 0)

    # Slack stats
    slack_new_messages = run_summary.get("slack_new_messages", 0)
    slack_decisions_found = run_summary.get("slack_decisions_found", 0)

    # Sheet stats
    rows_added = run_summary.get("rows_added", 0)
    rows_updated = run_summary.get("rows_updated", 0)

    # Steps percentage (round down)
    pct = math.floor((steps_executed / TOTAL_STEPS) * 100) if TOTAL_STEPS > 0 else 0

    # Build message
    lines = [
        f"*Scope Tracker \u00b7 {date_str} \u00b7 {time_str} IST*",
        "",
        f"*\U0001f4e6 {project_name}*",
        "",
        "```",
        f"PRD       {prd_status} \u00b7 {prd_feature_count} features tracked",
        f"Slack     {slack_new_messages} new messages \u00b7 {slack_decisions_found} scope decisions found",
        f"Sheet     {rows_added} rows added \u00b7 {rows_updated} rows updated",
        f"Steps     {steps_executed}/{TOTAL_STEPS} ({pct}%) executed",
        "```",
    ]

    # Conflicts section — only if there are pending conflicts
    conflict_count = len(pending_conflicts) if pending_conflicts else 0
    if conflict_count > 0:
        lines.append("")
        lines.append(f"*\u26a1 Awaiting Your Input ({conflict_count})*")

        for i, conflict in enumerate(pending_conflicts, 1):
            source_id = conflict.get("source_id", "?")
            feature_name = conflict.get("feature_name", "?")
            source_a = conflict.get("source_a", "PRD")
            value_a = conflict.get("value_a", "?")
            source_b = conflict.get("source_b", "Sheet")
            value_b = conflict.get("value_b", "?")
            lines.append(
                f'{i}. Conflict \u2014 {source_id} "{feature_name}" \u2014 '
                f'{source_a} says {value_a}, {source_b} says {value_b}. '
                f'Reply "{source_a}" or "{source_b}".'
            )

        lines.append("")
        lines.append("_Reply here \u2192 picked up on next run_")

    return "\n".join(lines)


def post_report(bot_token: str, channel_id: str, report_text: str) -> dict[str, Any]:
    """Post a report message to a Slack channel.

    Args:
        bot_token: Slack bot token (xoxb-...).
        channel_id: Slack channel ID.
        report_text: Formatted message text.

    Returns:
        Slack API response dict.

    Raises:
        RuntimeError: On HTTP errors or Slack API errors.
    """
    url = f"{SLACK_API_BASE}/chat.postMessage"
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            json={
                "channel": channel_id,
                "text": report_text,
                "mrkdwn": True,
            },
            timeout=30,
        )
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"Slack API HTTP error: {resp.status_code}") from e
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(f"Cannot connect to Slack API: {e}") from e
    except requests.exceptions.Timeout as e:
        raise RuntimeError("Slack API request timed out") from e

    data = resp.json()
    if not data.get("ok", False):
        error = data.get("error", "unknown_error")
        raise RuntimeError(f"Slack API error (chat.postMessage): {error}")

    _log(f"Report posted to channel {channel_id}")
    return data
