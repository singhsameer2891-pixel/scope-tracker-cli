"""Check if there are new Slack messages since the last run watermark.

Uses direct Slack Web API calls via slack_client instead of LLM.
If new messages exist, fetches and writes them to a raw JSON file.
If no new messages, returns a skip result. All stdout is JSON.
Human-readable logs go to stderr.

Args:
    --project-dir: Path to the project directory (e.g. scope-tracker/scalper/)
    --config: Path to scope_tracker_config.json
    --project: Project name

Returns (stdout JSON):
    {"status": "skipped (no new messages)"} — if no new messages
    {"status": "changed", "new_message_count": N, "raw_path": "..."} — if new messages found
"""

import argparse
import json
import os
import sys

from scope_tracker.scripts.slack_client import (
    fetch_channel_history,
    fetch_thread_replies,
    load_slack_credentials,
    resolve_channel_id,
)


def _load_config(config_path: str) -> dict:
    """Load and return the scope_tracker_config.json."""
    config_path = os.path.expanduser(os.path.abspath(config_path))
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading config: {e}", file=sys.stderr)
        sys.exit(1)


def _find_project(config: dict, project_name: str) -> dict:
    """Find and return the project config dict by name."""
    for proj in config.get("projects", []):
        if proj["name"] == project_name:
            return proj
    print(f"Project '{project_name}' not found in config.", file=sys.stderr)
    sys.exit(1)


def _load_run_state(project_dir: str, project_name: str) -> dict:
    """Load the project's run_state.json, or return empty dict if not found."""
    state_path = os.path.join(
        os.path.expanduser(os.path.abspath(project_dir)),
        "system",
        f"{project_name}_run_state.json",
    )
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def run(project_dir: str, config_path: str, project_name: str) -> dict:
    """Execute the Slack diff check using direct Slack API calls.

    Args:
        project_dir: Path to the project directory.
        config_path: Path to scope_tracker_config.json.
        project_name: Name of the project.

    Returns:
        Result dict with status and optional paths.
    """
    config = _load_config(config_path)
    project = _find_project(config, project_name)

    slack_channel = project.get("slack_channel", "")
    if not slack_channel:
        return {"status": "skipped (no new messages)"}

    project_dir = os.path.expanduser(os.path.abspath(project_dir))
    system_dir = os.path.join(project_dir, "system")
    os.makedirs(system_dir, exist_ok=True)

    # Get watermark and seen thread IDs from run_state
    run_state = _load_run_state(project_dir, project_name)
    watermark_ts = project.get("slack_last_run_timestamp") or run_state.get(
        "slack", {}
    ).get("last_run_timestamp", "0")
    seen_thread_ids = run_state.get("slack", {}).get("seen_thread_ids", [])

    # Load Slack credentials from .mcp.json
    base_dir = os.path.dirname(project_dir)
    mcp_json_path = os.path.join(base_dir, ".mcp.json")

    try:
        creds = load_slack_credentials(mcp_json_path)
    except RuntimeError as e:
        print(f"Error loading Slack credentials: {e}", file=sys.stderr)
        sys.exit(1)

    bot_token = creds["bot_token"]

    # Resolve channel name to ID
    print(f"Checking Slack channel '{slack_channel}' for new messages...", file=sys.stderr)
    try:
        channel_id = resolve_channel_id(bot_token, slack_channel)
    except RuntimeError as e:
        print(f"Error resolving Slack channel: {e}", file=sys.stderr)
        sys.exit(1)

    # Fetch channel history after watermark
    try:
        messages = fetch_channel_history(bot_token, channel_id, watermark_ts)
    except RuntimeError as e:
        print(f"Error fetching Slack history: {e}", file=sys.stderr)
        sys.exit(1)

    # Build threads structure: group messages by thread_ts
    threads_map: dict[str, dict] = {}
    new_thread_ids: list[str] = []

    for msg in messages:
        thread_ts = msg.get("thread_ts", msg.get("ts", ""))
        if thread_ts not in threads_map:
            threads_map[thread_ts] = {
                "thread_ts": thread_ts,
                "is_new": thread_ts not in seen_thread_ids,
                "messages": [],
            }
            new_thread_ids.append(thread_ts)
        threads_map[thread_ts]["messages"].append({
            "ts": msg.get("ts", ""),
            "author": msg.get("user", "unknown"),
            "text": msg.get("text", ""),
        })

    # Re-read seen threads for new replies
    for thread_id in seen_thread_ids:
        if thread_id not in threads_map:
            try:
                replies = fetch_thread_replies(bot_token, channel_id, thread_id)
                if len(replies) > 0:
                    threads_map[thread_id] = {
                        "thread_ts": thread_id,
                        "is_new": False,
                        "messages": [
                            {
                                "ts": r.get("ts", ""),
                                "author": r.get("user", "unknown"),
                                "text": r.get("text", ""),
                            }
                            for r in replies
                        ],
                    }
            except RuntimeError as e:
                print(
                    f"Warning: could not fetch replies for thread {thread_id}: {e}",
                    file=sys.stderr,
                )

    threads_list = list(threads_map.values())
    new_top_level_count = len(messages)
    # Count total messages across all threads (including new replies to seen threads)
    total_message_count = sum(len(t["messages"]) for t in threads_list)

    # Write raw output
    raw_path = os.path.join(system_dir, f"{project_name}_slack_raw.json")
    slack_data = {
        "new_message_count": total_message_count,
        "threads": threads_list,
        "latest_ts": messages[0].get("ts", watermark_ts) if messages else watermark_ts,
    }

    try:
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(slack_data, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"Error writing Slack raw output: {e}", file=sys.stderr)
        sys.exit(1)

    if total_message_count == 0:
        print("No new Slack messages — skipping.", file=sys.stderr)
        return {"status": "skipped (no new messages)"}

    print(f"Found {total_message_count} new Slack message(s) ({new_top_level_count} top-level, {total_message_count - new_top_level_count} thread replies).", file=sys.stderr)
    return {
        "status": "changed",
        "new_message_count": total_message_count,
        "raw_path": raw_path,
    }


def main() -> None:
    """CLI entry point for diff_slack.py."""
    parser = argparse.ArgumentParser(description="Check for new Slack messages.")
    parser.add_argument("--project-dir", required=True, help="Path to the project directory.")
    parser.add_argument("--config", required=True, help="Path to scope_tracker_config.json.")
    parser.add_argument("--project", required=True, help="Project name.")
    args = parser.parse_args()

    result = run(args.project_dir, args.config, args.project)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
