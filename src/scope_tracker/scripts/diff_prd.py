"""Check if the PRD source document has changed since the last run.

If changed, fetches full content and inline comments via MCP.
If unchanged, returns a skip result. All stdout is JSON.
Human-readable logs go to stderr.

Args:
    --project-dir: Path to the project directory (e.g. scope-tracker/scalper/)
    --config: Path to scope_tracker_config.json
    --project: Project name

Returns (stdout JSON):
    {"status": "not configured"} — if prd_source.type is "none"
    {"status": "skipped (unchanged)", "last_modified": "..."} — if mtime unchanged
    {"status": "changed", "last_modified": "...", "raw_path": "...", "comments_path": "..."} — if changed
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


def run(project_dir: str, config_path: str, project_name: str, force: bool = False) -> dict:
    """Execute the PRD diff check.

    Args:
        project_dir: Path to the project directory.
        config_path: Path to scope_tracker_config.json.
        project_name: Name of the project.

    Returns:
        Result dict with status and optional paths.
    """
    config = _load_config(config_path)
    project = _find_project(config, project_name)
    prd_source = project.get("prd_source", {})

    # Check if PRD is configured
    source_type = prd_source.get("type", "none")
    if source_type == "none":
        return {"status": "not configured"}

    project_dir = os.path.expanduser(os.path.abspath(project_dir))
    system_dir = os.path.join(project_dir, "system")
    os.makedirs(system_dir, exist_ok=True)

    # Determine paths for MCP call
    doc_url = prd_source.get("url", "")
    cwd = os.path.dirname(project_dir)  # scope-tracker/ root
    prompts_dir = os.path.join(cwd, "prompts")

    # Step 1: Fetch metadata to get modifiedTime
    meta_output_path = os.path.join(system_dir, f"{project_name}_prd_meta.json")
    print(f"Fetching PRD metadata for '{project_name}'...", file=sys.stderr)

    try:
        call_llm(
            prompt_file=os.path.join(prompts_dir, "prd_fetch_meta.md"),
            placeholders={
                "DOC_URL": doc_url,
                "SOURCE_TYPE": source_type,
                "OUTPUT_PATH": meta_output_path,
            },
            cwd=cwd,
            expected_output_files=[meta_output_path],
        )
    except RuntimeError as e:
        print(f"Error fetching PRD metadata: {e}", file=sys.stderr)
        sys.exit(1)

    # Read the metadata output
    try:
        with open(meta_output_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading PRD metadata output: {e}", file=sys.stderr)
        sys.exit(1)

    new_modified = meta.get("modified_time", "")

    # Step 2: Compare to stored modifiedTime
    run_state = _load_run_state(project_dir, project_name)
    stored_modified = run_state.get("prd", {}).get("last_modified", "")

    if not force and new_modified and new_modified == stored_modified:
        print("PRD unchanged — skipping.", file=sys.stderr)
        return {"status": "skipped (unchanged)", "last_modified": stored_modified}

    # Step 3: PRD changed — fetch full content
    print(f"PRD changed (was: {stored_modified}, now: {new_modified}). Fetching content...", file=sys.stderr)

    raw_path = os.path.join(system_dir, f"{project_name}_prd_raw.txt")
    comments_path = os.path.join(system_dir, f"{project_name}_prd_comments_raw.json")

    try:
        call_llm(
            prompt_file=os.path.join(prompts_dir, "prd_fetch_content.md"),
            placeholders={
                "DOC_URL": doc_url,
                "SOURCE_TYPE": source_type,
                "CONTENT_OUTPUT_PATH": raw_path,
                "COMMENTS_OUTPUT_PATH": comments_path,
            },
            cwd=cwd,
            expected_output_files=[raw_path, comments_path],
        )
    except RuntimeError as e:
        print(f"Error fetching PRD content: {e}", file=sys.stderr)
        sys.exit(1)

    return {
        "status": "changed",
        "last_modified": new_modified,
        "raw_path": raw_path,
        "comments_path": comments_path,
    }


def main() -> None:
    """CLI entry point for diff_prd.py."""
    parser = argparse.ArgumentParser(description="Check if PRD has changed.")
    parser.add_argument("--project-dir", required=True, help="Path to the project directory.")
    parser.add_argument("--config", required=True, help="Path to scope_tracker_config.json.")
    parser.add_argument("--project", required=True, help="Project name.")
    parser.add_argument("--force", action="store_true", help="Force fetch even if mtime unchanged.")
    args = parser.parse_args()

    result = run(args.project_dir, args.config, args.project, force=args.force)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
