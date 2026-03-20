"""Google Sheet manager for scope-tracker.

Creates and updates the UAT tracking Google Sheet. Handles all sheet operations:
creating sheets, writing rows, applying formatting, dropdowns, conditional formatting,
computing Effective Status, and detecting conflicts.

All stdout output is JSON. Human-readable logs go to stderr.

Usage:
    python sheet_manager.py --project-dir PATH --config PATH --project NAME --operation create|update
"""

import json
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from scope_tracker.scripts.call_llm import call_llm
from scope_tracker.scripts.google_sheets import (
    authenticate,
    create_spreadsheet as gs_create_spreadsheet,
    read_spreadsheet as gs_read_spreadsheet,
    update_spreadsheet as gs_update_spreadsheet,
)


# IST timezone offset
IST = timezone(timedelta(hours=5, minutes=30))

# Band color definitions (hex without #, as used by Sheets API)
BAND_IDENTITY_COLOR = {"red": 0.91, "green": 0.94, "blue": 1.0}  # #E8F0FE
BAND_SOURCE_COLOR = {"red": 0.90, "green": 0.96, "blue": 0.92}  # #E6F4EA
BAND_SCOPE_COLOR = {"red": 0.93, "green": 0.91, "blue": 0.96}  # #EDE7F6
BAND_UAT_COLOR = {"red": 1.0, "green": 0.97, "blue": 0.88}  # #FFF8E1
EFFECTIVE_STATUS_BG = {"red": 1.0, "green": 0.88, "blue": 0.51}  # #FFE082

# Conditional formatting colors
COND_PASSED = {"red": 0.78, "green": 0.90, "blue": 0.79}  # #C8E6C9
COND_FAILED = {"red": 1.0, "green": 0.80, "blue": 0.82}  # #FFCDD2
COND_BLOCKED = {"red": 1.0, "green": 0.88, "blue": 0.70}  # #FFE0B2
COND_PASSED_ITER = {"red": 0.94, "green": 0.96, "blue": 0.76}  # #F0F4C3

# Border colors
THIN_BORDER_COLOR = {"red": 0.88, "green": 0.88, "blue": 0.88}  # #E0E0E0
BAND_SEPARATOR_COLOR = {"red": 0.74, "green": 0.74, "blue": 0.74}  # #BDBDBD


def _log(msg: str) -> None:
    """Log a message to stderr."""
    print(msg, file=sys.stderr)


def load_config(config_path: str, project_name: str) -> tuple[dict, dict]:
    """Load config and return (full_config, project_config).

    Args:
        config_path: Path to scope_tracker_config.json.
        project_name: Name of the project.

    Returns:
        Tuple of (full config dict, project config dict).

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValueError: If project not found in config.
    """
    config_path = os.path.expanduser(os.path.abspath(config_path))
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_path}")

    for proj in config.get("projects", []):
        if proj["name"] == project_name:
            return config, proj

    raise ValueError(f"Project '{project_name}' not found in config")


def load_run_state(project_dir: str, project_name: str) -> dict:
    """Load run_state.json for a project.

    Args:
        project_dir: Path to the project directory.
        project_name: Name of the project.

    Returns:
        Run state dict, or empty dict if file doesn't exist.
    """
    state_path = os.path.expanduser(
        os.path.abspath(
            os.path.join(project_dir, "system", f"{project_name}_run_state.json")
        )
    )
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def build_headers(config: dict) -> list[str]:
    """Build the ordered list of column headers per Section 5.2.

    Args:
        config: Full config dict (needs sheet_config.uat_rounds).

    Returns:
        Ordered list of column header strings.
    """
    sheet_config = config.get("sheet_config", {})
    uat_rounds = sheet_config.get("uat_rounds", 5)

    headers = [
        # Band 1 — Identity
        "#",
        "Feature Name",
        "Description",
        # Band 2 — Source
        "Source",
        "Source ID",
        "Source Text",
        "PRD Section",
        "PRD Comments",
        # Band 3 — Scope
        "Scope Decision",
        "Target Version",
        "Conflict Resolution",
        "Added Run",
        "Last Updated",
    ]

    # Band 4 — UAT
    for i in range(1, uat_rounds + 1):
        headers.append(f"UAT #{i} Status")
        headers.append(f"UAT #{i} Notes")

    headers.extend([
        "Effective Status",
        "Blocker?",
        "Tester",
        "Test Date",
    ])

    return headers


def get_column_widths(config: dict) -> dict[str, int]:
    """Get column width mappings per Section 5.3.

    Args:
        config: Full config dict.

    Returns:
        Dict mapping column name to width in pixels.
    """
    sheet_config = config.get("sheet_config", {})
    uat_rounds = sheet_config.get("uat_rounds", 5)

    widths = {
        "#": 40,
        "Feature Name": 300,
        "Description": 400,
        "Source": 80,
        "Source ID": 100,
        "Source Text": 300,
        "PRD Section": 90,
        "PRD Comments": 300,
        "Scope Decision": 160,
        "Target Version": 130,
        "Conflict Resolution": 250,
        "Added Run": 90,
        "Last Updated": 160,
        "Effective Status": 150,
        "Blocker?": 80,
        "Tester": 120,
        "Test Date": 110,
    }

    for i in range(1, uat_rounds + 1):
        widths[f"UAT #{i} Status"] = 140
        widths[f"UAT #{i} Notes"] = 200

    return widths


def get_wrap_columns() -> set[str]:
    """Get the set of columns that should have text wrapping enabled.

    Returns:
        Set of column names that use text wrapping.
    """
    return {"Description", "Source Text", "PRD Comments"}
    # Note: UAT Notes columns also wrap, handled dynamically


def _is_wrap_column(col_name: str) -> bool:
    """Check if a column should have text wrapping.

    Args:
        col_name: Column header name.

    Returns:
        True if the column should wrap text.
    """
    base_wraps = {"Description", "Source Text", "PRD Comments"}
    if col_name in base_wraps:
        return True
    if "Notes" in col_name:
        return True
    return False


def _get_band_color(col_index: int, headers: list[str]) -> dict:
    """Get the band background color for a column index.

    Args:
        col_index: Zero-based column index.
        headers: List of all column headers.

    Returns:
        Color dict for the Sheets API.
    """
    # Band 1: columns 0-2 (Identity)
    if col_index <= 2:
        return BAND_IDENTITY_COLOR
    # Band 2: columns 3-7 (Source)
    if col_index <= 7:
        return BAND_SOURCE_COLOR
    # Band 3: columns 8-12 (Scope)
    if col_index <= 12:
        return BAND_SCOPE_COLOR

    col_name = headers[col_index] if col_index < len(headers) else ""

    # Effective Status has its own color
    if col_name == "Effective Status":
        return EFFECTIVE_STATUS_BG

    # Band 4: UAT columns and trailing columns
    return BAND_UAT_COLOR


def _get_band_separator_indices(headers: list[str]) -> list[int]:
    """Get column indices where band separators should appear.

    Band separators go after column #3, #8, #13, and last UAT column.

    Args:
        headers: List of all column headers.

    Returns:
        List of zero-based column indices for separator right borders.
    """
    separators = [2, 7, 12]  # After Identity, Source, Scope bands

    # Find last UAT column (before Effective Status)
    for i, h in enumerate(headers):
        if h == "Effective Status":
            separators.append(i - 1)
            break

    return separators


def _get_google_creds(config: dict, base_dir: str) -> Any:
    """Get Google OAuth2 credentials from config.

    Reads client_secret_path from config and authenticates via OAuth2.
    Token is stored in the scope-tracker directory.

    Args:
        config: Full config dict (must have google_sheets.client_secret_path).
        base_dir: Base scope-tracker directory (token.json stored here).

    Returns:
        Authenticated Google OAuth2 Credentials object.

    Raises:
        FileNotFoundError: If client_secret_path is not set or file missing.
    """
    gs_config = config.get("google_sheets", {})
    client_secret_path = gs_config.get("client_secret_path", "")

    if not client_secret_path:
        raise FileNotFoundError(
            "Google Sheets client_secret_path not configured. "
            "Run 'scope-tracker init' to set it up."
        )

    client_secret_path = os.path.expanduser(os.path.abspath(client_secret_path))
    return authenticate(client_secret_path, base_dir)


def _extract_spreadsheet_id(sheet_url: str) -> str:
    """Extract spreadsheet ID from a Google Sheets URL.

    Args:
        sheet_url: Full Google Sheets URL.

    Returns:
        The spreadsheet ID string.
    """
    # URL format: https://docs.google.com/spreadsheets/d/{id}/...
    if "/d/" in sheet_url:
        parts = sheet_url.split("/d/")[1].split("/")
        return parts[0]
    return sheet_url  # assume it's already an ID


def create_sheet(
    config: dict,
    project_config: dict,
    project_dir: str,
    prd_features_path: str,
) -> dict:
    """Create a new Google Sheet with all PRD features and full formatting.

    This implements the full 'create' operation end-to-end:
    create sheet → build headers → write all PRD feature rows →
    apply formatting → apply dropdowns → apply conditional formatting →
    compute effective status.

    Args:
        config: Full config dict.
        project_config: Project-specific config dict.
        project_dir: Path to the project directory.
        prd_features_path: Path to the PRD features JSON file.

    Returns:
        Result dict with status, sheet_url, and row count.
    """
    project_name = project_config["name"]
    base_dir = os.path.dirname(project_dir)
    headers = build_headers(config)

    # Load PRD features
    prd_features_path = os.path.expanduser(os.path.abspath(prd_features_path))
    try:
        with open(prd_features_path, "r", encoding="utf-8") as f:
            prd_features = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"PRD features file not found: {prd_features_path}")

    # Build sheet data: header row + data rows
    sheet_data = [headers]
    run_count = load_run_state(project_dir, project_name).get("run_count", 1)
    timestamp = datetime.now(IST).isoformat()

    for idx, item in enumerate(prd_features, start=1):
        row = _build_row_from_item(
            item=item,
            row_number=idx,
            run_count=run_count,
            timestamp=timestamp,
            headers=headers,
            source="PRD",
        )
        sheet_data.append(row)

    # Compute effective status for all rows
    uat_rounds = config.get("sheet_config", {}).get("uat_rounds", 5)
    for row_idx in range(1, len(sheet_data)):
        row_dict = dict(zip(headers, sheet_data[row_idx]))
        eff_status = compute_effective_status(row_dict, uat_rounds)
        eff_col = headers.index("Effective Status")
        sheet_data[row_idx][eff_col] = eff_status

    # Create sheet via Google Sheets API directly
    creds = _get_google_creds(config, base_dir)

    formatting_spec = _build_formatting_spec(headers, config)
    dropdown_spec = _build_dropdown_spec(headers, config)
    cond_format_spec = _build_conditional_formatting_spec(headers)
    column_widths = get_column_widths(config)

    _log(f"Creating Google Sheet for project: {project_name}")
    result = gs_create_spreadsheet(
        creds=creds,
        title=f"Scope Tracker — {project_name}",
        headers=headers,
        rows=sheet_data[1:],  # exclude header row from data
        column_widths=column_widths,
        formatting=formatting_spec,
        dropdowns=dropdown_spec,
        conditional_formatting=cond_format_spec,
    )

    sheet_url = result.get("sheet_url", "")
    _log(f"Sheet created: {sheet_url}")

    return {
        "status": "created",
        "sheet_url": sheet_url,
        "spreadsheet_id": result.get("spreadsheet_id", ""),
        "rows_added": len(prd_features),
        "total_columns": len(headers),
    }


def update_sheet(
    config: dict,
    project_config: dict,
    project_dir: str,
    prd_features_path: Optional[str] = None,
    slack_items_path: Optional[str] = None,
) -> dict:
    """Update an existing Google Sheet with new/changed items.

    This implements the full 'update' operation end-to-end:
    read sheet → process PRD items → process Slack items →
    detect conflicts → compute effective status → batch write → apply formatting.

    Args:
        config: Full config dict.
        project_config: Project-specific config dict.
        project_dir: Path to the project directory.
        prd_features_path: Path to PRD features JSON (None if PRD unchanged).
        slack_items_path: Path to Slack items JSON (None if no new Slack).

    Returns:
        Result dict with status, rows_added, rows_updated, conflicts_detected.
    """
    project_name = project_config["name"]
    base_dir = os.path.dirname(project_dir)
    headers = build_headers(config)
    uat_rounds = config.get("sheet_config", {}).get("uat_rounds", 5)
    run_state = load_run_state(project_dir, project_name)
    run_count = run_state.get("run_count", 1)
    timestamp = datetime.now(IST).isoformat()

    # Read current sheet data
    sheet_url = project_config.get("sheet_url", "")
    sheet_rows = read_sheet(config, base_dir, sheet_url, headers)

    rows_added = 0
    rows_updated = 0
    new_conflicts: list[dict] = []
    changes: list[dict] = []

    # Build source_id index for fast lookup
    source_id_index: dict[str, int] = {}
    for i, row in enumerate(sheet_rows):
        sid = row.get("Source ID", "")
        if sid:
            source_id_index[sid] = i

    # Process PRD items
    if prd_features_path:
        prd_path = os.path.expanduser(os.path.abspath(prd_features_path))
        try:
            with open(prd_path, "r", encoding="utf-8") as f:
                prd_features = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            prd_features = []

        next_row_number = len(sheet_rows) + 1

        for item in prd_features:
            source_id = item.get("source_id", "")
            if source_id in source_id_index:
                row_idx = source_id_index[source_id]
                existing_row = sheet_rows[row_idx]
                row_changes = _diff_prd_item(item, existing_row, timestamp)
                if row_changes:
                    changes.append({
                        "type": "update",
                        "row_index": row_idx + 2,  # 1-indexed, +1 for header
                        "changes": row_changes,
                    })
                    rows_updated += 1

                    # Check for conflict
                    conflict = _check_conflict_for_item(
                        item, existing_row, "PRD", run_state
                    )
                    if conflict:
                        new_conflicts.append(conflict)
            else:
                new_row = _build_row_from_item(
                    item=item,
                    row_number=next_row_number,
                    run_count=run_count,
                    timestamp=timestamp,
                    headers=headers,
                    source="PRD",
                )
                changes.append({
                    "type": "add",
                    "row_data": new_row,
                    "row_number": next_row_number,
                })
                # Add to index for Slack matching
                source_id_index[source_id] = next_row_number - 1
                row_dict = dict(zip(headers, new_row))
                sheet_rows.append(row_dict)
                next_row_number += 1
                rows_added += 1

    # Process Slack items
    if slack_items_path:
        slack_path = os.path.expanduser(os.path.abspath(slack_items_path))
        try:
            with open(slack_path, "r", encoding="utf-8") as f:
                slack_items = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            slack_items = []

        next_row_number = len(sheet_rows) + 1

        for item in slack_items:
            source_id = item.get("source_id", "")
            if source_id in source_id_index:
                row_idx = source_id_index[source_id]
                existing_row = sheet_rows[row_idx]
                row_changes = _diff_slack_item(item, existing_row, timestamp)
                if row_changes:
                    changes.append({
                        "type": "update",
                        "row_index": row_idx + 2,
                        "changes": row_changes,
                    })
                    rows_updated += 1

                    conflict = _check_conflict_for_item(
                        item, existing_row, "Slack", run_state
                    )
                    if conflict:
                        new_conflicts.append(conflict)
            else:
                # Try semantic match via LLM (semantic task — LLM required)
                prompts_dir = os.path.join(base_dir, "prompts")
                match_result = _try_semantic_match(
                    item, sheet_rows, base_dir, prompts_dir, project_dir, project_config["name"]
                )
                if match_result and match_result.get("match_found"):
                    matched_idx = match_result["matched_row_number"] - 1  # to 0-based
                    existing_row = sheet_rows[matched_idx]
                    row_changes = _diff_slack_item(item, existing_row, timestamp)
                    # Also update Source and Source ID to include Slack
                    if existing_row.get("Source", "") == "PRD":
                        row_changes["Source"] = "PRD, Slack"
                    if not existing_row.get("Source ID", "").endswith(source_id):
                        current_sid = existing_row.get("Source ID", "")
                        row_changes["Source ID"] = f"{current_sid}, {source_id}" if current_sid else source_id

                    if row_changes:
                        changes.append({
                            "type": "update",
                            "row_index": matched_idx + 2,
                            "changes": row_changes,
                        })
                        rows_updated += 1

                        conflict = _check_conflict_for_item(
                            item, existing_row, "Slack", run_state
                        )
                        if conflict:
                            new_conflicts.append(conflict)
                else:
                    # No match — add as new row
                    new_row = _build_row_from_item(
                        item=item,
                        row_number=next_row_number,
                        run_count=run_count,
                        timestamp=timestamp,
                        headers=headers,
                        source="Slack",
                    )
                    changes.append({
                        "type": "add",
                        "row_data": new_row,
                        "row_number": next_row_number,
                    })
                    source_id_index[source_id] = next_row_number - 1
                    row_dict = dict(zip(headers, new_row))
                    sheet_rows.append(row_dict)
                    next_row_number += 1
                    rows_added += 1

    # Compute effective status for ALL rows
    for i, row in enumerate(sheet_rows):
        eff_status = compute_effective_status(row, uat_rounds)
        changes.append({
            "type": "update_cell",
            "row_index": i + 2,  # 1-indexed + header
            "column": "Effective Status",
            "value": eff_status,
        })

    # Apply changes via Google Sheets API directly
    if changes and sheet_url:
        spreadsheet_id = _extract_spreadsheet_id(sheet_url)
        creds = _get_google_creds(config, base_dir)

        formatting_spec = _build_formatting_spec(headers, config)
        dropdown_spec = _build_dropdown_spec(headers, config)
        cond_format_spec = _build_conditional_formatting_spec(headers)

        _log(f"Applying {len(changes)} changes to sheet")
        try:
            gs_update_spreadsheet(
                creds=creds,
                spreadsheet_id=spreadsheet_id,
                changes=changes,
                headers=headers,
                formatting=formatting_spec,
                dropdowns=dropdown_spec,
                conditional_formatting=cond_format_spec,
            )
        except Exception as e:
            _log(f"Warning: Sheet update failed: {e}")

    return {
        "status": "updated",
        "rows_added": rows_added,
        "rows_updated": rows_updated,
        "conflicts_detected": len(new_conflicts),
        "conflicts": new_conflicts,
    }


def read_sheet(
    config: dict,
    base_dir: str,
    sheet_url: str,
    headers: list[str],
) -> list[dict]:
    """Read all rows from the Google Sheet into a list of dicts.

    Args:
        config: Full config dict (needs google_sheets credentials).
        base_dir: Base scope-tracker directory.
        sheet_url: URL of the Google Sheet.
        headers: Expected column headers.

    Returns:
        List of dicts, each keyed by column header name.
    """
    if not sheet_url:
        _log("Warning: No sheet URL configured")
        return []

    spreadsheet_id = _extract_spreadsheet_id(sheet_url)
    creds = _get_google_creds(config, base_dir)

    _log(f"Reading sheet: {spreadsheet_id}")
    try:
        data = gs_read_spreadsheet(creds=creds, spreadsheet_id=spreadsheet_id)
    except Exception as e:
        _log(f"Warning: Could not read sheet: {e}")
        return []

    raw_rows = data.get("rows", [])
    if not raw_rows:
        return []

    # First row is headers from the sheet — skip it, use our expected headers
    data_rows = raw_rows[1:] if len(raw_rows) > 1 else []

    rows = []
    for raw_row in data_rows:
        if isinstance(raw_row, list):
            row_dict = {}
            for i, val in enumerate(raw_row):
                if i < len(headers):
                    row_dict[headers[i]] = str(val) if val is not None else ""
            # Pad missing columns with empty strings
            for i in range(len(raw_row), len(headers)):
                row_dict[headers[i]] = ""
            rows.append(row_dict)

    return rows


def compute_effective_status(row: dict, uat_rounds: int) -> str:
    """Compute the Effective Status for a row.

    Iterates UAT rounds from highest to lowest. Returns the first non-empty,
    non-"To be tested" value found. If all empty or all "To be tested",
    returns "To be tested".

    Args:
        row: Dict of column_name -> value for a single row.
        uat_rounds: Number of UAT rounds configured.

    Returns:
        The computed effective status string.
    """
    for i in range(uat_rounds, 0, -1):
        key = f"UAT #{i} Status"
        value = row.get(key, "")
        if value and value != "To be tested":
            return value
    return "To be tested"


def detect_conflicts(
    new_items: list[dict],
    sheet_rows: list[dict],
    source_type: str,
    run_state: dict,
) -> list[dict]:
    """Detect conflicts between new items and existing sheet rows.

    A conflict exists when a PRD/Slack item's scope decision differs from
    the matching sheet row's Scope Decision, and the Conflict Resolution
    column is empty (or the source has changed since resolution).

    Args:
        new_items: List of new PRD or Slack item dicts.
        sheet_rows: List of current sheet row dicts.
        source_type: "PRD" or "Slack".
        run_state: Current run state dict.

    Returns:
        List of conflict dicts to add to the conflict queue.
    """
    conflicts = []

    # Build source_id index
    source_id_index: dict[str, int] = {}
    for i, row in enumerate(sheet_rows):
        sid = row.get("Source ID", "")
        if sid:
            source_id_index[sid] = i

    for item in new_items:
        source_id = item.get("source_id", "")
        if source_id not in source_id_index:
            continue

        row = sheet_rows[source_id_index[source_id]]
        conflict = _check_conflict_for_item(item, row, source_type, run_state)
        if conflict:
            conflicts.append(conflict)

    return conflicts


def _check_conflict_for_item(
    item: dict, row: dict, source_type: str, run_state: dict
) -> Optional[dict]:
    """Check if a single item conflicts with its sheet row.

    Args:
        item: The PRD or Slack item dict.
        row: The existing sheet row dict.
        source_type: "PRD" or "Slack".
        run_state: Current run state dict.

    Returns:
        Conflict dict if conflict found, None otherwise.
    """
    item_decision = item.get("latest_comment_decision") or item.get("scope_decision", "")
    sheet_decision = row.get("Scope Decision", "")

    if not item_decision or not sheet_decision:
        return None

    if item_decision == sheet_decision:
        return None

    # Check for conflict suppression
    resolution = row.get("Conflict Resolution", "")
    if resolution:
        # Conflict was previously resolved — only re-raise if source changed
        # since resolution. For simplicity, we check if the source text changed.
        source_text = row.get("Source Text", "")
        new_text = item.get("source_text", "")
        if source_text == new_text:
            return None  # Suppressed

    source_id = item.get("source_id", "")
    feature_name = item.get("feature_name", "") or item.get("user_story", "") or row.get("User Story / Feature", "")
    return {
        "id": source_id,
        "source_id": source_id,
        "feature_name": feature_name,
        "source_a": source_type,
        "value_a": item_decision,
        "source_b": "Sheet",
        "value_b": sheet_decision,
        "raised_at": datetime.now(IST).isoformat(),
        "slack_message_ts": None,
        "resolved": False,
    }


def _build_row_from_item(
    item: dict,
    row_number: int,
    run_count: int,
    timestamp: str,
    headers: list[str],
    source: str,
) -> list[str]:
    """Build a sheet row list from a PRD or Slack item.

    Args:
        item: Item dict (PRD feature or Slack item).
        row_number: The row number (# column value).
        run_count: Current run count (Added Run value).
        timestamp: ISO timestamp for Last Updated.
        headers: Full list of column headers.
        source: "PRD" or "Slack".

    Returns:
        List of cell values in header order.
    """
    row_dict: dict[str, str] = {h: "" for h in headers}

    row_dict["#"] = str(row_number)
    row_dict["Feature Name"] = item.get("feature_name", "")[:80]
    row_dict["Description"] = item.get("description", "")
    row_dict["Source"] = source
    row_dict["Source ID"] = item.get("source_id", "")
    row_dict["Source Text"] = item.get("source_text", "")
    row_dict["Added Run"] = str(run_count)
    row_dict["Last Updated"] = timestamp

    if source == "PRD":
        row_dict["PRD Section"] = item.get("identifier", "")
        row_dict["PRD Comments"] = item.get("prd_comments", "")
        decision = item.get("latest_comment_decision", "")
        if decision:
            row_dict["Scope Decision"] = decision
        else:
            row_dict["Scope Decision"] = "In Scope"
    elif source == "Slack":
        row_dict["Scope Decision"] = item.get("scope_decision", "In Scope")
        row_dict["Target Version"] = item.get("target_version", "")

    return [row_dict.get(h, "") for h in headers]


def _diff_prd_item(item: dict, existing_row: dict, timestamp: str) -> dict[str, str]:
    """Compute changes between a PRD item and existing sheet row.

    Only returns tool-owned columns that changed. Never touches user-owned columns.

    Args:
        item: PRD feature item dict.
        existing_row: Existing sheet row dict.
        timestamp: ISO timestamp for Last Updated.

    Returns:
        Dict of column_name -> new_value for changed columns. Empty if no changes.
    """
    changes: dict[str, str] = {}

    # Check description change
    new_desc = item.get("description", "")
    if new_desc and new_desc != existing_row.get("Description", ""):
        changes["Description"] = new_desc

    # Check source text change
    new_text = item.get("source_text", "")
    if new_text and new_text != existing_row.get("Source Text", ""):
        changes["Source Text"] = new_text

    # Check PRD comments change
    new_comments = item.get("prd_comments", "")
    if new_comments != existing_row.get("PRD Comments", ""):
        changes["PRD Comments"] = new_comments

    # Check feature name change
    new_name = item.get("feature_name", "")[:80]
    if new_name and new_name != existing_row.get("Feature Name", ""):
        changes["Feature Name"] = new_name

    if changes:
        changes["Last Updated"] = timestamp

    return changes


def _diff_slack_item(item: dict, existing_row: dict, timestamp: str) -> dict[str, str]:
    """Compute changes between a Slack item and existing sheet row.

    Args:
        item: Slack item dict.
        existing_row: Existing sheet row dict.
        timestamp: ISO timestamp for Last Updated.

    Returns:
        Dict of column_name -> new_value for changed columns.
    """
    changes: dict[str, str] = {}

    new_text = item.get("source_text", "")
    if new_text:
        existing_text = existing_row.get("Source Text", "")
        if existing_text:
            # Append Slack text if not already present
            if new_text not in existing_text:
                changes["Source Text"] = f"{existing_text}\n[Slack] {new_text}"
        else:
            changes["Source Text"] = f"[Slack] {new_text}"

    new_desc = item.get("description", "")
    if new_desc and new_desc != existing_row.get("Description", ""):
        changes["Description"] = new_desc

    if changes:
        changes["Last Updated"] = timestamp

    return changes


def _try_semantic_match(
    item: dict,
    sheet_rows: list[dict],
    base_dir: str,
    prompts_dir: str,
    project_dir: str,
    project_name: str,
) -> Optional[dict]:
    """Try to semantically match a Slack item to existing sheet rows via LLM.

    Args:
        item: Slack item dict.
        sheet_rows: List of existing sheet row dicts.
        base_dir: Base scope-tracker directory.
        prompts_dir: Path to prompts directory.
        project_dir: Path to project directory.
        project_name: Project name.

    Returns:
        Match result dict from LLM, or None on failure.
    """
    slack_match_prompt = os.path.join(prompts_dir, "slack_match.md")

    # Build simplified rows for matching
    existing_rows = []
    for i, row in enumerate(sheet_rows):
        existing_rows.append({
            "row_number": i + 1,
            "feature_name": row.get("Feature Name", ""),
            "description": row.get("Description", ""),
            "source_id": row.get("Source ID", ""),
        })

    # Write temp files for the LLM
    system_dir = os.path.join(project_dir, "system")
    os.makedirs(system_dir, exist_ok=True)

    slack_item_path = os.path.join(system_dir, f"{project_name}_match_slack_item.json")
    existing_rows_path = os.path.join(system_dir, f"{project_name}_match_existing.json")
    output_path = os.path.join(system_dir, f"{project_name}_match_result.json")

    with open(slack_item_path, "w", encoding="utf-8") as f:
        json.dump(item, f, indent=2)
    with open(existing_rows_path, "w", encoding="utf-8") as f:
        json.dump(existing_rows, f, indent=2)

    try:
        call_llm(
            prompt_file=slack_match_prompt,
            placeholders={
                "SLACK_ITEM_JSON": slack_item_path,
                "EXISTING_ROWS_JSON": existing_rows_path,
                "OUTPUT_PATH": output_path,
            },
            cwd=base_dir,
        )

        with open(output_path, "r", encoding="utf-8") as f:
            result = json.load(f)

        # Reject low confidence matches
        if result.get("confidence") == "low":
            result["match_found"] = False

        return result
    except (RuntimeError, FileNotFoundError, json.JSONDecodeError) as e:
        _log(f"Warning: Semantic match failed: {e}")
        return None


def _build_formatting_spec(headers: list[str], config: dict) -> dict:
    """Build the formatting specification for the sheet.

    Args:
        headers: List of column headers.
        config: Full config dict.

    Returns:
        Dict describing all formatting rules.
    """
    widths = get_column_widths(config)
    band_separators = _get_band_separator_indices(headers)

    columns = []
    for i, h in enumerate(headers):
        columns.append({
            "index": i,
            "name": h,
            "width": widths.get(h, 100),
            "wrap": _is_wrap_column(h),
            "band_color": _get_band_color(i, headers),
            "bold": h == "Effective Status",
        })

    return {
        "frozen_rows": 1,
        "frozen_columns": 3,
        "header_height": 32,
        "data_row_height": 24,
        "columns": columns,
        "band_separators": band_separators,
        "border_color": THIN_BORDER_COLOR,
        "separator_color": BAND_SEPARATOR_COLOR,
    }


def _build_dropdown_spec(headers: list[str], config: dict) -> list[dict]:
    """Build dropdown validation specifications.

    Args:
        headers: List of column headers.
        config: Full config dict.

    Returns:
        List of dropdown spec dicts.
    """
    sheet_config = config.get("sheet_config", {})
    dropdowns = []

    for i, h in enumerate(headers):
        options = None
        if h == "Scope Decision":
            options = sheet_config.get("scope_decision_options", [])
        elif h == "Target Version":
            options = sheet_config.get("version_options", [])
        elif h == "Blocker?":
            options = sheet_config.get("blocker_options", [])
        elif h.endswith("Status") and h.startswith("UAT #"):
            options = sheet_config.get("status_options", [])

        if options:
            dropdowns.append({
                "column_index": i,
                "column_name": h,
                "options": options,
                "start_row": 2,
                "end_row": 1000,
            })

    return dropdowns


def _build_conditional_formatting_spec(headers: list[str]) -> list[dict]:
    """Build conditional formatting rules.

    Args:
        headers: List of column headers.

    Returns:
        List of conditional formatting rule dicts.
    """
    rules = []

    # Find column indices
    eff_status_idx = None
    scope_decision_idx = None
    blocker_idx = None
    for i, h in enumerate(headers):
        if h == "Effective Status":
            eff_status_idx = i
        elif h == "Scope Decision":
            scope_decision_idx = i
        elif h == "Blocker?":
            blocker_idx = i

    if eff_status_idx is not None:
        rules.extend([
            {
                "column_index": eff_status_idx,
                "condition": "TEXT_EQ",
                "value": "Passed",
                "format": {"backgroundColor": COND_PASSED},
            },
            {
                "column_index": eff_status_idx,
                "condition": "TEXT_EQ",
                "value": "Failed",
                "format": {"backgroundColor": COND_FAILED},
            },
            {
                "column_index": eff_status_idx,
                "condition": "TEXT_EQ",
                "value": "Blocked",
                "format": {"backgroundColor": COND_BLOCKED},
            },
            {
                "column_index": eff_status_idx,
                "condition": "TEXT_EQ",
                "value": "Passed with iteration",
                "format": {"backgroundColor": COND_PASSED_ITER},
            },
        ])

    if scope_decision_idx is not None:
        rules.extend([
            {
                "column_index": scope_decision_idx,
                "condition": "TEXT_EQ",
                "value": "Active Blocker",
                "format": {
                    "textFormat": {"foregroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}, "bold": True}
                },
            },
            {
                "column_index": scope_decision_idx,
                "condition": "TEXT_EQ",
                "value": "Conflicting Signal",
                "format": {
                    "textFormat": {"foregroundColor": {"red": 1.0, "green": 0.65, "blue": 0.0}, "bold": True}
                },
            },
        ])

    if blocker_idx is not None:
        rules.append({
            "column_index": blocker_idx,
            "condition": "TEXT_EQ",
            "value": "Yes",
            "format": {
                "textFormat": {"foregroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}}
            },
        })

    return rules


def add_row(
    item: dict,
    row_number: int,
    run_count: int,
    timestamp: str,
    headers: list[str],
    source: str,
) -> list[str]:
    """Public interface for building a row from an item.

    Sets all tool-owned columns. Leaves all user-owned columns empty.

    Args:
        item: PRD or Slack item dict.
        row_number: The # column value.
        run_count: Run number for Added Run column.
        timestamp: ISO timestamp for Last Updated.
        headers: Full list of column headers.
        source: "PRD" or "Slack".

    Returns:
        List of cell values in header order.
    """
    return _build_row_from_item(item, row_number, run_count, timestamp, headers, source)


def update_row(
    existing_row: dict,
    changes: dict[str, str],
    headers: list[str],
) -> list[str]:
    """Update specific cells in a row. Never touches user-owned columns.

    Args:
        existing_row: Dict of current row values.
        changes: Dict of column_name -> new_value for columns to update.
        headers: Full list of column headers.

    Returns:
        Full row list with changes applied.
    """
    # User-owned columns that must never be touched
    user_owned = {"Blocker?", "Tester", "Test Date"}
    for h in headers:
        if h.startswith("UAT #"):
            user_owned.add(h)

    updated = dict(existing_row)
    for col, val in changes.items():
        if col not in user_owned:
            updated[col] = val

    return [updated.get(h, "") for h in headers]


def main() -> None:
    """Main entry point for sheet_manager.py CLI."""
    parser = argparse.ArgumentParser(description="Google Sheet manager for scope-tracker")
    parser.add_argument("--project-dir", required=True, help="Path to project directory")
    parser.add_argument("--config", required=True, help="Path to scope_tracker_config.json")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument(
        "--operation",
        required=True,
        choices=["create", "update"],
        help="Operation to perform",
    )
    parser.add_argument("--prd-features", default=None, help="Path to PRD features JSON")
    parser.add_argument("--slack-items", default=None, help="Path to Slack items JSON")
    parser.add_argument("--client-secret", default=None, help="Path to Google OAuth2 client_secret.json")
    parser.add_argument("--token-path", default=None, help="Path to directory for token.json")

    args = parser.parse_args()

    project_dir = os.path.expanduser(os.path.abspath(args.project_dir))
    config_path = os.path.expanduser(os.path.abspath(args.config))

    config, project_config = load_config(config_path, args.project)

    try:
        if args.operation == "create":
            if not args.prd_features:
                _log("Error: --prd-features required for create operation")
                sys.exit(1)
            result = create_sheet(config, project_config, project_dir, args.prd_features)
        else:
            result = update_sheet(
                config,
                project_config,
                project_dir,
                prd_features_path=args.prd_features,
                slack_items_path=args.slack_items,
            )
    except Exception as e:
        _log(f"Error: {e}")
        result = {"status": "error", "message": str(e)}
        json.dump(result, sys.stdout, indent=2)
        sys.exit(1)

    json.dump(result, sys.stdout, indent=2)
    print(file=sys.stdout)  # trailing newline
    sys.exit(0)


if __name__ == "__main__":
    main()
