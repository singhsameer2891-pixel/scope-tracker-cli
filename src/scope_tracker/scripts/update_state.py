"""Persist run metadata to run_state.json after each pipeline run.

Deep-merges updates into the existing run_state.json for a project.
Handles prd.last_modified, slack.last_run_timestamp,
slack.seen_thread_ids (append without overwrite), conflicts (merge by id),
and sheet.last_row_number.

All stdout is JSON. Human-readable logs go to stderr.

Args:
    --project-dir: Path to the project directory
    --config: Path to scope_tracker_config.json
    --project: Project name
    --updates-file: Path to a JSON file containing the updates to merge
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def _load_json(path: str) -> dict:
    """Load a JSON file, returning empty dict on error."""
    path = os.path.expanduser(os.path.abspath(path))
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _deep_merge_state(existing: dict, updates: dict) -> dict:
    """Deep-merge updates into existing run_state.

    Special handling:
    - slack.seen_thread_ids: append new IDs, do not overwrite
    - conflicts: merge by id field, update existing or add new
    - All other fields: overwrite with update value

    Args:
        existing: Current run_state dict.
        updates: Updates dict to merge in.

    Returns:
        Merged run_state dict.
    """
    result = existing.copy()

    for key, value in updates.items():
        if key == "slack" and isinstance(value, dict):
            existing_slack = result.get("slack", {})
            merged_slack = existing_slack.copy()

            for sk, sv in value.items():
                if sk == "seen_thread_ids" and isinstance(sv, list):
                    # Append new thread IDs without duplicates
                    existing_ids = set(merged_slack.get("seen_thread_ids", []))
                    for tid in sv:
                        existing_ids.add(tid)
                    merged_slack["seen_thread_ids"] = sorted(existing_ids)
                else:
                    merged_slack[sk] = sv

            result["slack"] = merged_slack

        elif key == "conflicts" and isinstance(value, list):
            # Merge conflicts by id — never overwrite a resolved conflict
            # with an unresolved one (prevents Step 3 re-raising what Step 0 resolved)
            existing_conflicts = {c["id"]: c for c in result.get("conflicts", [])}
            for conflict in value:
                cid = conflict["id"]
                existing = existing_conflicts.get(cid)
                if existing and existing.get("resolved") and not conflict.get("resolved"):
                    continue  # Preserve the resolved state
                existing_conflicts[cid] = conflict
            result["conflicts"] = list(existing_conflicts.values())

        elif key == "prd" and isinstance(value, dict):
            existing_prd = result.get("prd", {})
            merged_prd = existing_prd.copy()
            merged_prd.update(value)
            result["prd"] = merged_prd

        elif key == "sheet" and isinstance(value, dict):
            existing_sheet = result.get("sheet", {})
            merged_sheet = existing_sheet.copy()
            merged_sheet.update(value)
            result["sheet"] = merged_sheet

        else:
            result[key] = value

    return result


def run(project_dir: str, config_path: str, project_name: str, updates_file: str) -> dict:
    """Execute the state update.

    Args:
        project_dir: Path to the project directory.
        config_path: Path to scope_tracker_config.json (unused but kept for consistent interface).
        project_name: Name of the project.
        updates_file: Path to a JSON file with updates to merge.

    Returns:
        Result dict with status.
    """
    project_dir = os.path.expanduser(os.path.abspath(project_dir))
    system_dir = os.path.join(project_dir, "system")
    os.makedirs(system_dir, exist_ok=True)

    state_path = os.path.join(system_dir, f"{project_name}_run_state.json")
    now_iso = datetime.now(timezone.utc).astimezone().isoformat()

    # Load existing state
    existing = _load_json(state_path)

    # Initialize _meta if missing
    if "_meta" not in existing:
        existing["_meta"] = {"created": now_iso}

    # Load updates
    updates = _load_json(updates_file)
    if not updates:
        print(f"No updates to apply (file empty or not found: {updates_file}).", file=sys.stderr)
        return {"status": "no updates"}

    # Merge
    merged = _deep_merge_state(existing, updates)
    merged["_meta"]["last_updated"] = now_iso

    # Write
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
    except OSError as e:
        print(f"Error writing run_state.json: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"State updated for '{project_name}' at {state_path}.", file=sys.stderr)
    return {"status": "updated", "state_path": state_path}


def main() -> None:
    """CLI entry point for update_state.py."""
    parser = argparse.ArgumentParser(description="Update run_state.json for a project.")
    parser.add_argument("--project-dir", required=True, help="Path to the project directory.")
    parser.add_argument("--config", required=True, help="Path to scope_tracker_config.json.")
    parser.add_argument("--project", required=True, help="Project name.")
    parser.add_argument("--updates-file", required=True, help="Path to JSON updates file.")
    args = parser.parse_args()

    result = run(args.project_dir, args.config, args.project, args.updates_file)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
