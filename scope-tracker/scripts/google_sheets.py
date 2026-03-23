"""Direct Google Sheets API access for scope-tracker.

Replaces LLM-based sheet operations with direct API calls using OAuth2
authentication. Handles creating, reading, and updating Google Spreadsheets
with full formatting, dropdowns, and conditional formatting support.

All human-readable logs go to stderr. Return values are dicts suitable
for JSON serialization to stdout.

Inputs:
    - client_secret JSON path (for OAuth2 flow)
    - Spreadsheet data: headers, rows, formatting specs

Output format:
    - create_spreadsheet → {"sheet_url": "...", "spreadsheet_id": "..."}
    - read_spreadsheet → {"rows": [[...], ...]}
    - update_spreadsheet → {"status": "updated", "rows_modified": N}
"""

import json
import os
import sys
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# OAuth2 scopes required for spreadsheet operations
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _log(msg: str) -> None:
    """Log a human-readable message to stderr.

    Args:
        msg: The message to log.
    """
    print(f"[google_sheets] {msg}", file=sys.stderr)


def authenticate(
    client_secret_path: str,
    token_dir: str,
) -> Credentials:
    """Authenticate with Google Sheets API via OAuth2.

    First-time usage opens a browser for the OAuth consent flow and saves
    the resulting token to {token_dir}/token.json. Subsequent calls reuse
    the saved refresh token.

    Args:
        client_secret_path: Absolute path to the OAuth2 client_secret JSON file.
        token_dir: Directory where token.json will be stored (the scope-tracker dir).

    Returns:
        Authenticated Google OAuth2 Credentials object.

    Raises:
        FileNotFoundError: If client_secret_path does not exist.
        Exception: If the OAuth flow fails.
    """
    client_secret_path = os.path.expanduser(os.path.abspath(client_secret_path))
    token_dir = os.path.expanduser(os.path.abspath(token_dir))
    token_path = os.path.join(token_dir, "token.json")

    if not os.path.isfile(client_secret_path):
        raise FileNotFoundError(
            f"Client secret file not found: {client_secret_path}"
        )

    creds: Optional[Credentials] = None

    # Try loading existing token
    if os.path.isfile(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            _log(f"Could not load saved token, will re-authenticate: {e}")
            creds = None

    # Refresh or run OAuth flow
    if creds and creds.valid:
        _log("Using cached credentials")
    elif creds and creds.expired and creds.refresh_token:
        try:
            _log("Refreshing expired credentials")
            creds.refresh(Request())
        except Exception as e:
            _log(f"Token refresh failed, re-authenticating: {e}")
            creds = None

    if not creds or not creds.valid:
        _log("Starting OAuth2 consent flow (browser will open)")
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_path, SCOPES)
        creds = flow.run_local_server(port=0)

    # Save token for next time
    try:
        os.makedirs(token_dir, exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        _log(f"Token saved to {token_path}")
    except OSError as e:
        _log(f"Warning: could not save token: {e}")

    return creds


def get_sheets_service(
    client_secret_path: str,
    token_path: str,
) -> tuple[Any, "Credentials"]:
    """Authenticate and return a Sheets API service object plus credentials.

    Convenience wrapper that combines authenticate() and service creation.

    Args:
        client_secret_path: Absolute path to the OAuth2 client_secret JSON file.
        token_path: Path where token.json is stored (typically the scope-tracker dir).

    Returns:
        Tuple of (Sheets API service resource, Credentials).
    """
    token_dir = os.path.dirname(token_path) if os.path.basename(token_path) == "token.json" else token_path
    creds = authenticate(client_secret_path, token_dir)
    service = _get_service(creds)
    return service, creds


def _get_service(creds: Credentials) -> Any:
    """Build the Google Sheets API service object.

    Args:
        creds: Authenticated credentials.

    Returns:
        Google Sheets API service resource.
    """
    return build("sheets", "v4", credentials=creds)


def _col_letter(index: int) -> str:
    """Convert a zero-based column index to a Sheets column letter (A, B, ..., Z, AA, ...).

    Args:
        index: Zero-based column index.

    Returns:
        Column letter string.
    """
    result = ""
    while True:
        result = chr(ord("A") + index % 26) + result
        index = index // 26 - 1
        if index < 0:
            break
    return result


def _build_color(rgb: dict) -> dict:
    """Build a Sheets API color dict from an RGB dict.

    Args:
        rgb: Dict with 'red', 'green', 'blue' keys (0.0-1.0 floats).

    Returns:
        Color dict suitable for the Sheets API.
    """
    return {
        "red": rgb.get("red", 0.0),
        "green": rgb.get("green", 0.0),
        "blue": rgb.get("blue", 0.0),
    }


def _build_border(style: str, color: dict) -> dict:
    """Build a Sheets API border spec.

    Args:
        style: Border style string (e.g. 'SOLID', 'SOLID_MEDIUM').
        color: RGB color dict.

    Returns:
        Border dict for the Sheets API.
    """
    return {
        "style": style,
        "color": _build_color(color),
    }


def create_spreadsheet(
    creds: Credentials,
    title: str,
    headers: list[str],
    rows: list[list[str]],
    column_widths: dict[str, int],
    formatting: dict,
    dropdowns: list[dict],
    conditional_formatting: list[dict],
) -> dict[str, str]:
    """Create a new Google Spreadsheet with data and full formatting.

    Creates the spreadsheet, writes header + data rows, then applies all
    formatting in a single batchUpdate call: column widths, frozen rows/cols,
    band colors, text wrapping, bold headers, band separator borders, thin
    cell borders, dropdown validations, and conditional formatting rules.

    Args:
        creds: Authenticated Google OAuth2 credentials.
        title: Spreadsheet title.
        headers: Ordered list of column header strings.
        rows: List of row lists (each row is a list of cell value strings).
        column_widths: Dict mapping column name to width in pixels.
        formatting: Formatting spec dict with keys: frozen_rows, frozen_columns,
            columns (list of dicts with index, name, width, wrap, band_color, bold),
            band_separators (list of column indices), border_color, separator_color.
        dropdowns: List of dropdown spec dicts with keys: column_index, options,
            start_row, end_row.
        conditional_formatting: List of conditional formatting rule dicts with keys:
            column_index, condition, value, format (with backgroundColor and/or textFormat).

    Returns:
        Dict with 'sheet_url' and 'spreadsheet_id'.

    Raises:
        HttpError: If the Google Sheets API call fails.
    """
    service = _get_service(creds)

    # Step 1: Create empty spreadsheet
    _log(f"Creating spreadsheet: {title}")
    try:
        spreadsheet_body = {"properties": {"title": title}}
        spreadsheet = (
            service.spreadsheets()
            .create(body=spreadsheet_body, fields="spreadsheetId,spreadsheetUrl")
            .execute()
        )
    except HttpError as e:
        _log(f"Error creating spreadsheet: {e}")
        raise

    spreadsheet_id = spreadsheet["spreadsheetId"]
    sheet_url = spreadsheet.get("spreadsheetUrl", "")
    _log(f"Spreadsheet created: {spreadsheet_id}")

    # Step 2: Write header + data rows
    all_rows = [headers] + rows
    range_str = f"Sheet1!A1:{_col_letter(len(headers) - 1)}{len(all_rows)}"

    try:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_str,
            valueInputOption="RAW",
            body={"values": all_rows},
        ).execute()
        _log(f"Wrote {len(all_rows)} rows ({len(headers)} columns)")
    except HttpError as e:
        _log(f"Error writing data: {e}")
        raise

    # Step 3: Build and execute batchUpdate for all formatting
    requests = _build_formatting_requests(
        headers=headers,
        num_rows=len(all_rows),
        formatting=formatting,
        column_widths=column_widths,
        dropdowns=dropdowns,
        conditional_formatting=conditional_formatting,
    )

    if requests:
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            ).execute()
            _log(f"Applied {len(requests)} formatting requests")
        except HttpError as e:
            _log(f"Error applying formatting: {e}")
            raise

    return {"sheet_url": sheet_url, "spreadsheet_id": spreadsheet_id}


def read_spreadsheet(
    creds: Credentials,
    spreadsheet_id: str,
) -> dict[str, list[list[str]]]:
    """Read all data from Sheet1 of a Google Spreadsheet.

    Args:
        creds: Authenticated Google OAuth2 credentials.
        spreadsheet_id: The ID of the spreadsheet to read.

    Returns:
        Dict with 'rows' key containing a list of lists (each row is a list
        of cell value strings). The first row is the header row.

    Raises:
        HttpError: If the Google Sheets API call fails.
    """
    service = _get_service(creds)

    _log(f"Reading spreadsheet: {spreadsheet_id}")
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range="Sheet1")
            .execute()
        )
    except HttpError as e:
        _log(f"Error reading spreadsheet: {e}")
        raise

    rows = result.get("values", [])
    _log(f"Read {len(rows)} rows")
    return {"rows": rows}


def update_spreadsheet(
    creds: Credentials,
    spreadsheet_id: str,
    changes: list[dict],
    headers: list[str],
    formatting: dict,
    dropdowns: list[dict],
    conditional_formatting: list[dict],
) -> dict[str, Any]:
    """Apply a list of changes to an existing Google Spreadsheet.

    Supports three change types:
    - {"type": "add", "row_data": [...]} — append a new row
    - {"type": "update", "row_index": N, "changes": {"col_name": "val"}} — update
      specific cells in row N (1-indexed, row 1 = header)
    - {"type": "update_cell", "row_index": N, "column": "name", "value": "val"} —
      update a single cell

    After applying data changes, re-applies all formatting to ensure consistency.

    Args:
        creds: Authenticated Google OAuth2 credentials.
        spreadsheet_id: The ID of the spreadsheet to update.
        changes: List of change dicts (see above for types).
        headers: Ordered list of column header strings.
        formatting: Formatting spec dict (same structure as create_spreadsheet).
        dropdowns: List of dropdown spec dicts.
        conditional_formatting: List of conditional formatting rule dicts.

    Returns:
        Dict with 'status' and 'rows_modified' count.

    Raises:
        HttpError: If the Google Sheets API call fails.
    """
    service = _get_service(creds)
    header_index = {name: idx for idx, name in enumerate(headers)}

    rows_modified = 0
    append_rows: list[list[str]] = []
    value_updates: list[dict] = []

    for change in changes:
        change_type = change.get("type", "")

        if change_type == "add":
            row_data = change.get("row_data", [])
            append_rows.append(row_data)
            rows_modified += 1

        elif change_type == "update":
            row_index = change.get("row_index", 0)  # 1-indexed
            col_changes = change.get("changes", {})
            for col_name, value in col_changes.items():
                col_idx = header_index.get(col_name)
                if col_idx is not None:
                    cell_ref = f"Sheet1!{_col_letter(col_idx)}{row_index}"
                    value_updates.append({
                        "range": cell_ref,
                        "values": [[value]],
                    })
            rows_modified += 1

        elif change_type == "update_cell":
            row_index = change.get("row_index", 0)
            col_name = change.get("column", "")
            value = change.get("value", "")
            col_idx = header_index.get(col_name)
            if col_idx is not None:
                cell_ref = f"Sheet1!{_col_letter(col_idx)}{row_index}"
                value_updates.append({
                    "range": cell_ref,
                    "values": [[value]],
                })
                rows_modified += 1

    # Apply cell updates via batchUpdate values
    if value_updates:
        _log(f"Applying {len(value_updates)} cell updates")
        try:
            service.spreadsheets().values().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": value_updates,
                },
            ).execute()
        except HttpError as e:
            _log(f"Error applying cell updates: {e}")
            raise

    # Append new rows
    if append_rows:
        _log(f"Appending {len(append_rows)} new rows")
        try:
            service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range=f"Sheet1!A1:{_col_letter(len(headers) - 1)}1",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": append_rows},
            ).execute()
        except HttpError as e:
            _log(f"Error appending rows: {e}")
            raise

    # Determine total row count for formatting
    try:
        result = (
            service.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range="Sheet1!A:A")
            .execute()
        )
        total_rows = len(result.get("values", []))
    except HttpError:
        total_rows = 1000  # fallback

    # Re-apply formatting
    column_widths = {}
    for col_spec in formatting.get("columns", []):
        column_widths[col_spec["name"]] = col_spec.get("width", 100)

    requests = _build_formatting_requests(
        headers=headers,
        num_rows=total_rows,
        formatting=formatting,
        column_widths=column_widths,
        dropdowns=dropdowns,
        conditional_formatting=conditional_formatting,
    )

    if requests:
        try:
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            ).execute()
            _log(f"Re-applied {len(requests)} formatting requests")
        except HttpError as e:
            _log(f"Error re-applying formatting: {e}")
            raise

    _log(f"Update complete: {rows_modified} rows modified")
    return {"status": "updated", "rows_modified": rows_modified}


def _build_formatting_requests(
    headers: list[str],
    num_rows: int,
    formatting: dict,
    column_widths: dict[str, int],
    dropdowns: list[dict],
    conditional_formatting: list[dict],
) -> list[dict]:
    """Build all Sheets API batchUpdate requests for formatting.

    Constructs requests for: frozen rows/columns, column widths, bold header
    row, band colors per column, text wrapping, band separator borders, thin
    cell borders, dropdown validations, and conditional formatting rules.

    Args:
        headers: List of column header strings.
        num_rows: Total number of rows (including header).
        formatting: Formatting spec dict.
        column_widths: Dict mapping column name to width in pixels.
        dropdowns: List of dropdown spec dicts.
        conditional_formatting: List of conditional formatting rule dicts.

    Returns:
        List of Sheets API request dicts for batchUpdate.
    """
    requests: list[dict] = []
    sheet_id = 0  # default Sheet1

    num_cols = len(headers)
    frozen_rows = formatting.get("frozen_rows", 1)
    frozen_cols = formatting.get("frozen_columns", 3)
    columns_spec = formatting.get("columns", [])
    band_separators = formatting.get("band_separators", [])
    border_color = formatting.get("border_color", {"red": 0.88, "green": 0.88, "blue": 0.88})
    separator_color = formatting.get("separator_color", {"red": 0.74, "green": 0.74, "blue": 0.74})

    # 1. Frozen rows and columns
    requests.append({
        "updateSheetProperties": {
            "properties": {
                "sheetId": sheet_id,
                "gridProperties": {
                    "frozenRowCount": frozen_rows,
                    "frozenColumnCount": frozen_cols,
                },
            },
            "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount",
        }
    })

    # 2. Column widths
    for col_spec in columns_spec:
        col_idx = col_spec["index"]
        col_name = col_spec["name"]
        width = column_widths.get(col_name, col_spec.get("width", 100))
        requests.append({
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "properties": {"pixelSize": width},
                "fields": "pixelSize",
            }
        })

    # 3. Bold header row
    requests.append({
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "cell": {
                "userEnteredFormat": {
                    "textFormat": {"bold": True},
                    "horizontalAlignment": "CENTER",
                    "verticalAlignment": "MIDDLE",
                }
            },
            "fields": "userEnteredFormat(textFormat,horizontalAlignment,verticalAlignment)",
        }
    })

    # 4. Band colors per column (applied to header + data rows)
    for col_spec in columns_spec:
        col_idx = col_spec["index"]
        band_color = col_spec.get("band_color")
        if band_color:
            # Apply band color to header row for this column
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": col_idx,
                        "endColumnIndex": col_idx + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": _build_color(band_color),
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                }
            })

            # Apply band color to data rows for this column
            if num_rows > 1:
                requests.append({
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "endRowIndex": num_rows,
                            "startColumnIndex": col_idx,
                            "endColumnIndex": col_idx + 1,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": _build_color(band_color),
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                })

    # 5. Text wrapping on specific columns
    for col_spec in columns_spec:
        if col_spec.get("wrap"):
            col_idx = col_spec["index"]
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": num_rows,
                        "startColumnIndex": col_idx,
                        "endColumnIndex": col_idx + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "wrapStrategy": "WRAP",
                        }
                    },
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            })

    # 6. Bold text for columns marked as bold (e.g., Effective Status)
    for col_spec in columns_spec:
        if col_spec.get("bold") and num_rows > 1:
            col_idx = col_spec["index"]
            requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 1,
                        "endRowIndex": num_rows,
                        "startColumnIndex": col_idx,
                        "endColumnIndex": col_idx + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {"bold": True},
                        }
                    },
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            })

    # 7. Thin borders on all cells
    requests.append({
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": 0,
                "endRowIndex": num_rows,
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "top": _build_border("SOLID", border_color),
            "bottom": _build_border("SOLID", border_color),
            "left": _build_border("SOLID", border_color),
            "right": _build_border("SOLID", border_color),
            "innerHorizontal": _build_border("SOLID", border_color),
            "innerVertical": _build_border("SOLID", border_color),
        }
    })

    # 8. Band separator borders (thicker borders between column groups)
    for sep_col_idx in band_separators:
        if 0 <= sep_col_idx < num_cols:
            requests.append({
                "updateBorders": {
                    "range": {
                        "sheetId": sheet_id,
                        "startRowIndex": 0,
                        "endRowIndex": num_rows,
                        "startColumnIndex": sep_col_idx,
                        "endColumnIndex": sep_col_idx + 1,
                    },
                    "right": _build_border("SOLID_MEDIUM", separator_color),
                }
            })

    # 9. Dropdown validations
    for dropdown in dropdowns:
        col_idx = dropdown.get("column_index", 0)
        options = dropdown.get("options", [])
        start_row = dropdown.get("start_row", 2)  # 1-indexed
        end_row = dropdown.get("end_row", 1000)

        if not options:
            continue

        condition_values = [{"userEnteredValue": opt} for opt in options]

        requests.append({
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": start_row - 1,  # convert to 0-indexed
                    "endRowIndex": end_row,
                    "startColumnIndex": col_idx,
                    "endColumnIndex": col_idx + 1,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": condition_values,
                    },
                    "showCustomUi": True,
                    "strict": False,
                },
            }
        })

    # 10. Conditional formatting rules
    for rule in conditional_formatting:
        col_idx = rule.get("column_index", 0)
        condition = rule.get("condition", "")
        value = rule.get("value", "")
        fmt = rule.get("format", {})

        if not condition or not value:
            continue

        # Map condition names to Sheets API condition types
        condition_type_map = {
            "TEXT_EQ": "TEXT_EQ",
            "TEXT_CONTAINS": "TEXT_CONTAINS",
            "TEXT_NOT_CONTAINS": "TEXT_NOT_CONTAINS",
        }
        api_condition_type = condition_type_map.get(condition, "TEXT_EQ")

        # Build the cell format for the rule
        cell_format: dict[str, Any] = {}

        bg_color = fmt.get("backgroundColor")
        if bg_color:
            cell_format["backgroundColor"] = _build_color(bg_color)

        text_format = fmt.get("textFormat")
        if text_format:
            tf: dict[str, Any] = {}
            fg_color = text_format.get("foregroundColor")
            if fg_color:
                tf["foregroundColor"] = _build_color(fg_color)
            if text_format.get("bold") is not None:
                tf["bold"] = text_format["bold"]
            if tf:
                cell_format["textFormat"] = tf

        if not cell_format:
            continue

        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [
                        {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,  # skip header
                            "endRowIndex": num_rows,
                            "startColumnIndex": col_idx,
                            "endColumnIndex": col_idx + 1,
                        }
                    ],
                    "booleanRule": {
                        "condition": {
                            "type": api_condition_type,
                            "values": [{"userEnteredValue": value}],
                        },
                        "format": cell_format,
                    },
                },
                "index": 0,
            }
        })

    return requests
