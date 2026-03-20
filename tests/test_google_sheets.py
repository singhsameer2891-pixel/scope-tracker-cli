"""Tests for google_sheets.py — direct Google Sheets API module.

Tests OAuth2 authentication, spreadsheet create/read/update, and
formatting request generation with mocked Google API calls.
"""

import json
import os
from unittest.mock import MagicMock, patch, mock_open

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_creds():
    """Return a mock Google OAuth2 Credentials object."""
    creds = MagicMock()
    creds.valid = True
    creds.expired = False
    creds.refresh_token = "fake-refresh-token"
    creds.to_json.return_value = '{"token": "fake"}'
    return creds


@pytest.fixture
def mock_service():
    """Return a mock Sheets API service with common methods."""
    service = MagicMock()
    return service


@pytest.fixture
def sample_headers():
    """Return a minimal set of headers for testing."""
    return ["#", "Feature Name", "Description", "Source", "Source ID"]


@pytest.fixture
def sample_rows():
    """Return sample data rows."""
    return [
        ["1", "Login", "User login feature", "PRD", "PRD:1"],
        ["2", "Signup", "User signup feature", "PRD", "PRD:2"],
    ]


@pytest.fixture
def sample_formatting():
    """Return a minimal formatting spec."""
    return {
        "frozen_rows": 1,
        "frozen_columns": 3,
        "columns": [
            {"index": 0, "name": "#", "width": 40, "wrap": False, "band_color": {"red": 0.91, "green": 0.94, "blue": 1.0}, "bold": False},
            {"index": 1, "name": "Feature Name", "width": 300, "wrap": False, "band_color": {"red": 0.91, "green": 0.94, "blue": 1.0}, "bold": False},
        ],
        "band_separators": [2],
        "border_color": {"red": 0.88, "green": 0.88, "blue": 0.88},
        "separator_color": {"red": 0.74, "green": 0.74, "blue": 0.74},
    }


# ---------------------------------------------------------------------------
# Test: create_spreadsheet
# ---------------------------------------------------------------------------

@patch("scope_tracker.scripts.google_sheets._get_service")
def test_create_returns_spreadsheet_id_and_url(mock_get_service, mock_creds, sample_headers, sample_rows, sample_formatting):
    """create_spreadsheet returns spreadsheet_id and sheet_url."""
    from scope_tracker.scripts.google_sheets import create_spreadsheet

    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    # Mock spreadsheet creation
    mock_service.spreadsheets().create().execute.return_value = {
        "spreadsheetId": "abc123",
        "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/abc123/edit",
    }

    # Mock values update (write data)
    mock_service.spreadsheets().values().update().execute.return_value = {}

    # Mock batchUpdate (formatting)
    mock_service.spreadsheets().batchUpdate().execute.return_value = {}

    result = create_spreadsheet(
        creds=mock_creds,
        title="Test Sheet",
        headers=sample_headers,
        rows=sample_rows,
        column_widths={"#": 40, "Feature Name": 300},
        formatting=sample_formatting,
        dropdowns=[],
        conditional_formatting=[],
    )

    assert result["spreadsheet_id"] == "abc123"
    assert "abc123" in result["sheet_url"]


# ---------------------------------------------------------------------------
# Test: read_spreadsheet
# ---------------------------------------------------------------------------

@patch("scope_tracker.scripts.google_sheets._get_service")
def test_read_returns_rows(mock_get_service, mock_creds):
    """read_spreadsheet returns rows from the sheet."""
    from scope_tracker.scripts.google_sheets import read_spreadsheet

    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    mock_service.spreadsheets().values().get().execute.return_value = {
        "values": [
            ["#", "Feature Name"],
            ["1", "Login"],
            ["2", "Signup"],
        ]
    }

    result = read_spreadsheet(creds=mock_creds, spreadsheet_id="abc123")

    assert "rows" in result
    assert len(result["rows"]) == 3
    assert result["rows"][0] == ["#", "Feature Name"]
    assert result["rows"][1] == ["1", "Login"]


@patch("scope_tracker.scripts.google_sheets._get_service")
def test_read_empty_spreadsheet(mock_get_service, mock_creds):
    """read_spreadsheet returns empty rows for an empty sheet."""
    from scope_tracker.scripts.google_sheets import read_spreadsheet

    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    mock_service.spreadsheets().values().get().execute.return_value = {"values": []}

    result = read_spreadsheet(creds=mock_creds, spreadsheet_id="abc123")
    assert result["rows"] == []


# ---------------------------------------------------------------------------
# Test: update_spreadsheet
# ---------------------------------------------------------------------------

@patch("scope_tracker.scripts.google_sheets._get_service")
def test_update_applies_changes(mock_get_service, mock_creds, sample_headers, sample_formatting):
    """update_spreadsheet applies add and update changes."""
    from scope_tracker.scripts.google_sheets import update_spreadsheet

    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    # Mock reading total rows for formatting
    mock_service.spreadsheets().values().get().execute.return_value = {
        "values": [["1"], ["2"], ["3"]]
    }

    # Mock batch update calls
    mock_service.spreadsheets().values().batchUpdate().execute.return_value = {}
    mock_service.spreadsheets().values().append().execute.return_value = {}
    mock_service.spreadsheets().batchUpdate().execute.return_value = {}

    changes = [
        {"type": "update", "row_index": 2, "changes": {"Feature Name": "Updated Login"}},
        {"type": "add", "row_data": ["3", "Logout", "User logout", "Slack", "SLACK:123"]},
        {"type": "update_cell", "row_index": 3, "column": "Description", "value": "New desc"},
    ]

    result = update_spreadsheet(
        creds=mock_creds,
        spreadsheet_id="abc123",
        changes=changes,
        headers=sample_headers,
        formatting=sample_formatting,
        dropdowns=[],
        conditional_formatting=[],
    )

    assert result["status"] == "updated"
    assert result["rows_modified"] == 3


# ---------------------------------------------------------------------------
# Test: formatting applies without error
# ---------------------------------------------------------------------------

@patch("scope_tracker.scripts.google_sheets._get_service")
def test_formatting_applies_without_error(mock_get_service, mock_creds, sample_headers, sample_rows, sample_formatting):
    """Full create with formatting, dropdowns, and conditional formatting completes without error."""
    from scope_tracker.scripts.google_sheets import create_spreadsheet

    mock_service = MagicMock()
    mock_get_service.return_value = mock_service

    mock_service.spreadsheets().create().execute.return_value = {
        "spreadsheetId": "fmt123",
        "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/fmt123/edit",
    }
    mock_service.spreadsheets().values().update().execute.return_value = {}
    mock_service.spreadsheets().batchUpdate().execute.return_value = {}

    dropdowns = [
        {"column_index": 3, "options": ["In Scope", "Parked"], "start_row": 2, "end_row": 100},
    ]
    cond_formatting = [
        {
            "column_index": 4,
            "condition": "TEXT_EQ",
            "value": "Passed",
            "format": {"backgroundColor": {"red": 0.78, "green": 0.90, "blue": 0.79}},
        },
    ]

    result = create_spreadsheet(
        creds=mock_creds,
        title="Formatted Sheet",
        headers=sample_headers,
        rows=sample_rows,
        column_widths={"#": 40},
        formatting=sample_formatting,
        dropdowns=dropdowns,
        conditional_formatting=cond_formatting,
    )

    assert result["spreadsheet_id"] == "fmt123"
    # Verify batchUpdate was called (formatting was applied)
    mock_service.spreadsheets().batchUpdate.assert_called()


# ---------------------------------------------------------------------------
# Test: authenticate
# ---------------------------------------------------------------------------

@patch("scope_tracker.scripts.google_sheets.InstalledAppFlow")
@patch("scope_tracker.scripts.google_sheets.Credentials")
def test_authenticate_loads_existing_token(mock_creds_class, mock_flow, tmp_path):
    """authenticate loads existing token.json when valid."""
    from scope_tracker.scripts.google_sheets import authenticate

    # Write a fake client_secret.json
    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text('{"installed": {"client_id": "fake"}}')

    # Write a fake token.json
    token_path = tmp_path / "token.json"
    token_path.write_text('{"token": "fake"}')

    mock_creds = MagicMock()
    mock_creds.valid = True
    mock_creds.expired = False
    mock_creds.to_json.return_value = '{"token": "fake"}'
    mock_creds_class.from_authorized_user_file.return_value = mock_creds

    result = authenticate(str(client_secret), str(tmp_path))

    assert result == mock_creds
    mock_flow.from_client_secrets_file.assert_not_called()  # no new flow needed


@patch("scope_tracker.scripts.google_sheets.InstalledAppFlow")
@patch("scope_tracker.scripts.google_sheets.Credentials")
def test_authenticate_runs_flow_when_no_token(mock_creds_class, mock_flow, tmp_path):
    """authenticate runs OAuth flow when no token.json exists."""
    from scope_tracker.scripts.google_sheets import authenticate

    client_secret = tmp_path / "client_secret.json"
    client_secret.write_text('{"installed": {"client_id": "fake"}}')

    mock_new_creds = MagicMock()
    mock_new_creds.valid = True
    mock_new_creds.to_json.return_value = '{"token": "new"}'
    mock_flow.from_client_secrets_file.return_value.run_local_server.return_value = mock_new_creds

    result = authenticate(str(client_secret), str(tmp_path))

    assert result == mock_new_creds
    mock_flow.from_client_secrets_file.assert_called_once()


def test_authenticate_raises_on_missing_client_secret(tmp_path):
    """authenticate raises FileNotFoundError when client_secret.json is missing."""
    from scope_tracker.scripts.google_sheets import authenticate

    with pytest.raises(FileNotFoundError, match="Client secret file not found"):
        authenticate(str(tmp_path / "nonexistent.json"), str(tmp_path))


# ---------------------------------------------------------------------------
# Test: get_sheets_service
# ---------------------------------------------------------------------------

@patch("scope_tracker.scripts.google_sheets.authenticate")
@patch("scope_tracker.scripts.google_sheets._get_service")
def test_get_sheets_service(mock_get_svc, mock_auth):
    """get_sheets_service returns (service, creds) tuple."""
    from scope_tracker.scripts.google_sheets import get_sheets_service

    mock_creds = MagicMock()
    mock_auth.return_value = mock_creds
    mock_svc = MagicMock()
    mock_get_svc.return_value = mock_svc

    service, creds = get_sheets_service("/fake/client_secret.json", "/fake/dir/token.json")

    assert service == mock_svc
    assert creds == mock_creds


# ---------------------------------------------------------------------------
# Test: helper functions
# ---------------------------------------------------------------------------

def test_col_letter():
    """_col_letter converts indices to sheet column letters."""
    from scope_tracker.scripts.google_sheets import _col_letter

    assert _col_letter(0) == "A"
    assert _col_letter(25) == "Z"
    assert _col_letter(26) == "AA"
    assert _col_letter(27) == "AB"
