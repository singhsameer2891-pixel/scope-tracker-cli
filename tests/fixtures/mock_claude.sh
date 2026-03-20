#!/usr/bin/env bash
# mock_claude.sh — Fake claude binary for end-to-end testing.
#
# Reads the -p argument, pattern-matches on known prompt types,
# and returns hardcoded valid JSON output for each. Exits 0.
#
# Usage: place this on PATH as "claude" during e2e tests.
# It also supports "--version" to pass doctor checks.

set -e

# Handle --version flag (used by doctor checks)
if [[ "$1" == "--version" ]]; then
    echo "claude mock 1.0.0 (test)"
    exit 0
fi

# Handle -p flag — the prompt text is the next argument
if [[ "$1" != "-p" ]]; then
    echo "mock_claude: unknown flag $1" >&2
    exit 1
fi

PROMPT_TEXT="$2"

# Pattern match on prompt content to determine which prompt is being called.
# The prompt text contains the full content of the .md file with placeholders filled in.

# --- prd_fetch_meta ---
if echo "$PROMPT_TEXT" | grep -q "prd_fetch_meta\|Fetch.*metadata\|modifiedTime.*modified_time\|fetch only metadata"; then
    # Extract OUTPUT_PATH from the prompt (look for a path to write JSON to)
    OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*_prd_meta\.json' | head -1)
    if [[ -n "$OUTPUT_PATH" ]]; then
        mkdir -p "$(dirname "$OUTPUT_PATH")"
        cat > "$OUTPUT_PATH" << 'METAJSON'
{"modified_time": "2026-03-20T10:00:00Z"}
METAJSON
    fi
    echo '{"modified_time": "2026-03-20T10:00:00Z"}'
    exit 0
fi

# --- prd_fetch_content ---
if echo "$PROMPT_TEXT" | grep -q "prd_fetch_content\|Fetch full document\|CONTENT_OUTPUT_PATH\|full document content"; then
    # Extract output paths
    CONTENT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*_prd_raw\.txt' | head -1)
    COMMENTS_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*_prd_comments_raw\.json' | head -1)
    if [[ -n "$CONTENT_PATH" ]]; then
        mkdir -p "$(dirname "$CONTENT_PATH")"
        cat > "$CONTENT_PATH" << 'PRDTXT'
# Product Requirements Document

## Overview
This is a sample PRD for testing.

## User Stories

| ID | User Story | Priority |
|----|-----------|----------|
| 1 | As a user, I want to log in using OAuth2 so that I don't need a separate password. | High |
| 1.1 | As a user, I want to enable 2FA via an authenticator app for enhanced security. | Medium |
| 1.2 | As a user, I want to reset my password via email link. | Medium |
| 2 | As a user, I want to see my live P&L in the portfolio view updated every 30 seconds. | High |
| 2.1 | As a user, I want to switch chart time periods (1D, 1W, 1M, 3M, 1Y, ALL). | Medium |

## Technical Notes
This section should be ignored by the extractor.

| Ref | Note |
|-----|------|
| TN-1 | Use WebSocket for real-time data |
PRDTXT
    fi
    if [[ -n "$COMMENTS_PATH" ]]; then
        mkdir -p "$(dirname "$COMMENTS_PATH")"
        cat > "$COMMENTS_PATH" << 'COMMENTSJSON'
[
  {
    "anchor_text": "see my live P&L",
    "author": "Ashwini",
    "date": "2026-03-10T09:00:00Z",
    "comment_text": "Descoped for V1"
  },
  {
    "anchor_text": "see my live P&L",
    "author": "Sam",
    "date": "2026-03-15T09:00:00Z",
    "comment_text": "Reinstate, confirmed V1"
  }
]
COMMENTSJSON
    fi
    echo "Content and comments written."
    exit 0
fi

# --- prd_extract ---
if echo "$PROMPT_TEXT" | grep -q "prd_extract\|User Stories.*table rows\|extract.*user stor\|IDENTIFIER_COLUMN_NAMES"; then
    OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*_prd_features_[0-9-]+\.json' | head -1)
    if [[ -z "$OUTPUT_PATH" ]]; then
        OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*features[^ ]*\.json' | head -1)
    fi
    FEATURES='[
  {
    "source_id": "PRD:1",
    "identifier": "1",
    "feature_name": "User login with OAuth2",
    "description": "Users can log in using Google or Microsoft OAuth2 providers.",
    "source_text": "As a user, I want to log in using OAuth2 so that I don'\''t need a separate password.",
    "prd_comments": "",
    "latest_comment_decision": "",
    "skipped_rows": []
  },
  {
    "source_id": "PRD:1.1",
    "identifier": "1.1",
    "feature_name": "Two-factor authentication",
    "description": "Optional 2FA via authenticator app for enhanced security.",
    "source_text": "As a user, I want to enable 2FA via an authenticator app for enhanced security.",
    "prd_comments": "",
    "latest_comment_decision": "",
    "skipped_rows": []
  },
  {
    "source_id": "PRD:1.2",
    "identifier": "1.2",
    "feature_name": "Password reset via email",
    "description": "Users can reset their password via an email link.",
    "source_text": "As a user, I want to reset my password via email link.",
    "prd_comments": "",
    "latest_comment_decision": "",
    "skipped_rows": []
  },
  {
    "source_id": "PRD:2",
    "identifier": "2",
    "feature_name": "Real-time P&L display",
    "description": "Users can see their live profit and loss in the portfolio view, updated every 30 seconds.",
    "source_text": "As a user, I want to see my live P&L in the portfolio view updated every 30 seconds.",
    "prd_comments": "[2026-03-10 Ashwini]: Descoped for V1. [2026-03-15 Sam]: Reinstate, confirmed V1.",
    "latest_comment_decision": "In Scope",
    "skipped_rows": []
  },
  {
    "source_id": "PRD:2.1",
    "identifier": "2.1",
    "feature_name": "Chart switching between time periods",
    "description": "Users can switch between 1D, 1W, 1M, 3M, 1Y, and ALL time periods on any chart.",
    "source_text": "As a user, I want to switch chart time periods (1D, 1W, 1M, 3M, 1Y, ALL).",
    "prd_comments": "",
    "latest_comment_decision": "",
    "skipped_rows": []
  }
]'
    if [[ -n "$OUTPUT_PATH" ]]; then
        mkdir -p "$(dirname "$OUTPUT_PATH")"
        echo "$FEATURES" > "$OUTPUT_PATH"
    fi
    echo "$FEATURES"
    exit 0
fi

# --- slack_fetch ---
if echo "$PROMPT_TEXT" | grep -q "slack_fetch\|Fetch new Slack messages\|WATERMARK_TS\|fetch.*messages.*after.*watermark"; then
    OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*_slack_raw\.json' | head -1)
    if [[ -z "$OUTPUT_PATH" ]]; then
        OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*conflict_reply[^ ]*\.json' | head -1)
    fi
    SLACK_DATA='{
  "new_message_count": 0,
  "threads": []
}'
    if [[ -n "$OUTPUT_PATH" ]]; then
        mkdir -p "$(dirname "$OUTPUT_PATH")"
        echo "$SLACK_DATA" > "$OUTPUT_PATH"
    fi
    echo "$SLACK_DATA"
    exit 0
fi

# --- slack_classify ---
if echo "$PROMPT_TEXT" | grep -q "slack_classify\|Classify scope-relevant\|classify.*scope"; then
    OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*_slack_items_[0-9-]+\.json' | head -1)
    if [[ -z "$OUTPUT_PATH" ]]; then
        OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*slack_items[^ ]*\.json' | head -1)
    fi
    ITEMS='[]'
    if [[ -n "$OUTPUT_PATH" ]]; then
        mkdir -p "$(dirname "$OUTPUT_PATH")"
        echo "$ITEMS" > "$OUTPUT_PATH"
    fi
    echo "$ITEMS"
    exit 0
fi

# --- slack_match ---
if echo "$PROMPT_TEXT" | grep -q "slack_match\|Semantically match\|semantic.*match"; then
    OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*match[^ ]*\.json' | head -1)
    MATCH='{"match_found": false, "confidence": "low", "reasoning": "No match found in test mode."}'
    if [[ -n "$OUTPUT_PATH" ]]; then
        mkdir -p "$(dirname "$OUTPUT_PATH")"
        echo "$MATCH" > "$OUTPUT_PATH"
    fi
    echo "$MATCH"
    exit 0
fi

# --- conflict_resolve ---
if echo "$PROMPT_TEXT" | grep -q "conflict_resolve\|Parse.*reply.*resolution\|determine.*conflict.*resolution"; then
    OUTPUT_PATH=$(echo "$PROMPT_TEXT" | grep -oE '/[^ ]*resolve[^ ]*\.json' | head -1)
    RESOLVE='{"resolved": false}'
    if [[ -n "$OUTPUT_PATH" ]]; then
        mkdir -p "$(dirname "$OUTPUT_PATH")"
        echo "$RESOLVE" > "$OUTPUT_PATH"
    fi
    echo "$RESOLVE"
    exit 0
fi

# --- slack_report ---
if echo "$PROMPT_TEXT" | grep -q "slack_report\|Post run.*report\|Scope Tracker.*report\|REPORTING_CHANNEL"; then
    echo "Report posted to Slack (mock)."
    exit 0
fi

# Fallback — unknown prompt, output empty JSON
echo '{}' >&2
echo "mock_claude: unrecognized prompt pattern" >&2
exit 0
