# Architecture

## Pipeline Overview

scope-tracker uses a multi-step pipeline orchestrated by `run_pipeline.py`.
Each step is either a deterministic Python script or an LLM call via `claude -p`.
Data fetching (Confluence, Slack, Google Sheets) uses direct API calls — LLM is reserved for semantic tasks only.

## Diff Scripts

These scripts gate whether downstream processing is needed by checking if source data has changed.

### `diff_prd.py`

**Purpose:** Check if the PRD document has been modified since the last run.

**Inputs:**
- `--project-dir` — path to the project directory (e.g. `scope-tracker/scalper/`)
- `--config` — path to `scope_tracker_config.json`
- `--project` — project name

**Logic (Confluence source — direct API):**
1. Read `prd_source` from config for the given project.
2. If `type: none` → return `{"status": "not configured"}`.
3. Load Confluence credentials from `.mcp.json`.
4. Call `confluence_client.fetch_page_metadata()` to get `modifiedTime`.
5. Compare to `run_state.prd.last_modified`.
6. If unchanged → return `{"status": "skipped (unchanged)"}`.
7. If changed → call `confluence_client.fetch_page_content()` and `fetch_page_comments()`.
8. Write raw content to `system/{name}_prd_raw.txt`.
9. Write inline comments to `system/{name}_prd_comments_raw.json`.
10. Return `{"status": "changed", "last_modified": "...", "raw_path": "...", "comments_path": "..."}`.

**Logic (Google Drive source — LLM via MCP):**
1–2. Same as above.
3. Call `claude -p prompts/prd_fetch_meta.md` to get `modifiedTime` via MCP.
4–9. Same pattern, using `call_llm(prd_fetch_content.md)`.

**Skip condition:** `modifiedTime` matches stored value in `run_state.json`.

### `diff_slack.py`

**Purpose:** Check if new Slack messages exist after the watermark timestamp.

**Inputs:**
- `--project-dir` — path to the project directory
- `--config` — path to `scope_tracker_config.json`
- `--project` — project name

**Logic (direct Slack API):**
1. Read `slack_channel` and `slack_last_run_timestamp` from config/run_state.
2. Load `SLACK_BOT_TOKEN` from `.mcp.json`.
3. Call `slack_client.resolve_channel_id()` to get channel ID from name.
4. Call `slack_client.fetch_channel_history()` with channel ID and watermark.
5. For seen threads, call `slack_client.fetch_thread_replies()` to check for new replies.
6. If no new messages → return `{"status": "skipped (no new messages)"}`.
7. If new messages → write to `system/{name}_slack_raw.json`.
8. Return `{"status": "changed", "new_message_count": N, "raw_path": "..."}`.

**Skip condition:** `fetch_channel_history()` returns 0 messages after the watermark timestamp.

## Direct API Clients

### `confluence_client.py`

**Purpose:** Fetch Confluence page metadata, content, and inline comments via REST API.

**Functions:**

| Function | What it does |
|---|---|
| `get_page_id_from_url(url)` | Extracts page ID from a Confluence URL |
| `fetch_page_metadata(site_name, email, api_token, page_id)` | Returns `{"modified_time": "ISO8601"}` |
| `fetch_page_content(site_name, email, api_token, page_id)` | Returns plain text (HTML stripped) |
| `fetch_page_comments(site_name, email, api_token, page_id)` | Returns list of `{anchor_text, author, date, comment_text}` |
| `load_confluence_credentials(mcp_json_path)` | Loads credentials from `.mcp.json` |

**API endpoints:**
- Metadata: `GET /wiki/api/v2/pages/{id}?include=version`
- Content: `GET /wiki/api/v2/pages/{id}?body-format=storage` → strip HTML to plain text
- Comments: `GET /wiki/api/v2/pages/{id}/inline-comments`

**Credentials:** Read from `.mcp.json` (`ATLASSIAN_SITE_NAME`, `ATLASSIAN_USER_EMAIL`, `ATLASSIAN_API_TOKEN`).

### `slack_client.py`

**Purpose:** Fetch Slack channel history and thread replies via Web API.

**Functions:**

| Function | What it does |
|---|---|
| `resolve_channel_id(bot_token, channel_name)` | Resolves channel name to ID via `conversations.list` |
| `fetch_channel_history(bot_token, channel_id, oldest_ts)` | Returns messages after timestamp (paginated) |
| `fetch_thread_replies(bot_token, channel_id, thread_ts)` | Returns all replies in a thread (paginated) |
| `load_slack_credentials(mcp_json_path)` | Loads `SLACK_BOT_TOKEN` from `.mcp.json` |

**API endpoints:**
- History: `POST https://slack.com/api/conversations.history`
- Replies: `POST https://slack.com/api/conversations.replies`
- Channel lookup: `POST https://slack.com/api/conversations.list`

**Credentials:** `SLACK_BOT_TOKEN` from `.mcp.json`.

## Pure Python Replacements

### `prd_parser.py`

**Purpose:** Deterministic PRD feature extraction — replaces the LLM-based `prd_extract.md` prompt.

**Function:**
```python
extract_features(raw_text, comments, identifier_col_names, story_col_names) -> list[dict]
```

**Logic:**
1. Find "User Stories" section heading (case-insensitive regex).
2. Parse all pipe-delimited markdown tables within that section.
3. Match header columns against `identifier_col_names` and `story_col_names` (case-insensitive).
4. Filter rows by identifier regex: `^\d+(\.\d+)*$`.
5. Build feature dicts: `source_id`, `identifier`, `feature_name` (truncated 80 chars), `description`, `source_text`.
6. Attach comments by matching `anchor_text` to story text.
7. Derive `latest_comment_decision` from most recent comment keywords.
8. Return list of feature dicts + `skipped_rows` in first element.

### `slack_reporter.py`

**Purpose:** Build and post Slack run reports — replaces the LLM-based `slack_report.md` prompt.

**Functions:**

| Function | What it does |
|---|---|
| `build_report(project_name, run_datetime, steps_executed, run_summary, pending_conflicts)` | Returns formatted Slack mrkdwn message string |
| `post_report(bot_token, channel_id, report_text)` | Posts message to Slack via `chat.postMessage` API |

**Report format:** Header with project name and date, code block with PRD/Slack/Sheet/Steps summary, optional "Awaiting Your Input" section for pending conflicts.

## State Management

### `update_state.py`

**Purpose:** Persist run metadata to `run_state.json` after each pipeline run.

**Inputs:**
- `--project-dir` — path to the project directory
- `--config` — path to `scope_tracker_config.json`
- `--project` — project name
- `--updates-file` — path to JSON file containing updates to merge

**Logic:**
Deep-merges updates into existing `run_state.json` with special handling for:
- `prd.*` — shallow merge (update individual fields, preserve others)
- `slack.seen_thread_ids` — set-union append (never removes existing IDs)
- `slack.last_run_timestamp` — overwrite
- `conflicts` — merge by `id` field (update existing, add new)
- `sheet.*` — shallow merge
- Top-level fields (`run_count`, `last_run_date`) — overwrite

**Output:** Updated `run_state.json` in `system/` directory.

## Helper Modules

### `call_llm.py`

**Purpose:** Shared helper for invoking `claude -p` with prompt templates. Used only for semantic LLM tasks (classification, matching, conflict interpretation).

**Interface:**
```python
call_llm(prompt_file: str, placeholders: dict, cwd: str, timeout: int = 300) -> str
```

- Reads the prompt `.md` file
- Replaces `{{KEY}}` placeholders with values from the dict
- Runs `claude -p` as a subprocess in the given `cwd` (which must contain `.mcp.json`)
- Returns stdout on success
- Raises `RuntimeError` on non-zero exit or timeout

## Google Sheets Direct API

### `google_sheets.py`

**Purpose:** Direct Google Sheets API access using OAuth2. Replaces all LLM-based sheet operations.

**Authentication:** OAuth2 "installed app" flow.
- First run: reads `client_secret.json`, opens browser for consent, saves `token.json`
- Subsequent runs: uses saved refresh token (auto-refreshes if expired)
- Scope: `https://www.googleapis.com/auth/spreadsheets`

**Functions:**

| Function | What it does |
|---|---|
| `authenticate(client_secret_path, token_dir)` | OAuth2 auth flow, returns Credentials |
| `get_sheets_service(client_secret_path, token_path)` | Convenience wrapper, returns (service, creds) |
| `create_spreadsheet(creds, title, headers, rows, ...)` | Creates new spreadsheet with data + formatting |
| `read_spreadsheet(creds, spreadsheet_id)` | Reads all rows from Sheet1 |
| `update_spreadsheet(creds, spreadsheet_id, changes, ...)` | Batch apply add/update/update_cell changes |

**Formatting:** All formatting (column widths, frozen rows/cols, band colors, bold headers, text wrapping, borders, band separators, dropdowns, conditional formatting) is applied via a single `batchUpdate` call for efficiency.

## Sheet Manager

### `sheet_manager.py`

**Purpose:** All Google Sheet operations — create, update, format, compute Effective Status, detect conflicts. Uses `google_sheets.py` for direct API access (no LLM calls for sheet operations).

**Arguments:**
- `--project-dir` — path to the project directory
- `--config` — path to `scope_tracker_config.json`
- `--project` — project name
- `--operation` — `create` or `update`
- `--prd-features` — path to PRD features JSON (optional)
- `--slack-items` — path to Slack items JSON (optional)

**Operations:**

| Operation | What it does |
|---|---|
| `create` | Creates a new Google Sheet, populates with PRD features, applies full formatting |
| `update` | Reads current sheet, processes PRD/Slack items, adds/updates rows, detects conflicts |

**Column Layout (4 bands):**

| Band | Background | Columns |
|---|---|---|
| Identity (`#E8F0FE`) | Light steel blue | #, Feature Name, Description |
| Source (`#E6F4EA`) | Light teal | Source, Source ID, Source Text, PRD Section, PRD Comments |
| Scope (`#EDE7F6`) | Light lavender | Scope Decision, Target Version, Conflict Resolution, Added Run, Last Updated |
| UAT (`#FFF8E1`) | Warm cream | UAT #1–#N Status/Notes, Effective Status (`#FFE082`), Blocker?, Tester, Test Date |

**Column ownership:**
- Tool-owned: #, Feature Name, Description, Source, Source ID, Source Text, PRD Section, PRD Comments, Scope Decision (initial), Target Version (initial), Conflict Resolution, Added Run, Last Updated, Effective Status
- User-owned: All UAT # Status/Notes columns, Blocker?, Tester, Test Date
- `update_row()` never modifies user-owned columns

**Formatting rules:**
- Header row: frozen, bold, 32px height, centered
- Frozen columns: first 3 (#, Feature Name, Description)
- Data row height: 24px
- Text wrapping: Description, Source Text, PRD Comments, all Notes columns
- Borders: thin light grey (`#E0E0E0`) between all cells
- Band separators: medium grey (`#BDBDBD`) between bands
- Dropdowns: Scope Decision, Target Version, all UAT Status columns, Blocker? (rows 2–1000)

**Conditional formatting:**
- Effective Status = Passed → green (`#C8E6C9`)
- Effective Status = Failed → red (`#FFCDD2`)
- Effective Status = Blocked → orange (`#FFE0B2`)
- Effective Status = Passed with iteration → yellow-green (`#F0F4C3`)
- Scope Decision = Active Blocker → red bold text
- Scope Decision = Conflicting Signal → orange bold text
- Blocker? = Yes → red text

**Effective Status computation:**
```
For each row:
  For i in range(uat_rounds, 0, -1):
    value = row["UAT #{i} Status"]
    if value is not empty and value != "To be tested":
      return value
  return "To be tested"
```

**Conflict detection:**
- Compare each item's scope decision against the sheet row's Scope Decision
- If different and Conflict Resolution is empty → new conflict
- If Conflict Resolution has a value and source text unchanged → suppressed
- If Conflict Resolution has a value but source text changed → re-raised

**Output:** JSON with `{status, rows_added, rows_updated, conflicts_detected}`.

## Conflict Manager

### `conflict_manager.py`

**Purpose:** Read the scope-tracker Slack channel for replies to conflict messages. Apply resolutions to sheet and run_state.

**Arguments:**
- `--project-dir` — path to the project directory
- `--config` — path to `scope_tracker_config.json`
- `--project` — project name

**Logic:**
1. Read `conflicts` array from `run_state.json` where `resolved: false`.
2. If empty → return `{"status": "no pending conflicts"}`.
3. Load Slack credentials from `.mcp.json`.
4. For each unresolved conflict: call `slack_client.fetch_thread_replies()` to check for replies (direct API).
5. If reply found: call `call_llm(conflict_resolve.md)` to parse the resolution (LLM needed for semantic interpretation).
6. Apply resolution: write to Conflict Resolution column, update Scope Decision, mark resolved in run_state.
7. Return `{"status": "ok", "resolved_count": N, "pending_count": N}`.

**Output:** JSON with conflict resolution summary.

## Pipeline Orchestrator

### `run_pipeline.py`

**Purpose:** Outer orchestrator that runs all pipeline steps in order for a single project.

**Arguments:**
- `--project-dir` — path to the project directory
- `--config` — path to `scope_tracker_config.json`
- `--project` — project name
- `--dry-run` — skip sheet writes and Slack post
- `--verbose` — print step-by-step progress with timing

**Step sequence:**

| Step | Name | Type | Condition | Script/Module |
|---|---|---|---|---|
| 0 | Conflict Resolution | Python (direct Slack API + LLM) | Always runs | `conflict_manager.py` |
| 1 (a+b) | Source Diff Checks | Python (direct API) (parallel) | Always runs | `diff_prd.py` + `diff_slack.py` via `ThreadPoolExecutor` |
| 2a | PRD Extraction | Python (pure) | Only if `diff_prd` returned "changed" | `prd_parser.extract_features()` |
| 2b | Slack Classification | LLM call | Only if `diff_slack` returned "changed" | `claude -p slack_classify.md` |
| 3 | Sheet Update | Python (direct Google Sheets API) | Always runs (skipped in dry-run) | `sheet_manager.py --operation update` |
| 4 | State Update | Python script | Always runs | `update_state.py` |
| 5 | Slack Report | Python (direct Slack API) | Always runs (skipped in dry-run) | `slack_reporter.build_report()` + `post_report()` |

**Total steps:** 6 (steps 1a+1b count as one parallel step, steps 2a+2b count as one extraction step).

**`steps_executed` counter:** Incremented after each logical step (0, 1, 2, 3, 4, 5) regardless of whether sub-steps were skipped. Written to `system/{name}_steps_executed.json` after every step.

**Dry-run mode:** Steps 3 (sheet update) and 5 (Slack report) are skipped. All other steps execute normally. The summary is printed to stderr instead.

## LLM vs Direct API Split

After Group 11, the tool uses LLM calls **only for 3 semantic tasks**. Everything else is deterministic Python:

| Task | Method | Reason |
|---|---|---|
| Confluence metadata/content/comments | Direct REST API (`confluence_client.py`) | Deterministic fetch |
| Slack channel history/thread replies | Direct Slack API (`slack_client.py`) | Deterministic fetch |
| Google Sheet create/read/update | Direct Sheets API (`google_sheets.py`) | Deterministic CRUD |
| PRD feature extraction | Python (`prd_parser.py`) | Deterministic table parsing |
| Slack report posting | Python (`slack_reporter.py`) + Direct Slack API | Deterministic template formatting |
| Slack classification | **LLM** (`slack_classify.md`) | Semantic classification |
| Slack-to-sheet matching | **LLM** (`slack_match.md`) | Semantic matching |
| Conflict resolution parsing | **LLM** (`conflict_resolve.md`) | Semantic interpretation |
| Google Drive metadata/content | LLM via MCP (`prd_fetch_meta.md`, `prd_fetch_content.md`) | Requires GDrive MCP (no direct API yet) |

## Runner Module

### `runner.py`

**Purpose:** Bridge between the CLI layer and `run_pipeline.py`. Loads config, resolves paths, and orchestrates pipeline execution across projects.

**Functions:**

| Function | What it does |
|---|---|
| `run_project(project, config, base_path, dry_run, verbose)` | Resolves paths for a single project and calls `run_pipeline.run()` directly. Returns the pipeline summary dict. |
| `run_all(config_path, project_filter, dry_run, verbose)` | Reads config, filters to enabled projects, calls `run_project` for each, and collects results. Errors are captured per-project, not raised. |

## CLI Layer

### `cli.py`

**Purpose:** Click-based CLI providing all user-facing commands.

**Commands:**

| Command | What it does |
|---|---|
| `init` | Checks dependencies, scaffolds directories, runs MCP wizards, writes config files |
| `add` | Interactive project setup wizard, appends to existing config |
| `init-sheet` | Forces PRD read, extracts features, creates Google Sheet via `sheet_manager.py` |
| `run` | Calls `runner.run_all()`, prints summary table with Rich |
| `status` | Reads `run_state.json` and `steps_executed.json` per project, prints status table |
| `doctor` | Checks dependencies, `.mcp.json` keys, project folders, run_state validity, sheet_url |

### `installer.py`

**Purpose:** Dependency checks, directory scaffolding, MCP credential wizards, and config file generation.

**Functions:**

| Function | What it does |
|---|---|
| `check_dependencies()` | Verifies python3 >= 3.10, claude CLI, git, node/npx. Prints Rich table, exits on failure. |
| `scaffold_directories(base_path)` | Creates `scope-tracker/` with scripts/ and prompts/ copied from installed package. |
| `run_slack_mcp_wizard()` | Collects Slack Bot Token and Team ID interactively. |
| `run_gdrive_mcp_wizard()` | Collects Google credentials JSON path, validates file. |
| `run_confluence_mcp_wizard()` | Collects Confluence URL, username, and API token. |
| `write_mcp_config(base_path, mcp_config)` | Writes `.mcp.json` with configured MCP servers. |
| `run_project_wizard(existing_mcp_servers)` | Interactive project setup: name, channel, PRD source. |
| `run_google_sheets_wizard()` | Collects Google OAuth2 client_secret.json path, validates file. |
| `write_config(base_path, config)` | Writes `scope_tracker_config.json`. |
| `load_config(config_path)` | Reads and parses config from disk. |

## Self-Healing Dependency Management

`dependency_manager.py` provides automatic resolution of fixable setup issues.

### `ensure_python_deps()`

On every CLI invocation, checks that all required Python packages are importable. If any are missing, runs `pip install` automatically and logs what was installed to stderr. If pip fails, prints the exact command the user should run manually.

### `ensure_directories(st_dir, project_names)`

Creates missing `scripts/`, `prompts/`, and per-project `system/`/`outputs/` directories.

### `ensure_google_oauth_token(config, st_dir)`

Checks for a valid Google OAuth `token.json`. If missing or expired, automatically triggers the browser consent flow or refreshes the token. Never shows cryptic errors — always provides a clear message.

### `doctor --fix`

The `doctor` command identifies auto-fixable issues (missing packages, missing directories, missing OAuth token) and marks them as "Fixable". Running `scope-tracker doctor --fix` auto-resolves them. Manual-only issues (missing API tokens, missing binaries) show clear instructions.

### `init` — client_secret.json copy

During `scope-tracker init`, the `client_secret.json` file is copied into the scope-tracker directory (not just referenced by path) so the setup is self-contained.

---

## Prompt Files

All prompt files live in `prompts/` and are invoked via `call_llm()` with `{{PLACEHOLDER}}` substitution.

| File | Purpose | MCP needed | Placeholders | Output format |
|---|---|---|---|---|
| `prd_fetch_meta.md` | Fetch document last-modified timestamp only (Google Drive only) | gdrive | `DOC_URL`, `SOURCE_TYPE`, `OUTPUT_PATH` | JSON file: `{"modified_time": "..."}` |
| `prd_fetch_content.md` | Fetch full document text and inline comments (Google Drive only) | gdrive | `DOC_URL`, `SOURCE_TYPE`, `CONTENT_OUTPUT_PATH`, `COMMENTS_OUTPUT_PATH` | Plain text file + JSON comment array |
| `prd_extract.md` | *(Deprecated — replaced by `prd_parser.py`)* | None | `RAW_CONTENT_PATH`, `COMMENTS_RAW_PATH`, `OUTPUT_PATH`, `IDENTIFIER_COLUMN_NAMES`, `STORY_COLUMN_NAMES` | JSON array of feature objects |
| `slack_fetch.md` | *(Deprecated — replaced by `slack_client.py`)* | Slack | `CHANNEL`, `WATERMARK_TS`, `SEEN_THREAD_IDS`, `OUTPUT_PATH` | JSON file with threads and messages |
| `slack_classify.md` | Classify scope-relevant threads from raw Slack data | None (file in/out) | `RAW_SLACK_PATH`, `OUTPUT_PATH` | JSON array of classified scope items |
| `slack_match.md` | Semantically match one Slack item to existing sheet rows | None | `SLACK_ITEM_JSON`, `EXISTING_ROWS_JSON`, `OUTPUT_PATH` | JSON with match result and confidence |
| `conflict_resolve.md` | Parse user's Slack reply to determine conflict resolution | None | `CONFLICT_JSON`, `REPLY_TEXT`, `OUTPUT_PATH` | JSON with resolution details |
| `slack_report.md` | *(Deprecated — replaced by `slack_reporter.py`)* | Slack | `REPORTING_CHANNEL`, `STEPS_EXECUTED_PATH`, `RUN_SUMMARY_JSON`, `PENDING_CONFLICTS_JSON`, `PROJECT_NAME`, `RUN_DATETIME` | Posts Slack message (no file output) |
