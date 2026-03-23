"""Main pipeline orchestrator for scope-tracker.

Runs all pipeline steps in order for a single project:
  Step 0:  conflict_manager.py — resolve pending conflicts
  Step 1a: diff_prd.py         — check PRD modifiedTime (parallel with 1b)
  Step 1b: diff_slack.py       — check Slack watermark   (parallel with 1a)
  Step 2a: claude -p prd_extract.md     — only if PRD changed
  Step 2b: claude -p slack_classify.md  — only if Slack changed
  Step 3:  sheet_manager.py --operation update
  Step 4:  update_state.py     — persist run state
  Step 5:  claude -p slack_report.md    — post Slack report

All stdout output is JSON. Human-readable logs go to stderr.

Args:
    --project-dir: Path to the project directory
    --config: Path to scope_tracker_config.json
    --project: Project name
    --dry-run: Skip sheet writes and Slack post
    --verbose: Print each step as it starts/completes
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

from scope_tracker.scripts.call_llm import call_llm
from scope_tracker.scripts import conflict_manager
from scope_tracker.scripts import diff_prd
from scope_tracker.scripts import diff_slack
from scope_tracker.scripts import sheet_manager
from scope_tracker.scripts import update_state


# IST timezone
IST = timezone(timedelta(hours=5, minutes=30))


def _log(msg: str, verbose: bool = True) -> None:
    """Log a message to stderr if verbose mode is enabled.

    Args:
        msg: Message to log.
        verbose: Whether to output the message.
    """
    if verbose:
        print(msg, file=sys.stderr)


def _write_steps_executed(system_dir: str, project_name: str, steps_data: dict) -> None:
    """Write steps_executed.json after each step.

    Args:
        system_dir: Path to the system directory.
        project_name: Project name.
        steps_data: Steps execution data dict.
    """
    path = os.path.join(system_dir, f"{project_name}_steps_executed.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(steps_data, f, indent=2)
    except OSError as e:
        print(f"Warning: could not write steps_executed.json: {e}", file=sys.stderr)


def run(
    project_dir: str,
    config_path: str,
    project_name: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """Execute the full pipeline for a single project.

    Args:
        project_dir: Path to the project directory.
        config_path: Path to scope_tracker_config.json.
        project_name: Name of the project.
        dry_run: If True, skip sheet writes and Slack post.
        verbose: If True, print step-by-step progress.

    Returns:
        Result dict with pipeline summary.
    """
    project_dir = os.path.expanduser(os.path.abspath(project_dir))
    config_path = os.path.expanduser(os.path.abspath(config_path))
    system_dir = os.path.join(project_dir, "system")
    os.makedirs(system_dir, exist_ok=True)

    base_dir = os.path.dirname(project_dir)
    prompts_dir = os.path.join(base_dir, "prompts")

    # Load config
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        _log(f"Error loading config: {e}", True)
        return {"status": "error", "message": str(e)}

    sheet_config = config.get("sheet_config", {})

    steps_executed = 0
    steps_data = {
        "project": project_name,
        "started_at": datetime.now(IST).isoformat(),
        "steps": [],
        "steps_executed": 0,
    }

    run_summary = {
        "prd_status": "skipped",
        "slack_status": "skipped",
        "prd_feature_count": 0,
        "slack_new_messages": 0,
        "slack_decisions_found": 0,
        "rows_added": 0,
        "rows_updated": 0,
        "conflicts_detected": 0,
    }

    # ── Step 0: Conflict Manager ──────────────────────────────────
    _log("Step 0: Checking for conflict resolutions...", verbose)
    step_start = time.time()

    try:
        conflict_result = conflict_manager.run(project_dir, config_path, project_name)
    except SystemExit:
        conflict_result = {"status": "error"}
    except Exception as e:
        _log(f"Step 0 error: {e}", verbose)
        conflict_result = {"status": "error", "message": str(e)}

    steps_executed += 1
    step_duration = time.time() - step_start
    steps_data["steps"].append({
        "step": "0",
        "name": "conflict_manager",
        "status": conflict_result.get("status", "error"),
        "duration_s": round(step_duration, 2),
    })
    steps_data["steps_executed"] = steps_executed
    _write_steps_executed(system_dir, project_name, steps_data)
    _log(f"Step 0 complete: {conflict_result.get('status')} ({step_duration:.1f}s)", verbose)

    # ── Step 1a + 1b: Diff checks (parallel) ─────────────────────
    _log("Step 1a+1b: Checking PRD and Slack for changes (parallel)...", verbose)
    step_start = time.time()

    prd_result = {"status": "skipped"}
    slack_result = {"status": "skipped"}

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_prd = executor.submit(diff_prd.run, project_dir, config_path, project_name)
        future_slack = executor.submit(diff_slack.run, project_dir, config_path, project_name)

        for future in as_completed([future_prd, future_slack]):
            try:
                result = future.result()
                if future == future_prd:
                    prd_result = result
                else:
                    slack_result = result
            except SystemExit:
                pass
            except Exception as e:
                _log(f"Step 1 error: {e}", verbose)

    steps_executed += 1  # Count as one step (1a+1b parallel)
    step_duration = time.time() - step_start
    steps_data["steps"].append({
        "step": "1a",
        "name": "diff_prd",
        "status": prd_result.get("status", "error"),
        "duration_s": round(step_duration, 2),
    })
    steps_data["steps"].append({
        "step": "1b",
        "name": "diff_slack",
        "status": slack_result.get("status", "error"),
        "duration_s": round(step_duration, 2),
    })
    steps_data["steps_executed"] = steps_executed
    _write_steps_executed(system_dir, project_name, steps_data)
    _log(f"Step 1a: PRD → {prd_result.get('status')}", verbose)
    _log(f"Step 1b: Slack → {slack_result.get('status')}", verbose)

    prd_changed = prd_result.get("status") == "changed"
    slack_changed = slack_result.get("status") == "changed"

    run_summary["prd_status"] = "updated" if prd_changed else "unchanged"
    run_summary["slack_new_messages"] = slack_result.get("new_message_count", 0)

    # ── Step 2: LLM Extraction (2a: PRD, 2b: Slack) ────────────────
    _log("Step 2: LLM extraction...", verbose)
    step_start = time.time()

    prd_features_path = None
    if prd_changed:
        _log("Step 2a: PRD extraction (pure Python)...", verbose)
        raw_path = prd_result.get("raw_path", "")
        comments_path = prd_result.get("comments_path", "")
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
        prd_features_path = os.path.join(
            system_dir, f"{project_name}_prd_features_{date_str}.json"
        )

        identifier_col_names = sheet_config.get(
            "prd_identifier_column_names", ["ID", "Identifier", "#", "Ref"]
        )
        story_col_names = sheet_config.get(
            "prd_story_column_names", ["User Story", "Story", "Feature", "Requirement", "Description"]
        )

        try:
            from scope_tracker.scripts.prd_parser import extract_features

            # Read raw PRD text
            with open(raw_path, "r", encoding="utf-8") as f:
                raw_text = f.read()

            # Read comments (may not exist)
            comments: list = []
            try:
                with open(comments_path, "r", encoding="utf-8") as f:
                    comments = json.load(f)
            except (FileNotFoundError, json.JSONDecodeError):
                pass

            features = extract_features(raw_text, comments, identifier_col_names, story_col_names)

            # Write features JSON
            with open(prd_features_path, "w", encoding="utf-8") as f:
                json.dump(features, f, indent=2)

            run_summary["prd_feature_count"] = len(features)
        except Exception as e:
            _log(f"Step 2a error: {e}", verbose)
            prd_features_path = None
    else:
        _log("Step 2a: Skipped (PRD unchanged).", verbose)

    slack_items_path = None
    if slack_changed:
        _log("Step 2b: Slack classification...", verbose)
        raw_slack_path = slack_result.get("raw_path", "")
        date_str = datetime.now(IST).strftime("%Y-%m-%d")
        slack_items_path = os.path.join(
            system_dir, f"{project_name}_slack_items_{date_str}.json"
        )

        try:
            call_llm(
                prompt_file=os.path.join(prompts_dir, "slack_classify.md"),
                placeholders={
                    "RAW_SLACK_PATH": raw_slack_path,
                    "OUTPUT_PATH": slack_items_path,
                },
                cwd=base_dir,
            )
            # Count classified items
            try:
                with open(slack_items_path, "r", encoding="utf-8") as f:
                    items = json.load(f)
                run_summary["slack_decisions_found"] = len(items)
            except (FileNotFoundError, json.JSONDecodeError):
                pass
        except RuntimeError as e:
            _log(f"Step 2b error: {e}", verbose)
            slack_items_path = None
    else:
        _log("Step 2b: Skipped (no new Slack messages).", verbose)

    steps_executed += 1
    step_duration = time.time() - step_start
    steps_data["steps"].append({
        "step": "2a",
        "name": "prd_extract",
        "status": "executed" if prd_changed else "skipped",
        "duration_s": round(step_duration, 2),
    })
    steps_data["steps"].append({
        "step": "2b",
        "name": "slack_classify",
        "status": "executed" if slack_changed else "skipped",
        "duration_s": round(step_duration, 2),
    })
    steps_data["steps_executed"] = steps_executed
    _write_steps_executed(system_dir, project_name, steps_data)

    # ── Step 3: Sheet Update ──────────────────────────────────────
    _log("Step 3: Updating sheet...", verbose)
    step_start = time.time()

    sheet_result = {"status": "skipped", "rows_added": 0, "rows_updated": 0, "conflicts_detected": 0}
    if not dry_run:
        try:
            full_config, project_config = sheet_manager.load_config(config_path, project_name)
            sheet_result = sheet_manager.update_sheet(
                config=full_config,
                project_config=project_config,
                project_dir=project_dir,
                prd_features_path=prd_features_path,
                slack_items_path=slack_items_path,
            )
        except Exception as e:
            _log(f"Step 3 error: {e}", verbose)
            sheet_result = {"status": "error", "message": str(e), "rows_added": 0, "rows_updated": 0, "conflicts_detected": 0}
    else:
        _log("Step 3: Skipped (dry-run mode).", verbose)

    run_summary["rows_added"] = sheet_result.get("rows_added", 0)
    run_summary["rows_updated"] = sheet_result.get("rows_updated", 0)
    run_summary["conflicts_detected"] = sheet_result.get("conflicts_detected", 0)

    steps_executed += 1
    step_duration = time.time() - step_start
    steps_data["steps"].append({
        "step": "3",
        "name": "sheet_manager",
        "status": "dry-run" if dry_run else sheet_result.get("status", "error"),
        "duration_s": round(step_duration, 2),
    })
    steps_data["steps_executed"] = steps_executed
    _write_steps_executed(system_dir, project_name, steps_data)

    # ── Step 4: Update State ──────────────────────────────────────
    _log("Step 4: Updating run state...", verbose)
    step_start = time.time()

    # Build state updates
    state_updates: dict = {
        "run_count": _get_current_run_count(project_dir, project_name) + 1,
        "last_run_date": datetime.now(IST).strftime("%Y-%m-%d"),
    }

    if prd_changed:
        state_updates["prd"] = {
            "last_modified": prd_result.get("last_modified", ""),
            "last_read": datetime.now(IST).isoformat(),
            "feature_count": run_summary["prd_feature_count"],
        }

    if slack_changed:
        # Get the latest thread_ts from raw slack data
        raw_slack_path = slack_result.get("raw_path", "")
        latest_ts = _get_latest_slack_ts(raw_slack_path)
        seen_ids = _get_seen_thread_ids(raw_slack_path)
        state_updates["slack"] = {
            "last_run_timestamp": latest_ts,
            "seen_thread_ids": seen_ids,
        }

    if sheet_result.get("conflicts"):
        state_updates["conflicts"] = sheet_result["conflicts"]

    if sheet_result.get("rows_added", 0) > 0 or sheet_result.get("rows_updated", 0) > 0:
        run_state = _load_run_state(project_dir, project_name)
        current_last_row = run_state.get("sheet", {}).get("last_row_number", 0)
        state_updates["sheet"] = {
            "last_row_number": current_last_row + sheet_result.get("rows_added", 0),
            "last_updated": datetime.now(IST).isoformat(),
        }

    # Write updates to a temp file and call update_state
    updates_path = os.path.join(system_dir, f"{project_name}_pipeline_updates.json")
    try:
        with open(updates_path, "w", encoding="utf-8") as f:
            json.dump(state_updates, f, indent=2)
    except OSError as e:
        _log(f"Error writing updates file: {e}", verbose)

    try:
        update_state.run(project_dir, config_path, project_name, updates_path)
    except SystemExit:
        pass
    except Exception as e:
        _log(f"Step 4 error: {e}", verbose)

    steps_executed += 1
    step_duration = time.time() - step_start
    steps_data["steps"].append({
        "step": "4",
        "name": "update_state",
        "status": "executed",
        "duration_s": round(step_duration, 2),
    })
    steps_data["steps_executed"] = steps_executed
    _write_steps_executed(system_dir, project_name, steps_data)

    # ── Step 5: Slack Report ──────────────────────────────────────
    _log("Step 5: Posting Slack report...", verbose)
    step_start = time.time()

    if not dry_run:
        reporting_channel = config.get("global_settings", {}).get(
            "reporting_slack_channel", "scope-tracker"
        )
        run_datetime = datetime.now(IST).isoformat()

        # Get pending conflicts for report
        run_state = _load_run_state(project_dir, project_name)
        pending_conflicts = [
            c for c in run_state.get("conflicts", []) if not c.get("resolved", False)
        ]

        try:
            from scope_tracker.scripts.slack_reporter import build_report, post_report
            from scope_tracker.scripts.slack_client import load_slack_credentials

            report_text = build_report(
                project_name=project_name,
                run_datetime=run_datetime,
                steps_executed=steps_executed,
                run_summary=run_summary,
                pending_conflicts=pending_conflicts,
            )

            # Load Slack credentials — pass channel name directly to chat.postMessage
            # (no need for conversations.list to resolve channel ID)
            mcp_json_path = os.path.join(base_dir, ".mcp.json")
            slack_creds = load_slack_credentials(mcp_json_path)
            bot_token = slack_creds["bot_token"]
            # Ensure channel name has # prefix for public channels
            channel_ref = reporting_channel if reporting_channel.startswith("#") else f"#{reporting_channel}"

            post_report(bot_token, channel_ref, report_text)
        except RuntimeError as e:
            _log(f"Step 5 error: {e}", verbose)
    else:
        _log("Step 5: Skipped (dry-run mode).", verbose)
        _log(f"Dry-run summary: {json.dumps(run_summary, indent=2)}", verbose)

    steps_executed += 1
    step_duration = time.time() - step_start
    steps_data["steps"].append({
        "step": "5",
        "name": "slack_report",
        "status": "dry-run" if dry_run else "executed",
        "duration_s": round(step_duration, 2),
    })
    steps_data["steps_executed"] = steps_executed
    steps_data["completed_at"] = datetime.now(IST).isoformat()
    _write_steps_executed(system_dir, project_name, steps_data)

    _log(f"Pipeline complete. {steps_executed} steps executed.", verbose)

    return {
        "status": "completed",
        "steps_executed": steps_executed,
        "dry_run": dry_run,
        "summary": run_summary,
    }


def _get_current_run_count(project_dir: str, project_name: str) -> int:
    """Get the current run count from run_state.json.

    Args:
        project_dir: Path to the project directory.
        project_name: Project name.

    Returns:
        Current run count, or 0 if not found.
    """
    run_state = _load_run_state(project_dir, project_name)
    return run_state.get("run_count", 0)


def _load_run_state(project_dir: str, project_name: str) -> dict:
    """Load run_state.json for a project.

    Args:
        project_dir: Path to the project directory.
        project_name: Project name.

    Returns:
        Run state dict, or empty dict if not found.
    """
    state_path = os.path.join(project_dir, "system", f"{project_name}_run_state.json")
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _get_latest_slack_ts(raw_slack_path: str) -> str:
    """Extract the latest message timestamp from raw Slack data.

    Args:
        raw_slack_path: Path to the raw Slack JSON file.

    Returns:
        Latest timestamp string, or "0" if not found.
    """
    if not raw_slack_path:
        return "0"
    try:
        with open(raw_slack_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return "0"

    latest_ts = "0"
    for thread in data.get("threads", []):
        for msg in thread.get("messages", []):
            ts = msg.get("ts", "0")
            if ts > latest_ts:
                latest_ts = ts
    return latest_ts


def _get_seen_thread_ids(raw_slack_path: str) -> list[str]:
    """Extract all thread IDs from raw Slack data.

    Args:
        raw_slack_path: Path to the raw Slack JSON file.

    Returns:
        List of thread_ts strings.
    """
    if not raw_slack_path:
        return []
    try:
        with open(raw_slack_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    return [t["thread_ts"] for t in data.get("threads", []) if "thread_ts" in t]


def main() -> None:
    """CLI entry point for run_pipeline.py."""
    parser = argparse.ArgumentParser(description="Run the scope-tracker pipeline.")
    parser.add_argument("--project-dir", required=True, help="Path to the project directory.")
    parser.add_argument("--config", required=True, help="Path to scope_tracker_config.json.")
    parser.add_argument("--project", required=True, help="Project name.")
    parser.add_argument("--dry-run", action="store_true", help="Skip sheet writes and Slack post.")
    parser.add_argument("--verbose", action="store_true", help="Print step-by-step progress.")
    args = parser.parse_args()

    result = run(
        args.project_dir,
        args.config,
        args.project,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
