# TASKS.md — Execution Tracker

**Protocol:** Read CLAUDE.md before starting any group.
Execute one group per session. Update each task status as you go.
After all tasks in a group are DONE, update the group status, then STOP and confirm.

**Status key:** `PENDING` | `IN PROGRESS` | `DONE` | `BLOCKED`

---

## Group 1 — Repo Scaffold and Package Structure
**Status: DONE**
**Req ref:** Sections 9, 11
**Goal:** A valid, installable Python package. No logic yet — skeleton only.
Running `pip install -e .` and `scope-tracker --help` must work before this group is done.

| # | Task | Status |
|---|---|---|
| 1.1 | `git init`. Create `src/scope_tracker/`, `src/scope_tracker/scripts/`, `src/scope_tracker/prompts/`, `tests/`, `tests/fixtures/`, `docs/` directories | DONE |
| 1.2 | Write `pyproject.toml` exactly as specified in Section 11. Entry point: `scope-tracker = "scope_tracker.cli:main"` | DONE |
| 1.3 | Write `src/scope_tracker/__init__.py` with `__version__ = "1.0.0"` | DONE |
| 1.4 | Write `src/scope_tracker/cli.py` — `click` group with five stub commands: `init`, `add`, `init-sheet`, `run`, `status`, `doctor`. Each prints "not yet implemented." Uses `rich` for output. | DONE |
| 1.5 | Write `src/scope_tracker/installer.py` — empty module, docstring only | DONE |
| 1.6 | Write `src/scope_tracker/runner.py` — empty module, docstring only | DONE |
| 1.7 | Add `.gitkeep` to `src/scope_tracker/scripts/` and `src/scope_tracker/prompts/` | DONE |
| 1.8 | Write `tests/conftest.py` — empty, with `import pytest` | DONE |
| 1.9 | Write `.gitignore`: `.mcp.json`, `*.xlsx`, `outputs/`, `system/`, `__pycache__/`, `*.pyc`, `.env`, `dist/`, `*.egg-info/`, `credentials.json`, `.venv/` | DONE |
| 1.10 | Run `pip install -e .` and verify `scope-tracker --help` shows all six commands | DONE |
| 1.11 | Write `README.md` skeleton: title, one-line description, install command (`pip install git+https://github.com/{owner}/scope-tracker.git`), all six CLI commands listed with one-line descriptions | DONE |

---

## Group 2 — Pipeline Scripts: Diffs and State
**Status: DONE**
**Req ref:** Sections 7.1, 7.2, 7.5, 6.3
**Goal:** `diff_prd.py`, `diff_slack.py`, and `update_state.py` written and tested.
These are the "did anything change?" gatekeepers. All output is JSON on stdout.

| # | Task | Status |
|---|---|---|
| 2.1 | Write `src/scope_tracker/scripts/diff_prd.py`. Args: `--project-dir`, `--config`, `--project`. Logic: read `prd_source` from config; if `type: none` return not-configured JSON; call `call_llm(prd_fetch_meta.md)` to get `modified_time`; compare to `run_state.prd.last_modified`; if unchanged return skipped JSON; if changed call `call_llm(prd_fetch_content.md)` to write `{name}_prd_raw.txt` and `{name}_prd_comments_raw.json`; return changed JSON with paths. All stdout is JSON. Logs to stderr. | DONE |
| 2.2 | Write `src/scope_tracker/scripts/diff_slack.py`. Args: `--project-dir`, `--config`, `--project`. Logic: read `slack_channel` and `slack_last_run_timestamp` from config; call `call_llm(slack_fetch.md)` with CHANNEL, WATERMARK_TS, SEEN_THREAD_IDS; if no new messages return skipped JSON; else write `{name}_slack_raw.json` and return changed JSON with message count and path. | DONE |
| 2.3 | Write `src/scope_tracker/scripts/update_state.py`. Args: `--project-dir`, `--config`, `--project`, `--updates-file`. Reads updates JSON, deep-merges into run_state.json. Handles `prd.last_modified`, `slack.last_run_timestamp`, `slack.seen_thread_ids` (append, no overwrite), `conflicts` (merge by id), `sheet.last_row_number`. Writes updated run_state.json. | DONE |
| 2.4 | Write `src/scope_tracker/scripts/call_llm.py` — a standalone helper module (not a script) that implements `call_llm(prompt_file, placeholders, cwd, timeout=300)` exactly as specified in Section 7.6. Import this in all scripts that need it. Raises `RuntimeError` with stderr snippet on failure. | DONE |
| 2.5 | Write `tests/fixtures/sample_run_state.json` — realistic fixture: prd.last_modified set, slack.last_run_timestamp set, one unresolved conflict, sheet.last_row_number = 5 | DONE |
| 2.6 | Write `tests/fixtures/sample_config.json` — one project "demo" with google-drive PRD source, slack channel, sheet_url, all sheet_config options populated with defaults | DONE |
| 2.7 | Write `tests/test_diff_prd.py`: (a) mtime unchanged → returns skipped; (b) mtime changed → calls prd_fetch_content, writes files, returns changed; (c) type none → returns not-configured. Mock `call_llm`. | DONE |
| 2.8 | Write `tests/test_diff_slack.py`: (a) no new messages → returns skipped; (b) new messages → writes raw file, returns changed. Mock `call_llm`. | DONE |
| 2.9 | All tests pass (`pytest tests/test_diff_prd.py tests/test_diff_slack.py`) | DONE |
| 2.10 | Update `docs/architecture.md`: add diff scripts section describing each script's logic, inputs, outputs, and skip conditions | DONE |

---

## Group 3 — LLM Prompt Files
**Status: DONE**
**Req ref:** Section 8 (all subsections)
**Goal:** All 8 prompt files written with exact placeholder names, output format specs,
and all rules from REQUIREMENTS.md embedded in the prompt text.

| # | Task | Status |
|---|---|---|
| 3.1 | Write `src/scope_tracker/prompts/prd_fetch_meta.md`. Placeholders: `{{DOC_URL}}`, `{{SOURCE_TYPE}}`, `{{OUTPUT_PATH}}`. Instructs LLM to fetch only metadata (modifiedTime / version.when) and write JSON `{"modified_time": "..."}` to OUTPUT_PATH. | DONE |
| 3.2 | Write `src/scope_tracker/prompts/prd_fetch_content.md`. Placeholders: `{{DOC_URL}}`, `{{SOURCE_TYPE}}`, `{{CONTENT_OUTPUT_PATH}}`, `{{COMMENTS_OUTPUT_PATH}}`. Fetches full doc text and inline comments. Writes plain text to CONTENT_OUTPUT_PATH. Writes comment array JSON (with anchor_text, author, date, comment_text) to COMMENTS_OUTPUT_PATH. | DONE |
| 3.3 | Write `src/scope_tracker/prompts/prd_extract.md`. Placeholders: `{{RAW_CONTENT_PATH}}`, `{{COMMENTS_RAW_PATH}}`, `{{OUTPUT_PATH}}`, `{{IDENTIFIER_COLUMN_NAMES}}`, `{{STORY_COLUMN_NAMES}}`. Rules: only User Stories section; only table rows; only rows where identifier matches `^\d+(\.\d+)*$`; ignore all other columns; match identifier/story columns by header name against config lists; assign source_id as `PRD:{identifier}`; attach comments by matching anchor_text to the row's story text; concatenate multiple comments chronologically; derive latest_comment_decision from most recent comment. Output: JSON array per spec in Section 8.3. | DONE |
| 3.4 | Write `src/scope_tracker/prompts/slack_fetch.md`. Placeholders: `{{CHANNEL}}`, `{{WATERMARK_TS}}`, `{{SEEN_THREAD_IDS}}`, `{{OUTPUT_PATH}}`. Fetches messages after watermark. Re-reads threads in SEEN_THREAD_IDS for new replies. Writes structured JSON per Section 8.4. | DONE |
| 3.5 | Write `src/scope_tracker/prompts/slack_classify.md`. Placeholders: `{{RAW_SLACK_PATH}}`, `{{OUTPUT_PATH}}`. Classifies scope-relevant threads. Rules: only high or medium confidence; verbatim key_messages only (no paraphrase); source_id = `SLACK:{thread_ts}`; skips non-scope threads. Output: JSON array per Section 8.5. | DONE |
| 3.6 | Write `src/scope_tracker/prompts/slack_match.md`. Placeholders: `{{SLACK_ITEM_JSON}}`, `{{EXISTING_ROWS_JSON}}`, `{{OUTPUT_PATH}}`. Semantically matches one Slack item to existing sheet rows. Returns match_found, matched_row_number, confidence, reasoning per Section 8.6. If confidence is low, must set match_found: false. | DONE |
| 3.7 | Write `src/scope_tracker/prompts/conflict_resolve.md`. Placeholders: `{{CONFLICT_JSON}}`, `{{REPLY_TEXT}}`, `{{OUTPUT_PATH}}`. Parses user's Slack reply to determine winning source and resolved value. Output per Section 8.7. | DONE |
| 3.8 | Write `src/scope_tracker/prompts/slack_report.md`. Placeholders: `{{REPORTING_CHANNEL}}`, `{{STEPS_EXECUTED_PATH}}`, `{{RUN_SUMMARY_JSON}}`, `{{PENDING_CONFLICTS_JSON}}`, `{{PROJECT_NAME}}`, `{{RUN_DATETIME}}`. Posts report in exact format from Section 8.8. Rules: omit Awaiting Input section if n=0; each conflict its own bullet; update reporting_slack_last_read in config after posting. | DONE |
| 3.9 | Review all 8 prompt files: verify every `{{PLACEHOLDER}}` referenced in `call_llm()` calls in the scripts exists in the prompt. No undefined placeholders. | DONE |
| 3.10 | Update `docs/architecture.md`: add prompt files table (file, purpose, MCP needed, placeholders, output format) | DONE |

---

## Group 4 — Sheet Manager
**Status: DONE**
**Req ref:** Sections 5 (all subsections), 7.3
**Goal:** `sheet_manager.py` creates and updates the Google Sheet with full formatting,
dropdowns, color bands, conditional formatting, and Effective Status computation.
This is the most complex script — take care to implement every detail in Section 5.

| # | Task | Status |
|---|---|---|
| 4.1 | Write `src/scope_tracker/scripts/sheet_manager.py` — skeleton with `--project-dir`, `--config`, `--project`, `--operation create\|update` args. Import Google Sheets API client. Stub all functions. All stdout JSON. | DONE |
| 4.2 | Implement `create_sheet(service, project_name)` — creates a new Google Sheet via Sheets API, returns sheet_id and URL | DONE |
| 4.3 | Implement `build_headers(config)` — returns ordered list of column names exactly as defined in Section 5.2. Number of UAT columns = `config.sheet_config.uat_rounds * 2` (status + notes per round). Always ends with Effective Status, Blocker, Tester, Test Date. | DONE |
| 4.4 | Implement `apply_formatting(service, sheet_id, config)` — applies ALL formatting from Section 5.3: frozen rows/columns, column widths, row heights, color bands (hex values from Section 5.3), bold headers, text wrapping per column, borders, band separators. Use `batchUpdate` API calls for efficiency. | DONE |
| 4.5 | Implement `apply_dropdowns(service, sheet_id, config)` — adds data validation (dropdown lists) to all dropdown columns for rows 2–1000. Lists read from `config.sheet_config.*_options` at runtime. Columns: Scope Decision, Target Version, all UAT # Status columns, Blocker. | DONE |
| 4.6 | Implement `apply_conditional_formatting(service, sheet_id, config)` — all rules from Section 5.3: Effective Status backgrounds, Active Blocker red text, Conflicting Signal orange text, Blocker=Yes red text. | DONE |
| 4.7 | Implement `add_row(service, sheet_id, item, row_number, run_count, timestamp)` — writes a single new row from a PRD or Slack item dict. Sets all tool-owned columns. Leaves all user-owned columns empty. Source column = "PRD" or "Slack". Source ID = item's source_id. | DONE |
| 4.8 | Implement `update_row(service, sheet_id, row_index, changes)` — updates only the specified cells in a row. Never touches user-owned columns. Writes Last Updated timestamp. | DONE |
| 4.9 | Implement `compute_effective_status(row, uat_rounds)` — Python function (not a Sheet formula). Logic: iterate UAT rounds from highest to lowest; return first non-empty, non-"To be tested" value; if all empty or all "To be tested": return "To be tested". Write result to Effective Status column. Run for ALL rows on every update operation. | DONE |
| 4.10 | Implement `read_sheet(service, sheet_id)` — reads all rows into a list of dicts keyed by header name. Used for matching before updates. | DONE |
| 4.11 | Implement `detect_conflicts(new_items, sheet_rows)` — compare each PRD/Slack item's scope_decision against the matching sheet row's Scope Decision. If different and Conflict Resolution column is empty: add to conflicts list. If Conflict Resolution column has a value AND source content has not changed since resolution: skip (suppressed). Return list of new conflicts. | DONE |
| 4.12 | Implement `create` operation end-to-end: create sheet → build headers → write all PRD feature rows → apply formatting → apply dropdowns → apply conditional formatting → compute effective status → write sheet URL to config | DONE |
| 4.13 | Implement `update` operation end-to-end: read sheet → process PRD items (add/update) → process Slack items (add/update/match) → detect conflicts → compute effective status → batch write all changes → apply formatting to new rows | DONE |
| 4.14 | Write `tests/fixtures/sample_prd_features.json` — 5 PRD items covering: new item, unchanged item, item with changed description, item with comment | DONE |
| 4.15 | Write `tests/fixtures/sample_slack_items.json` — 3 Slack items: one matching existing row, one new, one that should trigger conflict | DONE |
| 4.16 | Write `tests/test_sheet_manager.py`: (a) create operation builds correct headers; (b) update adds new rows; (c) update does not modify user-owned columns; (d) effective status computed correctly for all status combinations; (e) conflict detected when Scope Decision differs and no existing resolution; (f) conflict suppressed when resolution exists and source unchanged. Mock Google Sheets API. | DONE |
| 4.17 | All sheet_manager tests pass | DONE |
| 4.18 | Update `docs/architecture.md`: sheet_manager section with column layout table, formatting rules, effective status logic | DONE |

---

## Group 5 — Conflict Manager and Run Pipeline
**Status: DONE**
**Req ref:** Sections 4, 7.4, 7.6
**Goal:** `conflict_manager.py` and `run_pipeline.py` written and tested.
After this group, the full pipeline runs end-to-end (with mocked LLM calls).

| # | Task | Status |
|---|---|---|
| 5.1 | Write `src/scope_tracker/scripts/conflict_manager.py`. Args: `--project-dir`, `--config`, `--project`. Logic: read conflicts from run_state where resolved=false; if none return no-pending JSON; for each: check if slack_message_ts thread has new replies via `call_llm(conflict_resolve.md)`; apply resolution to sheet and run_state; return resolved_count and pending_count JSON. | DONE |
| 5.2 | Write `src/scope_tracker/scripts/run_pipeline.py` exactly per Section 7.6. Steps 0–5 in correct order. Steps 1a+1b parallel via ThreadPoolExecutor. Steps 2a+2b conditional (only if source changed). Steps 3, 4, 5 sequential. `steps_executed` counter incremented after every step. Written to `{name}_steps_executed.json` after each step. `--dry-run` flag supported (skips sheet writes and Slack post, prints to stdout instead). `--verbose` flag supported. | DONE |
| 5.3 | Implement `call_llm()` in `call_llm.py` exactly per spec in Section 7.6 with `{{PLACEHOLDER}}` substitution. All scripts that call `call_llm` must import from this module. | DONE |
| 5.4 | Write `tests/test_conflict_manager.py`: (a) no pending conflicts → returns no-pending; (b) conflict with no reply → returns pending unchanged; (c) conflict with reply → applies resolution to sheet and run_state; (d) resolved conflict not re-raised when source unchanged. Mock `call_llm` and sheet API. | DONE |
| 5.5 | Write `tests/test_run_pipeline.py`: (a) all steps run in correct order; (b) steps 1a+1b run in parallel (use threading verification); (c) step 2a skipped when PRD unchanged; (d) step 2b skipped when no new Slack; (e) steps_executed increments correctly including skipped steps; (f) dry-run does not call sheet_manager update; (g) dry-run does not call slack_report. Mock all subprocess calls. | DONE |
| 5.6 | All pipeline tests pass | DONE |
| 5.7 | Update `docs/architecture.md`: full step table (step number, name, type, condition, script/prompt used) | DONE |

---

## Group 6 — CLI: `init`, `add`, `init-sheet`
**Status: DONE**
**Req ref:** Sections 9 (init, add, init-sheet), 6.2, 10
**Goal:** `scope-tracker init` runs end to end on a fresh directory. All prompts are
clear, all MCP configs are written correctly, all folder structures are created.

| # | Task | Status |
|---|---|---|
| 6.1 | Write `installer.py: check_dependencies()` — checks python3 ≥ 3.10, `claude` binary, `git`, `node`/`npx`. Returns list of `{"tool": name, "found": bool, "message": str, "install_url": str}`. Prints clear pass/fail with `rich`. Stops execution if any required dep missing. | DONE |
| 6.2 | Write `installer.py: scaffold_directories(base_path)` — creates `scope-tracker/` with `scripts/`, `prompts/`, `.gitignore`. Copies all files from `src/scope_tracker/scripts/` and `src/scope_tracker/prompts/` into the right places. Uses `importlib.resources` to locate package files. | DONE |
| 6.3 | Write `installer.py: run_slack_mcp_wizard()` — prompts for SLACK_BOT_TOKEN and SLACK_TEAM_ID. Prints link to api.slack.com/apps. Validates token format (must start with `xoxb-`). Returns dict. | DONE |
| 6.4 | Write `installer.py: run_gdrive_mcp_wizard()` — prompts for credentials JSON file path. Validates file exists and is valid JSON with `client_id` key. Prints instructions for console.cloud.google.com. Returns dict. | DONE |
| 6.5 | Write `installer.py: run_confluence_mcp_wizard()` — prompts for URL, username, API token. Validates URL starts with `https://`. Prints link to id.atlassian.com. Returns dict. | DONE |
| 6.6 | Write `installer.py: write_mcp_config(base_path, mcp_config)` — writes `.mcp.json`. Always includes `slack`. Includes `gdrive` only if any project uses Google Drive. Includes `confluence` only if any project uses Confluence. | DONE |
| 6.7 | Write `installer.py: run_project_wizard(existing_mcp_servers)` — interactive prompts per Section 9 (add command). Returns project config dict. Triggers MCP wizard for new MCP servers needed that aren't already in `.mcp.json`. Validates Google Doc URL format. Validates Confluence URL format. | DONE |
| 6.8 | Write `installer.py: write_config(base_path, config)` — writes `scope_tracker_config.json`. Creates empty `projects` list if none. | DONE |
| 6.9 | Write `installer.py: write_gitignore(base_path)` — writes `.gitignore` with all entries from Section 1.9 | DONE |
| 6.10 | Implement `cli.py init` — calls check_dependencies (stop if any fail) → scaffold_directories → run_slack_mcp_wizard → run_project_wizard → write_mcp_config → write_config → write_gitignore → print success with next steps using `rich` panel | DONE |
| 6.11 | Implement `cli.py add` — loads existing config → run_project_wizard → append project to config → write config → create project folder structure → print confirmation | DONE |
| 6.12 | Implement `cli.py init-sheet --project NAME` — load config → validate project exists and has prd_source → force-run diff_prd.py (ignoring mtime) → run prd_extract → run sheet_manager --operation create → update config with sheet_url → print sheet URL | DONE |
| 6.13 | Write `tests/test_installer.py`: (a) check_dependencies detects missing binary; (b) scaffold creates correct directory tree; (c) write_mcp_config omits gdrive block when not needed; (d) write_config roundtrip; (e) project wizard returns correct dict structure. Mock user input with `click.testing.CliRunner`. | DONE |
| 6.14 | All installer tests pass | DONE |
| 6.15 | Update `README.md` with full install and init walkthrough section | DONE |
| 6.16 | Create `docs/configuration.md` — fully annotated `scope_tracker_config.json` and `.mcp.json` with every field explained, valid values, and examples | DONE |

---

## Group 7 — CLI: `run`, `status`, `doctor` + User Docs
**Status: DONE**
**Req ref:** Sections 9 (run, status, doctor), 12
**Goal:** All CLI commands work. User documentation complete.

| # | Task | Status |
|---|---|---|
| 7.1 | Write `runner.py: run_project(project, config, base_path, dry_run, verbose)` — resolves all paths, calls `run_pipeline.py` via subprocess with correct args, streams output if verbose, parses JSON result, returns summary dict | DONE |
| 7.2 | Write `runner.py: run_all(config_path, project_filter, dry_run, verbose)` — reads config, filters to enabled projects, calls run_project for each, collects results | DONE |
| 7.3 | Implement `cli.py run` — load config → find scope-tracker/ dir → call runner.run_all() → print per-project summary table with `rich` | DONE |
| 7.4 | Implement `cli.py status` — read each project's run_state.json and steps_executed.json → print `rich` table: Project / Last Run / Steps / Sheet Rows / Features / Pending Conflicts | DONE |
| 7.5 | Implement `cli.py doctor` — all checks from Section 9 (doctor command) → print pass/fail per check with `rich` symbols. Failed checks show fix instruction. | DONE |
| 7.6 | Write `tests/test_runner.py`: (a) run_project passes correct args to subprocess; (b) dry-run flag propagated; (c) verbose streams output; (d) failed subprocess raises with clear message. Mock subprocess. | DONE |
| 7.7 | All runner tests pass | DONE |
| 7.8 | Write `docs/user-guide.md` covering exactly what Section 12 specifies: PRD format requirements (exact wording), how to do UAT, how conflicts work, how to add items manually, how to update dropdown options. Plain English for non-technical PMs. | DONE |
| 7.9 | Update `README.md` with `run`, `status`, `doctor` examples including sample output | DONE |
| 7.10 | Final review: `docs/architecture.md` — verify it accurately reflects every script, every step, every prompt | DONE |

---

## Group 8 — End-to-End Test and Release
**Status: DONE**
**Req ref:** All sections
**Goal:** Full dry-run passes. Package installs cleanly from GitHub URL. All tests green.

| # | Task | Status |
|---|---|---|
| 8.1 | Write `tests/fixtures/mock_claude.sh` — fake `claude` binary. Reads `-p` arg, pattern-matches on known prompt types (prd_fetch_meta, prd_extract, slack_classify, etc.), returns hardcoded valid JSON output for each. Exits 0. | DONE |
| 8.2 | Write `tests/fixtures/sample_prd_raw.txt` — realistic plain text PRD with a "User Stories" section containing a table with identifiers 1, 1.1, 1.2, 2, 2.1 and story text. Also includes prose sections and a table in a different section (should be ignored). | DONE |
| 8.3 | Write `tests/test_e2e.py` — integration test using `tmp_path`: (a) runs `scope-tracker init` with mocked input in a temp dir, verifies all files created; (b) runs `scope-tracker run --dry-run` with mock_claude on PATH, verifies steps_executed = 6; (c) verifies `scope-tracker status` outputs correct project name and last run date; (d) verifies `scope-tracker doctor` passes all checks in test environment | DONE |
| 8.4 | Run full test suite: `pytest tests/ -v`. All tests must pass. Fix any failures before marking done. | DONE |
| 8.5 | Push to GitHub. Run `pip install git+https://github.com/{owner}/scope-tracker.git` in a fresh virtual environment. Verify `scope-tracker --help` works. | DONE |
| 8.6 | Final `README.md` review — accurate, no references to old architecture | DONE |
| 8.7 | Final `docs/user-guide.md` review — step-by-step walkthrough tested against actual CLI output | DONE |
| 8.8 | Write `CHANGELOG.md` — v1.0.0 entry listing all features | DONE |
| 8.9 | `git tag v1.0.0` | DONE |

---

## Group 9 — Google Sheets Direct API Integration
**Status: PENDING**
**Req ref:** Section 14.2
**Goal:** Replace all LLM-based Google Sheet operations with direct `google-api-python-client` calls. After this group, `init-sheet` creates a real Google Sheet with full formatting and returns a sheet URL.

| # | Task | Status |
|---|---|---|
| 9.1 | Add `google-auth-oauthlib` to `pyproject.toml` dependencies. Add `token.json` to `.gitignore`. | PENDING |
| 9.2 | Write `src/scope_tracker/scripts/google_sheets.py` — OAuth2 auth flow (`get_sheets_service`): reads `client_secret.json`, handles first-run browser consent, saves/loads `token.json` for refresh. Scopes: `spreadsheets`. | PENDING |
| 9.3 | Implement `google_sheets.create_spreadsheet(service, title, headers, rows)` — creates spreadsheet, writes header + data rows, returns `{"sheet_url", "spreadsheet_id"}` | PENDING |
| 9.4 | Implement `google_sheets.apply_formatting(service, spreadsheet_id, formatting_spec)` — column widths, frozen rows/columns, band colors, bold headers, text wrapping, borders, band separators. Uses `batchUpdate`. | PENDING |
| 9.5 | Implement `google_sheets.apply_dropdowns(service, spreadsheet_id, dropdown_spec)` — data validation for Scope Decision, Target Version, UAT Status, Blocker columns. | PENDING |
| 9.6 | Implement `google_sheets.apply_conditional_formatting(service, spreadsheet_id, cond_format_spec)` — Effective Status backgrounds, Active Blocker red, Conflicting Signal orange, Blocker=Yes red. | PENDING |
| 9.7 | Implement `google_sheets.read_spreadsheet(service, spreadsheet_id)` — read all rows from Sheet1 as list of lists. | PENDING |
| 9.8 | Implement `google_sheets.update_spreadsheet(service, spreadsheet_id, changes, headers)` — batch apply add/update/update_cell changes. | PENDING |
| 9.9 | Update `sheet_manager.py` — remove all `call_llm` usage. Use `google_sheets` module for create, read, update. Add `client_secret_path` and `token_path` parameters. | PENDING |
| 9.10 | Update `cli.py init-sheet` — pass Google credentials paths to sheet_manager. Handle OAuth consent flow (first-run opens browser). | PENDING |
| 9.11 | Update `installer.py init` — prompt for Google `client_secret.json` path during setup. Store path in config under `google_sheets.client_secret_path`. | PENDING |
| 9.12 | Write `tests/test_google_sheets.py` — mock Google API: (a) create returns spreadsheet_id and URL; (b) read returns rows; (c) update applies changes; (d) formatting applies without error. | PENDING |
| 9.13 | All tests pass. Run `scope-tracker init-sheet --project basket-test-slack` and verify sheet URL is returned. | PENDING |
| 9.14 | Update `docs/configuration.md` and `docs/architecture.md` with Google Sheets direct API details. | PENDING |

---

## Group 10 — Confluence and Slack Direct API Clients
**Status: PENDING**
**Req ref:** Sections 14.3, 14.4
**Goal:** Replace LLM-based Confluence and Slack data fetching with direct Python API calls. After this group, `diff_prd.py` (Confluence) and `diff_slack.py` fetch data without any LLM calls.

| # | Task | Status |
|---|---|---|
| 10.1 | Write `src/scope_tracker/scripts/confluence_client.py` — `get_page_id_from_url(url)`, `fetch_page_metadata(site_name, email, token, page_id)`, `fetch_page_content(...)`, `fetch_page_comments(...)`. Uses `requests` with basic auth. Strips HTML from content. | PENDING |
| 10.2 | Write `tests/test_confluence_client.py` — mock `requests`: (a) metadata returns modified_time; (b) content returns plain text; (c) comments returns list of comment dicts; (d) invalid URL raises clear error. | PENDING |
| 10.3 | Update `diff_prd.py` — when `source_type == "confluence"`, use `confluence_client` instead of `call_llm`. Read credentials from `.mcp.json`. Write `_prd_meta.json`, `_prd_raw.txt`, `_prd_comments_raw.json` directly from Python. Keep `call_llm` path for `google-drive` source type (for now). | PENDING |
| 10.4 | Write `src/scope_tracker/scripts/slack_client.py` — `resolve_channel_id(bot_token, channel_name)`, `fetch_channel_history(bot_token, channel_id, oldest_ts)`, `fetch_thread_replies(bot_token, channel_id, thread_ts)`. Uses `requests` to Slack Web API. Handles pagination. | PENDING |
| 10.5 | Write `tests/test_slack_client.py` — mock `requests`: (a) channel history returns messages; (b) thread replies returns replies; (c) channel name resolves to ID; (d) pagination handled. | PENDING |
| 10.6 | Update `diff_slack.py` — use `slack_client` instead of `call_llm(slack_fetch.md)`. Read `SLACK_BOT_TOKEN` from `.mcp.json`. Build raw messages JSON and write `_slack_raw.json` directly from Python. | PENDING |
| 10.7 | Update `conflict_manager.py` — use `slack_client.fetch_thread_replies()` instead of `call_llm(slack_fetch.md)` for reading conflict thread replies. Keep `call_llm(conflict_resolve.md)` for interpreting the reply (LLM needed). | PENDING |
| 10.8 | All tests pass. Run `scope-tracker init-sheet --project basket-test-slack` and verify PRD content is fetched via direct API. | PENDING |
| 10.9 | Update `docs/architecture.md` with direct API client details. | PENDING |

---

## Group 11 — PRD Parser and Slack Reporter (Pure Python)
**Status: PENDING**
**Req ref:** Sections 14.5, 14.6
**Goal:** Replace LLM-based PRD extraction and Slack report formatting with pure Python. After this group, the only `call_llm` usages remaining are the 3 semantic tasks: `slack_classify.md`, `slack_match.md`, `conflict_resolve.md`.

| # | Task | Status |
|---|---|---|
| 11.1 | Write `src/scope_tracker/scripts/prd_parser.py` — `extract_features(raw_text, comments, identifier_col_names, story_col_names)`. Logic: find "User Stories" heading (case-insensitive), parse tables, match columns by header name, filter by identifier regex, build feature dicts, attach comments, derive latest_comment_decision. | PENDING |
| 11.2 | Write `tests/test_prd_parser.py` — (a) extracts features from markdown table with valid IDs; (b) skips rows with non-numeric IDs; (c) returns empty list when no "User Stories" section; (d) attaches comments correctly; (e) handles multiple tables (only extracts from User Stories section); (f) handles pipe-delimited and whitespace-delimited tables. | PENDING |
| 11.3 | Update `cli.py init-sheet` — call `prd_parser.extract_features()` instead of `call_llm(prd_extract.md)`. Write features JSON from Python. | PENDING |
| 11.4 | Update `run_pipeline.py` Step 2a — call `prd_parser.extract_features()` instead of `call_llm(prd_extract.md)`. | PENDING |
| 11.5 | Write `src/scope_tracker/scripts/slack_reporter.py` — `build_report(project_name, run_datetime, steps_executed, run_summary, pending_conflicts)` returns formatted Slack message string. `post_report(bot_token, channel_id, report_text)` posts via Slack API. | PENDING |
| 11.6 | Write `tests/test_slack_reporter.py` — (a) report includes project name and run date; (b) omits conflict section when count=0; (c) includes each conflict as bullet when count>0; (d) post_report calls Slack API. Mock `requests`. | PENDING |
| 11.7 | Update `run_pipeline.py` Step 5 — call `slack_reporter` instead of `call_llm(slack_report.md)`. Read `SLACK_BOT_TOKEN` from `.mcp.json`. | PENDING |
| 11.8 | Audit: grep for all remaining `call_llm` usages. Confirm only 3 remain: `slack_classify.md`, `slack_match.md`, `conflict_resolve.md`. Remove unused prompt files or mark as deprecated. | PENDING |
| 11.9 | All tests pass. | PENDING |
| 11.10 | Update `docs/architecture.md` — reflect final LLM vs Python split. Update `README.md` if needed. | PENDING |

---

## Group 12 — Integration Test, Reinstall, and Verify
**Status: PENDING**
**Req ref:** All sections
**Goal:** Full pipeline works end-to-end with direct API calls. Package reinstalls cleanly. All tests green.

| # | Task | Status |
|---|---|---|
| 12.1 | Update `tests/test_e2e.py` — adjust for direct API calls (mock Google Sheets API, mock Confluence/Slack HTTP, mock `call_llm` only for the 3 semantic prompts). | PENDING |
| 12.2 | Run full test suite: `pytest tests/ -v`. All tests pass. Fix any failures. | PENDING |
| 12.3 | Push to GitHub. Reinstall from git URL. Verify `scope-tracker --help` works. | PENDING |
| 12.4 | Run `scope-tracker init-sheet --project basket-test-slack` end-to-end. Verify: (a) Confluence PRD fetched via direct API; (b) Google Sheet created with URL; (c) config updated with sheet_url. | PENDING |
| 12.5 | Update `CHANGELOG.md` — v1.1.0 entry: "Replaced LLM-as-middleman with direct API calls for Confluence, Slack, Google Sheets, PRD parsing, and report formatting." | PENDING |
| 12.6 | `git tag v1.1.0` | PENDING |

---

## Summary

| Group | Description | Status |
|---|---|---|
| 1 | Repo scaffold and package structure | DONE |
| 2 | Pipeline scripts: diff_prd, diff_slack, update_state | DONE |
| 3 | LLM prompt files (all 8) | DONE |
| 4 | Sheet manager — create, update, formatting, dropdowns, effective status | DONE |
| 5 | Conflict manager and run_pipeline orchestrator | DONE |
| 6 | CLI: init, add, init-sheet commands | DONE |
| 7 | CLI: run, status, doctor commands + user docs | DONE |
| 8 | End-to-end test and release | DONE |
| 9 | Google Sheets direct API integration | PENDING |
| 10 | Confluence and Slack direct API clients | PENDING |
| 11 | PRD parser and Slack reporter (pure Python) | PENDING |
| 12 | Integration test, reinstall, and verify | PENDING |
