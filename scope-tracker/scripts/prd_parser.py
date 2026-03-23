"""Pure Python PRD parser for extracting user stories from PRD documents.

Replaces the LLM-based prd_extract.md prompt with deterministic parsing logic.
Finds the "User Stories" section, parses markdown/text tables, extracts rows
with valid numeric identifiers, and attaches inline comments.

Functions:
    extract_features(raw_text, comments, identifier_col_names, story_col_names) — list of feature dicts
"""

import json
import os
import re
import sys
from typing import Any


def _log(msg: str) -> None:
    """Log a message to stderr."""
    print(msg, file=sys.stderr)


def _find_user_stories_section(text: str) -> str | None:
    """Find the content of the 'User Stories' section in the document.

    Looks for a heading (markdown # or plain text) containing 'User Stories'
    (case-insensitive). Returns all content from that heading until the next
    heading of equal or higher level, or end of document.

    Args:
        text: Full raw PRD text.

    Returns:
        Section content string, or None if not found.
    """
    lines = text.split("\n")
    section_start = None
    section_level = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Check for markdown heading
        heading_match = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            if section_start is not None:
                # We found the next heading at same or higher level — stop
                if level <= section_level:
                    return "\n".join(lines[section_start:i])

            if re.search(r"user\s+stories", title, re.IGNORECASE):
                section_start = i + 1
                section_level = level
                continue

        # Also check for underline-style headings (===== or -----)
        if i > 0 and stripped and re.match(r"^[=]+$", stripped):
            prev_title = lines[i - 1].strip()
            if re.search(r"user\s+stories", prev_title, re.IGNORECASE):
                section_start = i + 1
                section_level = 1
                continue
            if section_start is not None:
                return "\n".join(lines[section_start:i - 1])

        if i > 0 and stripped and re.match(r"^[-]+$", stripped) and len(stripped) >= 3:
            prev_title = lines[i - 1].strip()
            if re.search(r"user\s+stories", prev_title, re.IGNORECASE):
                section_start = i + 1
                section_level = 2
                continue
            if section_start is not None and section_level <= 2:
                return "\n".join(lines[section_start:i - 1])

    if section_start is not None:
        return "\n".join(lines[section_start:])

    return None


def _parse_tables(section_text: str) -> list[list[list[str]]]:
    """Parse all pipe-delimited markdown tables from section text.

    Each table is returned as a list of rows, where each row is a list of
    cell strings. The first row is assumed to be the header. Separator
    rows (containing only dashes, pipes, colons) are excluded.

    Args:
        section_text: Text content of the User Stories section.

    Returns:
        List of tables, each being a list of rows (list of cell strings).
    """
    tables: list[list[list[str]]] = []
    current_table: list[list[str]] = []

    for line in section_text.split("\n"):
        stripped = line.strip()

        # Check if line is a pipe-delimited table row
        if "|" in stripped:
            # Split by pipe, strip whitespace from cells
            cells = [c.strip() for c in stripped.split("|")]
            # Remove empty strings from leading/trailing pipes
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]

            if not cells:
                continue

            # Check if this is a separator row (e.g., |---|---|)
            is_separator = all(
                re.match(r"^[:]*-+[:]*$", c.strip()) for c in cells if c.strip()
            )
            if is_separator:
                continue

            current_table.append(cells)
        else:
            # Non-table line — if we were building a table, finalize it
            if current_table:
                if len(current_table) >= 2:  # Need at least header + 1 data row
                    tables.append(current_table)
                current_table = []

    # Finalize last table
    if current_table and len(current_table) >= 2:
        tables.append(current_table)

    return tables


def _match_column_index(
    headers: list[str], candidate_names: list[str]
) -> int | None:
    """Find the first header that matches any candidate name (case-insensitive).

    Args:
        headers: List of header cell strings.
        candidate_names: List of acceptable column names.

    Returns:
        Column index, or None if no match.
    """
    lower_candidates = [n.lower().strip() for n in candidate_names]
    for i, h in enumerate(headers):
        if h.lower().strip() in lower_candidates:
            return i
    return None


def _is_valid_identifier(value: str) -> bool:
    """Check if a value matches the valid identifier pattern.

    Valid: 1, 1.3, 1.2.5, 2, 10.1
    Invalid: US-001, F1, Feature 1, 1., .1, blank

    Args:
        value: String to check.

    Returns:
        True if the value is a valid numeric identifier.
    """
    return bool(re.match(r"^\d+(\.\d+)*$", value.strip()))


def _attach_comments(
    features: list[dict[str, Any]], comments: list[dict[str, Any]]
) -> None:
    """Attach inline comments to features by matching anchor_text to story text.

    Modifies features in place, setting prd_comments and latest_comment_decision.

    Args:
        features: List of feature dicts with 'description' field.
        comments: List of comment dicts with 'anchor_text', 'author', 'date', 'comment_text'.
    """
    if not comments:
        return

    for feature in features:
        story_text = feature.get("description", "")
        matched_comments: list[dict[str, Any]] = []

        for comment in comments:
            anchor = comment.get("anchor_text", "")
            if not anchor:
                continue
            if anchor in story_text:
                matched_comments.append(comment)

        if not matched_comments:
            continue

        # Sort chronologically by date
        matched_comments.sort(key=lambda c: c.get("date", ""))

        # Build concatenated comment string
        parts = []
        for c in matched_comments:
            date_str = c.get("date", "")
            # Normalize date to YYYY-MM-DD
            if date_str:
                date_str = date_str[:10]  # Take only the date part
            author = c.get("author", "Unknown")
            text = c.get("comment_text", "")
            parts.append(f"[{date_str} {author}]: {text}.")

        feature["prd_comments"] = " ".join(parts)

        # Derive latest_comment_decision from most recent comment
        last_comment = matched_comments[-1]
        last_text = last_comment.get("comment_text", "").lower()

        decision = _infer_scope_decision(last_text)
        feature["latest_comment_decision"] = decision


def _infer_scope_decision(comment_text: str) -> str | None:
    """Infer a scope decision from comment text.

    Looks for keywords indicating scope decisions like 'In Scope',
    'Pushed to V2', 'Parked', 'Fast Follower', 'Descoped', etc.

    Args:
        comment_text: Lowercase comment text.

    Returns:
        Scope decision string, or None if no decision implied.
    """
    text = comment_text.lower()

    # Check for common scope decision keywords (order matters — more specific first)
    if "descope" in text or "de-scope" in text or "out of scope" in text or "out-of-scope" in text:
        return "Descoped"
    if "pushed to v2" in text or "push to v2" in text or "defer to v2" in text or "moved to v2" in text:
        return "Pushed to V2"
    if "fast follower" in text or "fast-follower" in text:
        return "Fast Follower"
    if "parked" in text or "parking" in text or "on hold" in text or "on-hold" in text:
        return "Parked"
    if "in scope" in text or "in-scope" in text or "confirmed" in text or "reinstate" in text or "approved" in text:
        return "In Scope"
    if "active blocker" in text or "blocked" in text or "blocker" in text:
        return "Active Blocker"

    return None


def extract_features(
    raw_text: str,
    comments: list[dict[str, Any]],
    identifier_col_names: list[str],
    story_col_names: list[str],
) -> list[dict[str, Any]]:
    """Extract user story features from raw PRD text.

    Finds the 'User Stories' section, parses tables, filters by valid
    identifier format, builds feature dicts, and attaches inline comments.

    Args:
        raw_text: Full raw PRD document text.
        comments: List of comment dicts with anchor_text, author, date, comment_text.
        identifier_col_names: List of acceptable identifier column header names.
        story_col_names: List of acceptable story/feature column header names.

    Returns:
        List of feature dicts with keys: source_id, identifier, feature_name,
        description, source_text, prd_comments, latest_comment_decision.
        First element includes a 'skipped_rows' key.
    """
    section = _find_user_stories_section(raw_text)
    if section is None:
        _log("No 'User Stories' section found in PRD.")
        return []

    tables = _parse_tables(section)
    if not tables:
        _log("No tables found in 'User Stories' section.")
        return []

    features: list[dict[str, Any]] = []
    skipped_rows: list[str] = []

    for table in tables:
        if len(table) < 2:
            continue

        headers = table[0]
        id_col = _match_column_index(headers, identifier_col_names)
        story_col = _match_column_index(headers, story_col_names)

        if id_col is None:
            _log(f"No identifier column found in table with headers: {headers}")
            continue
        if story_col is None:
            _log(f"No story column found in table with headers: {headers}")
            continue

        # Process data rows (skip header)
        for row in table[1:]:
            if id_col >= len(row):
                skipped_rows.append("Row with missing identifier column skipped")
                continue

            identifier = row[id_col].strip()

            if not identifier:
                skipped_rows.append("Row with empty identifier skipped")
                continue

            if not _is_valid_identifier(identifier):
                skipped_rows.append(
                    f"Row with identifier '{identifier}' skipped — non-numeric format"
                )
                continue

            story_text = row[story_col].strip() if story_col < len(row) else ""

            # Truncate feature_name to 80 chars
            feature_name = story_text[:80] if len(story_text) > 80 else story_text

            features.append({
                "source_id": f"PRD:{identifier}",
                "identifier": identifier,
                "feature_name": feature_name,
                "description": story_text,
                "source_text": story_text,
                "prd_comments": "",
                "latest_comment_decision": None,
            })

    # Attach comments
    _attach_comments(features, comments)

    # Add skipped_rows to first element
    if features:
        features[0]["skipped_rows"] = skipped_rows
    elif skipped_rows:
        _log(f"All rows were skipped: {skipped_rows}")

    return features
