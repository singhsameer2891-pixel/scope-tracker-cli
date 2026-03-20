"""Manage conflict resolution by reading Slack replies to conflict messages.

For each unresolved conflict in run_state.json, checks if the Slack thread
has new replies using the direct Slack API. If a reply is found, uses the LLM
to parse the resolution and applies it to the sheet and run_state.

All stdout output is JSON. Human-readable logs go to stderr.

Args:
    --project-dir: Path to the project directory
    --config: Path to scope_tracker_config.json
    --project: Project name

Returns (stdout JSON):
    {"status": "no pending conflicts"} — if no unresolved conflicts
    {"status": "ok", "resolved_count": N, "pending_count": N} — after processing
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

from scope_tracker.scripts.call_llm import call_llm
from scope_tracker.scripts.slack_client import (
    fetch_thread_replies,
    fetch_user_display_name,
    get_message_permalink,
    load_slack_credentials,
    resolve_channel_id,
)


# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))


def _log(msg: str) -> None:
    """Log a message to stderr."""
    print(msg, file=sys.stderr)


def _load_json(path: str) -> dict:
    """Load a JSON file, returning empty dict on error.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON dict, or empty dict if file not found or invalid.
    """
    path = os.path.expanduser(os.path.abspath(path))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_config(config_path: str, project_name: str) -> tuple[dict, dict]:
    """Load config and find the project.

    Args:
        config_path: Path to scope_tracker_config.json.
        project_name: Name of the project.

    Returns:
        Tuple of (full config, project config).
    """
    config_path = os.path.expanduser(os.path.abspath(config_path))
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _log(f"Error reading config: {e}")
        sys.exit(1)

    for proj in config.get("projects", []):
        if proj["name"] == project_name:
            return config, proj

    _log(f"Project '{project_name}' not found in config.")
    sys.exit(1)


def run(project_dir: str, config_path: str, project_name: str) -> dict:
    """Execute conflict resolution check.

    Reads unresolved conflicts from run_state.json. For each, checks if the
    Slack thread has a reply using the direct Slack API. If so, parses the
    reply via LLM and applies the resolution to the sheet and run_state.

    Args:
        project_dir: Path to the project directory.
        config_path: Path to scope_tracker_config.json.
        project_name: Name of the project.

    Returns:
        Result dict with status, resolved_count, and pending_count.
    """
    project_dir = os.path.expanduser(os.path.abspath(project_dir))
    system_dir = os.path.join(project_dir, "system")
    os.makedirs(system_dir, exist_ok=True)

    config, project_config = _load_config(config_path, project_name)
    base_dir = os.path.dirname(project_dir)
    prompts_dir = os.path.join(base_dir, "prompts")

    # Load run state
    state_path = os.path.join(system_dir, f"{project_name}_run_state.json")
    run_state = _load_json(state_path)
    conflicts = run_state.get("conflicts", [])

    # Filter to unresolved conflicts
    unresolved = [c for c in conflicts if not c.get("resolved", False)]

    if not unresolved:
        _log("No pending conflicts to resolve.")
        return {"status": "no pending conflicts"}

    _log(f"Found {len(unresolved)} unresolved conflict(s). Checking for replies...")

    # Load Slack credentials for direct API calls
    mcp_json_path = os.path.join(base_dir, ".mcp.json")
    try:
        creds = load_slack_credentials(mcp_json_path)
    except RuntimeError as e:
        _log(f"Error loading Slack credentials: {e}")
        sys.exit(1)

    bot_token = creds["bot_token"]

    # Resolve the reporting channel ID
    reporting_channel = config.get("global_settings", {}).get(
        "reporting_slack_channel", "scope-tracker"
    )
    try:
        channel_id = resolve_channel_id(bot_token, reporting_channel)
    except RuntimeError as e:
        _log(f"Error resolving reporting channel '{reporting_channel}': {e}")
        sys.exit(1)

    resolved_count = 0

    for conflict in unresolved:
        conflict_id = conflict.get("id", "unknown")
        slack_message_ts = conflict.get("slack_message_ts")

        if not slack_message_ts:
            _log(f"Conflict {conflict_id}: no slack_message_ts, skipping.")
            continue

        # Fetch thread replies via direct Slack API
        try:
            replies = fetch_thread_replies(bot_token, channel_id, slack_message_ts)
        except RuntimeError as e:
            _log(f"Conflict {conflict_id}: error checking replies: {e}")
            continue

        # Find reply (skip the original message, take the latest reply)
        reply_text = None
        reply_user_id = None
        reply_ts = None
        for msg in replies:
            if msg.get("ts") != slack_message_ts:
                reply_text = msg.get("text", "")
                reply_user_id = msg.get("user", "")
                reply_ts = msg.get("ts", "")

        if not reply_text:
            _log(f"Conflict {conflict_id}: no reply found yet.")
            continue

        _log(f"Conflict {conflict_id}: reply found, parsing resolution...")

        # Parse the reply using conflict_resolve.md (LLM needed for semantic interpretation)
        conflict_json_path = os.path.join(
            system_dir, f"{project_name}_conflict_{conflict_id.replace(':', '_')}.json"
        )
        resolve_output_path = os.path.join(
            system_dir, f"{project_name}_resolve_{conflict_id.replace(':', '_')}.json"
        )

        with open(conflict_json_path, "w", encoding="utf-8") as f:
            json.dump(conflict, f, indent=2)

        try:
            call_llm(
                prompt_file=os.path.join(prompts_dir, "conflict_resolve.md"),
                placeholders={
                    "CONFLICT_JSON": conflict_json_path,
                    "REPLY_TEXT": reply_text,
                    "OUTPUT_PATH": resolve_output_path,
                },
                cwd=base_dir,
            )
        except RuntimeError as e:
            _log(f"Conflict {conflict_id}: error parsing resolution: {e}")
            continue

        # Read resolution
        resolution = _load_json(resolve_output_path)
        if not resolution.get("resolved", False):
            _log(f"Conflict {conflict_id}: reply did not resolve the conflict.")
            continue

        # Apply resolution
        resolved_value = resolution.get("resolved_value", "")
        resolution_text = resolution.get("resolution_text", "")
        now_str = datetime.now(IST).strftime("%Y-%m-%d")

        # Look up the Slack username and message permalink
        display_name = fetch_user_display_name(bot_token, reply_user_id or "")
        permalink = get_message_permalink(bot_token, channel_id, reply_ts or "")

        # Build the resolution string for the Conflict Resolution column
        if permalink:
            resolution_entry = f"[{now_str} @{display_name} via Slack ({permalink})]: {resolution_text}"
        else:
            resolution_entry = f"[{now_str} @{display_name} via Slack]: {resolution_text}"

        # Update the conflict in run_state
        conflict["resolved"] = True
        conflict["resolved_at"] = datetime.now(IST).isoformat()
        conflict["resolution"] = resolution_entry

        # Prepare sheet updates (the actual sheet write will happen via sheet_manager
        # or the pipeline will handle it). Store the resolution for the pipeline to apply.
        state_updates_path = os.path.join(
            system_dir, f"{project_name}_state_updates.json"
        )
        state_updates = _load_json(state_updates_path) if os.path.exists(state_updates_path) else {}
        if "conflict_resolutions" not in state_updates:
            state_updates["conflict_resolutions"] = []
        state_updates["conflict_resolutions"].append({
            "conflict_id": conflict_id,
            "resolved_value": resolved_value,
            "resolution_entry": resolution_entry,
        })
        with open(state_updates_path, "w", encoding="utf-8") as f:
            json.dump(state_updates, f, indent=2)

        resolved_count += 1
        _log(f"Conflict {conflict_id}: resolved → {resolved_value}")

    # Write updated conflicts back to run_state
    run_state["conflicts"] = conflicts
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(run_state, f, indent=2, ensure_ascii=False)
    except OSError as e:
        _log(f"Error writing run_state: {e}")

    pending_count = len([c for c in conflicts if not c.get("resolved", False)])

    return {
        "status": "ok",
        "resolved_count": resolved_count,
        "pending_count": pending_count,
    }


def main() -> None:
    """CLI entry point for conflict_manager.py."""
    parser = argparse.ArgumentParser(description="Resolve conflicts via Slack replies.")
    parser.add_argument("--project-dir", required=True, help="Path to the project directory.")
    parser.add_argument("--config", required=True, help="Path to scope_tracker_config.json.")
    parser.add_argument("--project", required=True, help="Project name.")
    args = parser.parse_args()

    result = run(args.project_dir, args.config, args.project)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
