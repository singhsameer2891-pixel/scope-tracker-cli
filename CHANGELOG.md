# Changelog

## v1.1.0 — 2026-03-20

Replaced LLM-as-middleman with direct API calls for Confluence, Slack, Google Sheets,
PRD parsing, and report formatting. Added self-healing dependency management.

### Breaking changes

- None. All CLI commands and config format are backward-compatible.

### New: Direct API clients

- **Confluence**: `confluence_client.py` fetches page metadata, content, and comments via REST API (replaces `prd_fetch_meta.md` and `prd_fetch_content.md` LLM calls for Confluence sources)
- **Slack**: `slack_client.py` fetches channel history and thread replies via Slack Web API (replaces `slack_fetch.md` LLM call)
- **Google Sheets**: `google_sheets.py` creates, reads, updates, and formats sheets via Google Sheets API with OAuth2 (replaces LLM-based sheet operations)

### New: Pure Python replacements

- **PRD parser**: `prd_parser.py` extracts user stories from markdown tables deterministically (replaces `prd_extract.md` LLM call)
- **Slack reporter**: `slack_reporter.py` builds and posts run summary reports via Slack API (replaces `slack_report.md` LLM call)

### Remaining LLM usage

Only 3 semantic tasks still use `claude -p`: `slack_classify.md`, `slack_match.md`, `conflict_resolve.md`.

### Self-healing dependency management

- `dependency_manager.py` auto-installs missing Python packages at startup
- `doctor` command offers automatic fixes for resolvable issues
- Google OAuth token refresh handled transparently
- Missing `.mcp.json` keys produce clear error messages with fix instructions

### Testing

- Updated e2e tests to mock direct API clients instead of LLM calls
- 189 tests passing across 15 test files

---

## v1.0.0 — 2026-03-20

Initial release.

### Features

- **CLI commands**: `init`, `add`, `init-sheet`, `run`, `status`, `doctor`
- **`scope-tracker init`**: interactive setup wizard with dependency checks, Slack/GDrive/Confluence MCP configuration, project creation, and directory scaffolding
- **`scope-tracker add`**: add new projects interactively with PRD source and Slack channel configuration
- **`scope-tracker init-sheet`**: create a fully formatted Google Sheet from PRD user stories with color bands, dropdowns, conditional formatting, and frozen columns
- **`scope-tracker run`**: full pipeline execution with `--dry-run` and `--verbose` flags
- **`scope-tracker status`**: display last run summary per project in a rich table
- **`scope-tracker doctor`**: diagnostic check for all dependencies, MCP configs, and project health

### Pipeline

- 6-step pipeline orchestrated by `run_pipeline.py`
- Step 0: conflict resolution via Slack thread replies
- Steps 1a+1b: parallel PRD and Slack diff checks (skip if unchanged)
- Steps 2a+2b: LLM extraction — PRD user stories and Slack scope classification
- Step 3: Google Sheet update — add/update rows, compute Effective Status, detect conflicts
- Step 4: state persistence to `run_state.json`
- Step 5: Slack summary report to reporting channel

### Data sources

- PRD via Google Drive (Google Docs) or Confluence pages
- Slack channel monitoring with watermark-based incremental reads
- Manual rows in Google Sheet (never modified by tool)

### Sheet management

- 4-band column layout: Identity, Source, Scope, UAT
- Configurable UAT rounds (default 5, max 10)
- Effective Status auto-computation from highest UAT round
- Conflict detection with Slack-based resolution flow
- Dropdown data validation on all status columns
- Conditional formatting for pass/fail/blocked/conflict states

### LLM integration

- 8 prompt templates in `prompts/` directory
- All LLM calls via `claude -p` subprocess with `{{PLACEHOLDER}}` substitution
- MCP servers loaded from `.mcp.json` automatically

### Configuration

- `scope_tracker_config.json`: project list, sheet settings, dropdown options
- `.mcp.json`: MCP server credentials (auto-generated, gitignored)
- `run_state.json`: per-project state with deep-merge updates

### Documentation

- `README.md`: install, quick start, CLI reference, command examples
- `docs/architecture.md`: full pipeline, script, and prompt reference
- `docs/configuration.md`: annotated config file reference
- `docs/user-guide.md`: PRD format, UAT workflow, conflicts, manual rows
