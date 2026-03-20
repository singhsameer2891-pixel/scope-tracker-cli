"""Check if there are new Slack messages since the last run watermark.

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

from scope_tracker.scripts.call_llm import call_llm


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
    """Execute the Slack diff check.

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
    watermark_ts = project.get("slack_last_run_timestamp") or run_state.get("slack", {}).get("last_run_timestamp", "0")
    seen_thread_ids = json.dumps(run_state.get("slack", {}).get("seen_thread_ids", []))

    cwd = os.path.dirname(os.path.dirname(project_dir))  # scope-tracker/ root
    prompts_dir = os.path.join(cwd, "prompts")

    raw_path = os.path.join(system_dir, f"{project_name}_slack_raw.json")

    print(f"Checking Slack channel '{slack_channel}' for new messages...", file=sys.stderr)

    try:
        call_llm(
            prompt_file=os.path.join(prompts_dir, "slack_fetch.md"),
            placeholders={
                "CHANNEL": slack_channel,
                "WATERMARK_TS": watermark_ts,
                "SEEN_THREAD_IDS": seen_thread_ids,
                "OUTPUT_PATH": raw_path,
            },
            cwd=cwd,
        )
    except RuntimeError as e:
        print(f"Error fetching Slack messages: {e}", file=sys.stderr)
        sys.exit(1)

    # Read the output to check if there are new messages
    try:
        with open(raw_path, "r", encoding="utf-8") as f:
            slack_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading Slack output: {e}", file=sys.stderr)
        sys.exit(1)

    new_count = slack_data.get("new_message_count", 0)

    if new_count == 0:
        print("No new Slack messages — skipping.", file=sys.stderr)
        return {"status": "skipped (no new messages)"}

    print(f"Found {new_count} new Slack message(s).", file=sys.stderr)
    return {
        "status": "changed",
        "new_message_count": new_count,
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
