"""Check if the PRD source document has changed since the last run.

If changed, fetches full content and inline comments.
For Confluence sources: uses direct REST API calls via confluence_client.
For Google Drive sources: uses LLM calls via call_llm (MCP).
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
from scope_tracker.scripts.confluence_client import (
    get_page_id_from_url,
    fetch_page_metadata,
    fetch_page_content,
    fetch_page_comments,
    load_confluence_credentials,
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


def _run_confluence(
    project_dir: str, project_name: str, prd_source: dict, run_state: dict, force: bool
) -> dict:
    """Handle PRD diff for Confluence sources using direct REST API.

    Args:
        project_dir: Absolute path to the project directory.
        project_name: Name of the project.
        prd_source: PRD source config dict.
        run_state: Current run state dict.
        force: If True, skip mtime comparison.

    Returns:
        Result dict with status and optional paths.
    """
    system_dir = os.path.join(project_dir, "system")
    doc_url = prd_source.get("url", "")
    base_dir = os.path.dirname(project_dir)
    mcp_json_path = os.path.join(base_dir, ".mcp.json")

    # Load credentials
    try:
        creds = load_confluence_credentials(mcp_json_path)
    except RuntimeError as e:
        print(f"Error loading Confluence credentials: {e}", file=sys.stderr)
        sys.exit(1)

    # Extract page ID
    try:
        page_id = get_page_id_from_url(doc_url)
    except ValueError as e:
        print(f"Error parsing Confluence URL: {e}", file=sys.stderr)
        sys.exit(1)

    # Step 1: Fetch metadata
    print(f"Fetching Confluence metadata for '{project_name}'...", file=sys.stderr)
    try:
        meta = fetch_page_metadata(
            creds["site_name"], creds["email"], creds["api_token"], page_id
        )
    except RuntimeError as e:
        print(f"Error fetching Confluence metadata: {e}", file=sys.stderr)
        sys.exit(1)

    # Write metadata file
    meta_output_path = os.path.join(system_dir, f"{project_name}_prd_meta.json")
    with open(meta_output_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    new_modified = meta.get("modified_time", "")

    # Step 2: Compare to stored modifiedTime
    stored_modified = run_state.get("prd", {}).get("last_modified", "")
    if not force and new_modified and new_modified == stored_modified:
        print("PRD unchanged — skipping.", file=sys.stderr)
        return {"status": "skipped (unchanged)", "last_modified": stored_modified}

    # Step 3: Fetch full content
    print(
        f"PRD changed (was: {stored_modified}, now: {new_modified}). Fetching content...",
        file=sys.stderr,
    )

    raw_path = os.path.join(system_dir, f"{project_name}_prd_raw.txt")
    comments_path = os.path.join(system_dir, f"{project_name}_prd_comments_raw.json")

    try:
        content = fetch_page_content(
            creds["site_name"], creds["email"], creds["api_token"], page_id
        )
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(content)
    except RuntimeError as e:
        print(f"Error fetching Confluence content: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        comments = fetch_page_comments(
            creds["site_name"], creds["email"], creds["api_token"], page_id
        )
        with open(comments_path, "w", encoding="utf-8") as f:
            json.dump(comments, f, indent=2, ensure_ascii=False)
    except RuntimeError as e:
        print(f"Error fetching Confluence comments: {e}", file=sys.stderr)
        sys.exit(1)

    return {
        "status": "changed",
        "last_modified": new_modified,
        "raw_path": raw_path,
        "comments_path": comments_path,
    }


def _run_google_drive(
    project_dir: str, project_name: str, prd_source: dict, run_state: dict, force: bool
) -> dict:
    """Handle PRD diff for Google Drive sources using LLM calls (MCP).

    Args:
        project_dir: Absolute path to the project directory.
        project_name: Name of the project.
        prd_source: PRD source config dict.
        run_state: Current run state dict.
        force: If True, skip mtime comparison.

    Returns:
        Result dict with status and optional paths.
    """
    system_dir = os.path.join(project_dir, "system")
    doc_url = prd_source.get("url", "")
    source_type = prd_source.get("type", "google-drive")
    cwd = os.path.dirname(project_dir)
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
    stored_modified = run_state.get("prd", {}).get("last_modified", "")
    if not force and new_modified and new_modified == stored_modified:
        print("PRD unchanged — skipping.", file=sys.stderr)
        return {"status": "skipped (unchanged)", "last_modified": stored_modified}

    # Step 3: PRD changed — fetch full content
    print(
        f"PRD changed (was: {stored_modified}, now: {new_modified}). Fetching content...",
        file=sys.stderr,
    )

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


def run(project_dir: str, config_path: str, project_name: str, force: bool = False) -> dict:
    """Execute the PRD diff check.

    Routes to Confluence direct API or Google Drive LLM path based on source_type.

    Args:
        project_dir: Path to the project directory.
        config_path: Path to scope_tracker_config.json.
        project_name: Name of the project.
        force: If True, skip mtime comparison and always fetch.

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

    run_state = _load_run_state(project_dir, project_name)

    if source_type == "confluence":
        return _run_confluence(project_dir, project_name, prd_source, run_state, force)
    else:
        # Google Drive and any other types use LLM path
        return _run_google_drive(project_dir, project_name, prd_source, run_state, force)


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
