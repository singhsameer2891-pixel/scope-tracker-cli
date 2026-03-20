# scope-tracker — Product Requirements

**Version:** 2.0
**Last updated:** 2026-03-19
**Distribution:** `pip install git+https://github.com/{owner}/scope-tracker.git`

---

## 1. Product Vision

A CLI tool that automatically tracks scope and UAT status across a software project by
reading three sources — a PRD (Google Doc or Confluence page), a Slack channel, and
manual entries — and maintaining a single Google Sheet that serves as both the scope
registry and the UAT tracker.

The user runs one command. The tool reads what changed, updates the sheet, and posts a
summary to Slack. Nothing is ever deleted from the sheet.

---

## 2. How It Works — Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         scope-tracker run                            │
│                        (CLI entry point)                             │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                        run_pipeline.py                               │
│                     Python outer orchestrator                        │
│          Calls scripts directly. Calls claude -p for LLM steps.     │
└───────┬─────────────────────┬────────────────────────────────────────┘
        │                     │
        ▼                     ▼
┌───────────────┐   ┌─────────────────────────────────────────────────┐
│  STEP 0       │   │  STEP 1 — Source Diff Checks (parallel)         │
│  LLM          │   │                                                 │
│  claude -p    │   │  ┌──────────────────┐  ┌──────────────────┐    │
│  Read scope-  │   │  │  diff_prd.py     │  │  diff_slack.py   │    │
│  tracker      │   │  │                 │  │                  │    │
│  Slack for    │   │  │  Check PRD       │  │  Check Slack     │    │
│  conflict     │   │  │  modifiedTime    │  │  watermark       │    │
│  resolutions  │   │  │  via API.        │  │  timestamp.      │    │
│  and user     │   │  │  If unchanged:   │  │  If no new msgs: │    │
│  replies      │   │  │  skip entirely.  │  │  skip entirely.  │    │
└───────┬───────┘   │  │  If changed:     │  │  If new msgs:    │    │
        │           │  │  fetch full PRD  │  │  fetch and       │    │
        │           │  │  and extract     │  │  classify scope  │    │
        │           │  │  user stories.   │  │  threads.        │    │
        │           │  └──────────┬───────┘  └──────────┬───────┘    │
        │           └─────────────┼──────────────────────┼────────────┘
        │                        │                      │
        │           ┌────────────▼──────────────────────▼────────────┐
        │           │  STEP 2 — LLM Extraction (if source changed)   │
        │           │                                                 │
        │           │  If PRD changed:                                │
        │           │  claude -p prd_extract.md                       │
        │           │  → extracts user story rows from table          │
        │           │  → output: prd_features_{date}.json             │
        │           │                                                 │
        │           │  If Slack has new messages:                     │
        │           │  claude -p slack_classify.md                    │
        │           │  → classifies scope-relevant threads            │
        │           │  → output: slack_items_{date}.json              │
        │           └────────────────────┬────────────────────────────┘
        │                                │
        │           ┌────────────────────▼────────────────────────────┐
        │           │  STEP 3 — Sheet Update (sheet_manager.py)       │
        │           │                                                  │
        │           │  For each item in prd_features_{date}.json:     │
        │           │    Look up Source ID = PRD:{identifier}          │
        │           │    Found → check if content changed → update    │
        │           │    Not found → add new row                      │
        │           │                                                  │
        │           │  For each item in slack_items_{date}.json:      │
        │           │    Look up Source ID = SLACK:{thread_ts}        │
        │           │    Found → check if decision changed → update   │
        │           │    Not found → LLM semantic match to existing   │
        │           │    row. If match: update. If no match: add.     │
        │           │                                                  │
        │           │  Manual rows (Source column empty): never touch │
        │           │                                                  │
        │           │  Compute Effective Status for all rows           │
        │           │  Detect conflicts → write to conflict queue     │
        │           └────────────────────┬────────────────────────────┘
        │                                │
        └──────────────┐                 │
                       ▼                 ▼
           ┌───────────────────────────────────────────┐
           │  STEP 4 — State Update + Slack Report     │
           │                                           │
           │  update_state.py                          │
           │  → persist PRD modifiedTime               │
           │  → persist Slack watermark                │
           │  → persist run metadata                   │
           │                                           │
           │  claude -p slack_report.md                │
           │  → post run summary to scope-tracker      │
           │  → include conflict items needing input   │
           │  → update reporting_slack_last_read       │
           └───────────────────────────────────────────┘
```

---

## 3. Data Sources and Read Rules

### 3.1 PRD (Google Doc or Confluence Page)

**When to read:** Only if the source document's `modifiedTime` (Google Drive) or
`version.when` (Confluence) has changed since the value stored in `run_state.json`.
Store the new timestamp after every read. If unchanged, skip entirely — do not call
any MCP tool, do not run LLM extraction.

**What to read:** Only the "User Stories" section of the document.

**Format requirement (documented in user-guide.md):**
The User Stories section must contain a table with at least two columns:
1. An identifier column — values must match `^\d+(\.\d+)*$` exactly
   (valid: `1`, `1.3`, `1.2.5` — invalid: `US-001`, `F1`, any text)
2. A user story / feature description column

Configurable column name lists (in `scope_tracker_config.json`):
- `prd_identifier_column_names`: default `["ID", "Identifier", "#", "Ref"]`
- `prd_story_column_names`: default `["User Story", "Story", "Feature", "Requirement", "Description"]`

The LLM identifies the right columns by matching header names against these lists.
All other columns in the table are ignored even if present.
Rows without a valid numeric identifier are skipped and logged.

**Stable dedup key:** `PRD:{identifier}` — e.g. `PRD:1`, `PRD:1.3`, `PRD:2.1.4`
This key never changes. It is the primary key for all sheet matching operations.

**Inline comments:** Fetch comments from the document using the platform API
(Google Docs comments API or Confluence inline comments API).
- Only include comments that are anchored to a row containing a valid numeric identifier
- Orphan comments (on headings, prose, or unanchored) are ignored entirely
- Multiple comments on the same row: concatenate in chronological order with
  author name and date: `[2026-03-10 Ashwini]: Descoped for V1. [2026-03-15 Sam]: Reinstate, confirmed V1.`
- The **latest** comment's decision is what gets applied to Scope Decision / Target Version
- The full concatenated string is stored in the PRD Comments column for human reference

**On PRD change:** If `modifiedTime` changed, fetch full content and for each identifier:
- If identifier exists in sheet and content unchanged: no action
- If identifier exists in sheet and content changed: update Description, Source Text,
  PRD Comments. Log the change. Post in Slack report as "PRD updated: {id} — content changed."
- If identifier is new (not in sheet): add new row
- If identifier was removed from PRD: do NOT remove from sheet. Log as "PRD:1.3 no
  longer in PRD — row preserved in sheet."

### 3.2 Slack Channel

**When to read:** Only if there are new messages after the stored `last_run_timestamp`
watermark in `run_state.json`. If no new messages, skip entirely.

**What to read:** All new messages and threads after the watermark in the project's
Slack channel. Also re-read threads in `seen_thread_ids` that have new replies.

**Classification:** LLM classifies each thread semantically:
- Is a scope decision being made or implied? (in/out, version, parked, etc.)
- If yes: record decision_type, confidence, verbatim key_messages, thread_ts

**Matching to existing sheet rows:**
- If `SLACK:{thread_ts}` already exists in sheet (Source ID column): same thread,
  check if decision changed, update if yes
- If thread_ts is new: LLM semantic match against existing Feature Names in the sheet.
  Confidence threshold: high or medium only. Low confidence = add as new row.
  If match found: update that row (append Slack to Source, update decision if changed,
  update Source Text to include `[Slack] verbatim message`)

**After reading:** Always update `last_run_timestamp` to the most recent message ts.

### 3.3 Manual Rows

Rows where the Source column is empty were added by the user directly in the sheet.
The tool **never** modifies, updates, or deletes these rows under any circumstance.
They are invisible to the pipeline. The only thing the tool may do is detect a conflict
between a manual row's Scope Decision and a PRD/Slack finding, and post that to Slack.

---

## 4. Conflict Handling

A conflict exists when:
- A PRD identifier's scope decision differs from the same row's Scope Decision in the sheet
- A Slack thread's scope decision for a matched row differs from that row's Scope Decision

**Conflict raised:**
1. Tool posts a clearly formatted message to the `scope-tracker` Slack channel:
   ```
   ⚡ Conflict — PRD:1.3 "Chart Switching"
   PRD says: Pushed to V2
   Sheet currently shows: In Scope
   Which is correct? Reply with "PRD" or "Sheet" (or a custom resolution).
   ```
2. Tool sets Scope Decision to `Conflicting Signal` until resolved
3. Conflict is logged in `run_state.json` conflict queue with identifier, sources, values, timestamp

**Conflict resolved:**
1. On next run, Step 0 reads the scope-tracker Slack channel for replies to conflict messages
2. LLM parses the reply to determine the user's decision
3. Tool writes the resolution to the **Conflict Resolution column** on that row:
   `[2026-03-19 Sam via Slack]: Sheet is correct, keeping In Scope.`
4. Tool updates Scope Decision to the resolved value
5. Conflict removed from queue in `run_state.json`

**Conflict suppression:**
Once Conflict Resolution column has a value for a row, the tool does NOT raise the same
conflict again — unless the PRD or Slack source for that row changes after the resolution
was written. New change after resolution = new conflict.

**Edge case:** If the user never replies, the conflict stays open. It is re-listed in
every Slack report under "Awaiting Resolution" until resolved.

---

## 5. The UAT Sheet

### 5.1 Created automatically

On first run for a project (or `scope-tracker init-sheet --project <name>`), the tool:
1. Reads the PRD and extracts all user stories
2. Creates a new Google Sheet in the user's Google Drive
3. Populates it with all extracted user stories as rows
4. Applies full formatting (see Section 5.3)
5. Stores the Sheet URL in `scope_tracker_config.json` for future writes

### 5.2 Column Layout

**Band 1 — Identity** (background: `#E8F0FE`, light steel blue)
| Column | Owned by | Description |
|---|---|---|
| # | Tool | Auto-incremented stable row number. Never changes once assigned. |
| Feature Name | Tool | Canonical name. For PRD items: story text truncated to 80 chars. For Slack: LLM-generated name. |
| Description | Tool | Full plain-English description of the feature or issue. |

**Band 2 — Source** (background: `#E6F4EA`, light teal)
| Column | Owned by | Description |
|---|---|---|
| Source | Tool | `PRD` / `Slack` / empty (manual). Never changed after row creation. |
| Source ID | Tool | `PRD:1.3` / `SLACK:1773901583.351119` / empty. Primary dedup key. Column width narrow, not prominent. |
| Source Text | Tool | Verbatim text as extracted from PRD or Slack. For PRD: exact user story text. For Slack: exact message text. Updated if source content changes. |
| PRD Section | Tool | The numeric identifier only. e.g. `1.3`. Empty for Slack/manual rows. |
| PRD Comments | Tool | Concatenated inline comments with author + date. Latest decision applied. Updated each run. |

**Band 3 — Scope** (background: `#EDE7F6`, light lavender)
| Column | Owned by | Description |
|---|---|---|
| Scope Decision | Tool (user can override) | Dropdown. See configurable options. Default: `In Scope`. |
| Target Version | Tool (user can override) | Dropdown. See configurable options. |
| Conflict Resolution | Tool | Populated when user resolves a conflict. Format: `[date actor]: resolution text`. Once populated, suppresses re-raising of that conflict. |
| Added Run | Tool | Run number when this row was first added. Integer. |
| Last Updated | Tool | ISO datetime in IST when tool last touched this row. |

**Band 4 — UAT** (background: `#FFF8E1`, warm cream)
| Column | Owned by | Description |
|---|---|---|
| UAT #1 Status | User | Dropdown. Configurable options. Default: `To be tested`. |
| UAT #1 Notes | User | Free text. |
| UAT #2 Status | User | Dropdown. |
| UAT #2 Notes | User | Free text. |
| UAT #3 Status | User | Dropdown. |
| UAT #3 Notes | User | Free text. |
| UAT #4 Status | User | Dropdown. |
| UAT #4 Notes | User | Free text. |
| UAT #5 Status | User | Dropdown. |
| UAT #5 Notes | User | Free text. |
| Effective Status | Tool | Computed each run. Highest-numbered UAT # column that has a non-empty, non-"To be tested" value. If all empty or all "To be tested": shows `To be tested`. |
| Blocker? | User | Dropdown: `Yes` / `No`. |
| Tester | User | Free text. Name of person who tested. |
| Test Date | User | Date. |

**Number of UAT rounds** is configurable via `sheet_config.uat_rounds` (default 5, max 10).
When this value changes, new columns are added on next sheet update. Existing columns are
never removed.

### 5.3 Sheet Formatting

Applied once on sheet creation and re-applied on every run to ensure consistency.

- **Header row**: frozen, bold, height 32px, all column names centered
- **Filter buttons**: enabled on all columns
- **Frozen columns**: first 3 columns (# , Feature Name, Effective Status) always visible
  when scrolling right
- **Color bands**: applied to header and all data rows as described in 5.2
- **Column widths**: # (40px), Feature Name (300px), Description (400px),
  Source (80px), Source ID (100px), Source Text (300px), PRD Section (90px),
  PRD Comments (300px), Scope Decision (160px), Target Version (130px),
  Conflict Resolution (250px), Added Run (90px), Last Updated (160px),
  UAT # Status (140px each), UAT # Notes (200px each), Effective Status (150px),
  Blocker (80px), Tester (120px), Test Date (110px)
- **Row height**: 24px for data rows
- **Text wrapping**: wrap for Description, Source Text, PRD Comments, all Notes columns.
  Clip for all other columns.
- **Borders**: thin light grey border (`#E0E0E0`) between all cells
- **Band separator**: medium grey border (`#BDBDBD`) between each color band (after
  column #3, #8, #12, last UAT column)
- **Effective Status column**: bold font, slightly darker background (`#FFE082`)
- **Dropdowns**: Google Sheets data validation on all dropdown columns for every data row.
  Applied up to row 1000 (extended if needed). Dropdown values read from config at run time.
- **Conditional formatting**:
  - Effective Status = `Passed`: light green background (`#C8E6C9`)
  - Effective Status = `Failed`: light red background (`#FFCDD2`)
  - Effective Status = `Blocked`: light orange background (`#FFE0B2`)
  - Effective Status = `Passed with iteration`: light yellow-green (`#F0F4C3`)
  - Scope Decision = `Active Blocker`: red text, bold
  - Scope Decision = `Conflicting Signal`: orange text, bold
  - Blocker = `Yes`: red text

### 5.4 Effective Status Computation

Run by `sheet_manager.py` on every pipeline run.

```
For each data row:
  For i in range(uat_rounds, 0, -1):  # from highest to lowest
    value = row["UAT #{i} Status"]
    if value is not empty and value != "To be tested":
      effective_status = value
      break
  else:
    effective_status = "To be tested"
  Write effective_status to Effective Status column for this row
```

This is computed in Python by reading the sheet via Google Sheets API — not in a
spreadsheet formula. The tool owns this column.

---

## 6. Configuration Files

### 6.1 `scope_tracker_config.json`

Created by `scope-tracker init`. Stored in `scope-tracker/` directory.

```json
{
  "global_settings": {
    "reporting_slack_channel": "scope-tracker",
    "reporting_slack_last_read": null,
    "default_timezone": "Asia/Kolkata"
  },
  "sheet_config": {
    "uat_rounds": 5,
    "status_options": [
      "To be tested",
      "Passed",
      "Passed with iteration",
      "Failed",
      "Blocked"
    ],
    "version_options": [
      "LIVE",
      "Next release",
      "Parked",
      "Fast follower"
    ],
    "scope_decision_options": [
      "In Scope",
      "Fast Follower",
      "Pushed to V2",
      "Parked",
      "Active Blocker",
      "Conflicting Signal"
    ],
    "blocker_options": ["Yes", "No"],
    "prd_identifier_column_names": ["ID", "Identifier", "#", "Ref"],
    "prd_story_column_names": [
      "User Story", "Story", "Feature", "Requirement", "Description"
    ]
  },
  "projects": [
    {
      "name": "scalper",
      "enabled": true,
      "folder": "scalper",
      "slack_channel": "scalper",
      "sheet_url": "https://docs.google.com/spreadsheets/d/...",
      "prd_source": {
        "type": "google-drive",
        "url": "https://docs.google.com/document/d/...",
        "last_modified": null
      },
      "slack_last_run_timestamp": null,
      "run_count": 0,
      "last_run_date": null
    }
  ]
}
```

**Field notes:**
- `sheet_url`: populated automatically after `scope-tracker init-sheet` creates the sheet.
- `prd_source.last_modified`: stored after each PRD read. Used for mtime check.
- `prd_source.type`: `google-drive` | `confluence` | `none`
- `slack_last_run_timestamp`: Slack watermark. Updated after each run.

### 6.2 `.mcp.json`

Auto-generated by `scope-tracker init`. Stored in `scope-tracker/`. **Never committed to git.**
The `.gitignore` generated by init must include `.mcp.json`.

```json
{
  "mcpServers": {
    "slack": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-slack"],
      "env": {
        "SLACK_BOT_TOKEN": "xoxb-...",
        "SLACK_TEAM_ID": "T..."
      }
    },
    "gdrive": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-gdrive"],
      "env": {
        "GDRIVE_CREDENTIALS_FILE": "/absolute/path/to/credentials.json"
      }
    }
  }
}
```

If the user's PRD source is Confluence, add:
```json
"confluence": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-confluence"],
  "env": {
    "CONFLUENCE_URL": "https://yourteam.atlassian.net/wiki",
    "CONFLUENCE_USERNAME": "user@example.com",
    "CONFLUENCE_API_TOKEN": "..."
  }
}
```

The `gdrive` MCP server is used for both reading the PRD (Google Doc) and reading/writing
the UAT sheet (Google Sheets). Both operations use the same credentials.

### 6.3 `run_state.json`

Stored in `scope-tracker/{project-name}/system/`. One file per project.
Written by `update_state.py` after each run.

```json
{
  "_meta": {
    "created": "2026-03-19T09:00:00+05:30",
    "last_updated": "2026-03-19T15:00:00+05:30"
  },
  "run_count": 3,
  "last_run_date": "2026-03-19",
  "prd": {
    "last_modified": "2026-03-18T10:23:00Z",
    "last_read": "2026-03-18T09:00:00+05:30",
    "feature_count": 22
  },
  "slack": {
    "last_run_timestamp": "1773901583.351119",
    "seen_thread_ids": ["1770359450.452919", "1772790030.028369"]
  },
  "conflicts": [
    {
      "id": "PRD:1.3",
      "source_a": "PRD",
      "value_a": "Pushed to V2",
      "source_b": "Sheet",
      "value_b": "In Scope",
      "raised_at": "2026-03-19T09:00:00+05:30",
      "slack_message_ts": "1773906163.221689",
      "resolved": false
    }
  ],
  "sheet": {
    "last_row_number": 24,
    "last_updated": "2026-03-19T15:00:00+05:30"
  }
}
```

---

## 7. Pipeline Scripts

### 7.1 `diff_prd.py`

**Purpose:** Check if PRD changed. If yes, fetch and extract user stories.

**Arguments:**
```
--project-dir PATH
--config PATH       (scope_tracker_config.json)
--project NAME
```

**Logic:**
1. Read `prd_source` from config for the project
2. If `type: none` → return `{"status": "not configured"}`
3. Fetch document metadata (modifiedTime / version.when) via MCP in a `claude -p` subprocess
   using `prompts/prd_fetch_meta.md`
4. Compare to `run_state.prd.last_modified`
5. If identical → return `{"status": "skipped (unchanged)", "last_modified": "..."}`
6. If changed → fetch full document content via MCP using `prompts/prd_fetch_content.md`
7. Write raw content to `system/{name}_prd_raw.txt`
8. Write inline comments to `system/{name}_prd_comments_raw.json`
9. Return `{"status": "changed", "last_modified": "...", "raw_path": "...", "comments_path": "..."}`

**stdout:** JSON only. All log lines to stderr.

### 7.2 `diff_slack.py`

**Purpose:** Check if new Slack messages exist. If yes, fetch them.

**Arguments:**
```
--project-dir PATH
--config PATH
--project NAME
```

**Logic:**
1. Read `slack_channel` and `slack_last_run_timestamp` from config
2. Call `claude -p prompts/slack_fetch.md` with `{{CHANNEL}}` and `{{WATERMARK_TS}}`
3. If no new messages → return `{"status": "skipped (no new messages)"}`
4. If new messages → write to `system/{name}_slack_raw.json`
5. Return `{"status": "changed", "new_message_count": N, "raw_path": "..."}`

**stdout:** JSON only.

### 7.3 `sheet_manager.py`

**Purpose:** All Google Sheet operations. Creates sheet, adds rows, updates rows,
applies formatting, computes Effective Status.

**Arguments:**
```
--project-dir PATH
--config PATH
--project NAME
--operation create | update
```

**Operations:**

`create`: Called once when sheet does not yet exist.
1. Read `prd_features_{date}.json` from system/
2. Create new Google Sheet via `claude -p prompts/sheet_create.md`
3. Write all rows with full formatting
4. Apply dropdowns, conditional formatting, frozen rows/columns
5. Write sheet URL to config

`update`: Called every run.
1. Read current sheet data into memory
2. Read `prd_features_{date}.json` and `slack_items_{date}.json` from system/
3. For each PRD item: match by `PRD:{identifier}` in Source ID column
   - Match found, content same: no action
   - Match found, content changed: update Description, Source Text, PRD Comments, Last Updated
   - No match: add new row at bottom
4. For each Slack item: match by `SLACK:{thread_ts}` in Source ID column
   - Match found, decision same: no action
   - Match found, decision changed: check conflict rules, update or flag
   - No match: call `claude -p prompts/slack_match.md` for semantic match
     - Match found (high/medium confidence): update row
     - No match: add new row
5. Compute Effective Status for ALL rows
6. Write all changes to sheet in a single batch API call
7. Apply formatting (dropdowns, conditional formatting) to any new rows
8. Detect conflicts: for any row where Source says PRD/Slack but Scope Decision
   contradicts the source finding → add to conflict queue in run_state.json

**stdout:** JSON with `{status, rows_added, rows_updated, conflicts_detected}`.

### 7.4 `conflict_manager.py`

**Purpose:** Read scope-tracker Slack for conflict resolution replies. Apply resolutions.

**Arguments:**
```
--project-dir PATH
--config PATH
--project NAME
```

**Logic:**
1. Read `conflicts` array from run_state.json where `resolved: false`
2. If empty → return `{"status": "no pending conflicts"}`
3. For each unresolved conflict: check if the `slack_message_ts` thread has new replies
   via Slack MCP
4. If reply found: call `claude -p prompts/conflict_resolve.md` to parse the reply
5. Apply resolution:
   - Write to Conflict Resolution column in sheet: `[{date} {actor} via Slack]: {resolution}`
   - Update Scope Decision to resolved value
   - Mark conflict as `resolved: true` in run_state.json
6. Return `{"status": "ok", "resolved_count": N, "pending_count": N}`

**stdout:** JSON only.

### 7.5 `update_state.py`

**Purpose:** Persist run metadata to run_state.json after each run.

No changes from existing implementation except it now writes `prd.last_modified`,
`slack.last_run_timestamp`, and the `conflicts` array.

### 7.6 `run_pipeline.py`

**Purpose:** Outer orchestrator. Runs all steps in order. Calls scripts via subprocess.
Calls `claude -p` for LLM steps.

**Arguments:**
```
--project-dir PATH
--config PATH
--project NAME
--dry-run           (skip all writes, print what would happen)
--verbose           (stream each step to stdout)
```

**Step sequence:**

```
Step 0:  conflict_manager.py          -- read scope-tracker Slack, resolve pending conflicts
Step 1a: diff_prd.py                  -- check PRD modifiedTime (parallel with 1b)
Step 1b: diff_slack.py                -- check Slack watermark  (parallel with 1a)
Step 2a: claude -p prd_extract.md     -- only if diff_prd returned "changed"
Step 2b: claude -p slack_classify.md  -- only if diff_slack returned "changed"
Step 3:  sheet_manager.py --operation update  -- add/update rows, compute Effective Status
Step 4:  update_state.py              -- persist run state
Step 5:  claude -p slack_report.md    -- post Slack report
```

Steps 1a and 1b run in parallel via `ThreadPoolExecutor`.
Steps 2a and 2b run independently (2a only if PRD changed, 2b only if Slack changed).
Steps 3, 4, 5 run sequentially.

**`steps_executed` counter:** Increment after each step regardless of skip. Write to
`system/{name}_steps_executed.json`. A step that was skipped (e.g. PRD unchanged) still
counts — the check ran.

**`call_llm()` helper:**
```python
def call_llm(prompt_file, placeholders: dict, cwd: str, timeout: int = 300) -> str:
    """
    Read prompt_file, replace {{KEY}} placeholders with values from placeholders dict.
    Call claude -p with the resulting prompt string.
    MCP servers are loaded automatically from .mcp.json in cwd.
    Returns stdout string. Raises RuntimeError on non-zero exit.
    """
    with open(prompt_file) as f:
        prompt = f.read()
    for key, value in placeholders.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", str(value))
    result = subprocess.run(
        ["claude", "-p", prompt],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p failed for {prompt_file}: {result.stderr[:500]}")
    return result.stdout
```

---

## 8. LLM Prompt Files

Stored in `scope-tracker/prompts/`. Each is a `.md` file.
Variables injected via `{{PLACEHOLDER}}` substitution before calling `claude -p`.

### 8.1 `prd_fetch_meta.md`
**MCP needed:** gdrive or confluence
**Purpose:** Fetch document metadata (modifiedTime only — not full content)
**Placeholders:** `{{DOC_URL}}`, `{{SOURCE_TYPE}}` (google-drive | confluence), `{{OUTPUT_PATH}}`
**Output:** JSON file at OUTPUT_PATH: `{"modified_time": "2026-03-18T10:23:00Z"}`

### 8.2 `prd_fetch_content.md`
**MCP needed:** gdrive or confluence
**Purpose:** Fetch full document content and inline comments
**Placeholders:** `{{DOC_URL}}`, `{{SOURCE_TYPE}}`, `{{CONTENT_OUTPUT_PATH}}`, `{{COMMENTS_OUTPUT_PATH}}`
**Output (content):** Plain text of document at CONTENT_OUTPUT_PATH
**Output (comments):** JSON array at COMMENTS_OUTPUT_PATH:
```json
[
  {
    "anchor_text": "exact text the comment is anchored to",
    "author": "Name",
    "date": "2026-03-10T09:00:00Z",
    "comment_text": "Descoped for V1"
  }
]
```

### 8.3 `prd_extract.md`
**MCP needed:** None (file in/file out)
**Purpose:** Parse raw PRD text, extract User Stories table rows with valid numeric IDs
**Placeholders:** `{{RAW_CONTENT_PATH}}`, `{{COMMENTS_RAW_PATH}}`, `{{OUTPUT_PATH}}`,
`{{IDENTIFIER_COLUMN_NAMES}}`, `{{STORY_COLUMN_NAMES}}`
**Output:** JSON array at OUTPUT_PATH:
```json
[
  {
    "source_id": "PRD:1.3",
    "identifier": "1.3",
    "feature_name": "Real-time P&L display",
    "description": "Users can see their live P&L in the portfolio view, updated every 30 seconds.",
    "source_text": "Exact verbatim text of the user story from the PRD table",
    "prd_comments": "[2026-03-10 Ashwini]: Descoped for V1. [2026-03-15 Sam]: Reinstate, confirmed V1.",
    "latest_comment_decision": "In Scope",
    "skipped_rows": ["Row with identifier 'US-001' skipped — non-numeric format"]
  }
]
```
Rules in prompt:
- Only rows in the "User Stories" section
- Only rows where identifier matches `^\d+(\.\d+)*$`
- Identifier column identified by matching header to IDENTIFIER_COLUMN_NAMES list
- Story column identified by matching header to STORY_COLUMN_NAMES list
- All other columns ignored
- skipped_rows array lists every row that was skipped and why

### 8.4 `slack_fetch.md`
**MCP needed:** Slack
**Purpose:** Fetch new Slack messages after watermark and re-read threads with new replies
**Placeholders:** `{{CHANNEL}}`, `{{WATERMARK_TS}}`, `{{SEEN_THREAD_IDS}}`, `{{OUTPUT_PATH}}`
**Output:** JSON at OUTPUT_PATH:
```json
{
  "new_message_count": 5,
  "threads": [
    {
      "thread_ts": "1773901583.351119",
      "is_new": true,
      "messages": [
        {"ts": "...", "author": "Name", "text": "verbatim message text"}
      ]
    }
  ]
}
```

### 8.5 `slack_classify.md`
**MCP needed:** None (file in/file out — raw Slack data already fetched)
**Purpose:** Classify scope-relevant threads from raw Slack data
**Placeholders:** `{{RAW_SLACK_PATH}}`, `{{OUTPUT_PATH}}`
**Output:** JSON array at OUTPUT_PATH:
```json
[
  {
    "source_id": "SLACK:1773901583.351119",
    "thread_ts": "1773901583.351119",
    "feature_name": "LLM-generated short name for this scope item",
    "description": "What was decided and why",
    "scope_decision": "Fast Follower",
    "target_version": "Next release",
    "confidence": "high",
    "source_text": "Verbatim key message text from the thread"
  }
]
```
Non-scope threads are not included. Only high or medium confidence items.

### 8.6 `slack_match.md`
**MCP needed:** None
**Purpose:** Semantically match a single Slack item to existing sheet rows
**Placeholders:** `{{SLACK_ITEM_JSON}}`, `{{EXISTING_ROWS_JSON}}`, `{{OUTPUT_PATH}}`
**Output:** JSON at OUTPUT_PATH:
```json
{
  "match_found": true,
  "matched_row_number": 7,
  "matched_feature_name": "Real-time P&L display",
  "confidence": "high",
  "reasoning": "The Slack message discusses P&L visibility which directly matches row 7"
}
```
If `match_found: false` or confidence is `low`, the caller adds a new row.

### 8.7 `conflict_resolve.md`
**MCP needed:** None
**Purpose:** Parse a user's Slack reply to determine their conflict resolution decision
**Placeholders:** `{{CONFLICT_JSON}}`, `{{REPLY_TEXT}}`, `{{OUTPUT_PATH}}`
**Output:** JSON at OUTPUT_PATH:
```json
{
  "resolved": true,
  "winning_source": "Sheet",
  "resolved_value": "In Scope",
  "resolution_text": "Sheet is correct, keeping In Scope",
  "actor": "Sam"
}
```

### 8.8 `slack_report.md`
**MCP needed:** Slack
**Purpose:** Post run completion report to reporting channel
**Placeholders:** `{{REPORTING_CHANNEL}}`, `{{STEPS_EXECUTED_PATH}}`, `{{RUN_SUMMARY_JSON}}`,
`{{PENDING_CONFLICTS_JSON}}`, `{{PROJECT_NAME}}`, `{{RUN_DATETIME}}`
**Output:** Posts message to Slack. Updates `reporting_slack_last_read` in config.

Report format:
```
*Scope Tracker · {DD Mon YYYY} · {HH:MM} IST*

*📦 {Project Name}*

```
PRD       {unchanged/updated} · {feature_count} features tracked
Slack     {N} new messages · {N} scope decisions found
Sheet     {N} rows added · {N} rows updated
Steps     {steps_executed}/6 ({pct}%) executed
```
Decisions: In Scope ({n}) · Fast Follower ({n}) · Pushed to V2 ({n}) · Parked ({n})
🚨 Active Blockers: {n}

*⚡ Awaiting Your Input ({n})*
1. Conflict — PRD:1.3 "Chart Switching" — PRD says Pushed to V2, sheet says In Scope. Reply "PRD" or "Sheet".
2. ...

_Reply here → picked up on next run_
```

Rules:
- Omit "Awaiting Your Input" section if n = 0
- Each conflict item is its own numbered bullet — never grouped
- Each unresolved conflict item remains in every report until resolved

---

## 9. CLI Commands

### `scope-tracker init`

Run once in an empty directory. Creates `scope-tracker/` in the current directory.

Steps:
1. Check `python3 --version` ≥ 3.10. Fail with message if not.
2. Check `claude --version`. If missing: print `Install Claude Code CLI from https://claude.ai/code` and exit.
3. Check `git --version`. Fail with message if not.
4. Check `node --version` (needed for npx MCP servers). Fail if not.
5. Print: "All dependencies found. Setting up scope-tracker..."
6. Create folder structure (see Section 10)
7. Copy scripts and prompts from installed package into `scope-tracker/scripts/` and `scope-tracker/prompts/`
8. Run global settings wizard:
   - "What Slack channel should run reports be posted to? (default: scope-tracker)"
   - "What is your default timezone? (default: Asia/Kolkata)"
9. Run MCP wizard — Slack (always required):
   - "Enter your Slack Bot Token (xoxb-...):"
   - "Enter your Slack Team ID (T...):"
   - Print: "To create a Slack bot, visit https://api.slack.com/apps"
10. Run first project wizard (calls `scope-tracker add` flow)
11. Write `scope_tracker_config.json`
12. Write `.mcp.json`
13. Write `.gitignore`
14. Print success summary with exact next steps

### `scope-tracker add`

Add a new project interactively.

Prompts:
1. "Project name (used as folder name, lowercase, no spaces):"
2. "Slack channel to monitor for scope decisions (no # prefix):"
3. "PRD source — where does your PRD live? [1] Google Doc [2] Confluence page [3] None"
   - If Google Doc: "Paste the Google Doc URL:"
     - Validate URL starts with `https://docs.google.com/document/`
     - If GDrive MCP not yet in `.mcp.json`: run GDrive MCP wizard
   - If Confluence: "Paste the Confluence page URL:"
     - If Confluence MCP not yet in `.mcp.json`: run Confluence MCP wizard
4. "Create the UAT sheet now? [Y/n]"
   - If Y: call `scope-tracker init-sheet --project {name}`

Creates project folder structure. Updates config. Prints confirmation.

**GDrive MCP wizard:**
- "Path to your Google credentials JSON file:" (OAuth2 credentials from Google Cloud Console)
- Print instructions for creating credentials at console.cloud.google.com
- Validate file exists and is valid JSON before proceeding

**Confluence MCP wizard:**
- "Confluence base URL (e.g. https://yourteam.atlassian.net/wiki):"
- "Confluence username (email):"
- "Confluence API token:" (instructions: id.atlassian.com > Security > API tokens)

### `scope-tracker init-sheet --project NAME`

Creates the UAT Google Sheet for a project. Called by `add` or standalone.

Steps:
1. Load config, validate project exists and has PRD source configured
2. Run `diff_prd.py` (forced read, ignoring modifiedTime check)
3. Run `claude -p prd_extract.md` to extract user stories
4. Run `sheet_manager.py --operation create`
5. Print: "Sheet created: {url}"
6. Update `projects[name].sheet_url` in config

### `scope-tracker run`

Run the full pipeline.

```
scope-tracker run [--project NAME] [--dry-run] [--verbose]
```

- `--project`: run for one project only. Default: all enabled projects.
- `--dry-run`: run all steps, but do not write to sheet or post to Slack. Print what would happen.
- `--verbose`: print each step as it starts and completes with timing.

### `scope-tracker status`

Print last run summary for each enabled project as a formatted table.
Columns: Project / Last Run / Steps / Sheet Rows / PRD Features / Pending Conflicts.

### `scope-tracker doctor`

Diagnostic. Check and print pass/fail for:
- python3 ≥ 3.10
- claude CLI installed and responds to `claude --version`
- git installed
- node/npx installed
- `.mcp.json` exists and has `slack` key
- `.mcp.json` has `gdrive` key (if any project uses Google Drive)
- `.mcp.json` has `confluence` key (if any project uses Confluence)
- Each enabled project's folder exists
- Each enabled project's `run_state.json` is valid JSON
- Each enabled project's sheet_url is set in config

---

## 10. Directory Structure

```
scope-tracker/                          ← created by init in current directory
├── .mcp.json                           ← gitignored, has all MCP credentials
├── .gitignore
├── scope_tracker_config.json
│
├── scripts/                            ← copied from package on init
│   ├── run_pipeline.py
│   ├── diff_prd.py
│   ├── diff_slack.py
│   ├── sheet_manager.py
│   ├── conflict_manager.py
│   └── update_state.py
│
├── prompts/                            ← copied from package on init
│   ├── prd_fetch_meta.md
│   ├── prd_fetch_content.md
│   ├── prd_extract.md
│   ├── slack_fetch.md
│   ├── slack_classify.md
│   ├── slack_match.md
│   ├── conflict_resolve.md
│   └── slack_report.md
│
└── {project-name}/
    ├── system/
    │   ├── {name}_run_state.json
    │   ├── {name}_prd_raw.txt
    │   ├── {name}_prd_comments_raw.json
    │   ├── {name}_prd_features_{YYYY-MM-DD}.json
    │   ├── {name}_slack_raw.json
    │   ├── {name}_slack_items_{YYYY-MM-DD}.json
    │   └── {name}_steps_executed.json
    └── outputs/
        └── (empty — all output is in the Google Sheet)
```

---

## 11. Python Package Structure (repo)

```
scope-tracker/                          ← repo root
├── pyproject.toml
├── README.md
├── .gitignore
├── docs/
│   ├── architecture.md                 ← full pipeline description, all scripts
│   ├── configuration.md               ← all config files annotated
│   └── user-guide.md                  ← step-by-step user instructions (see Section 12)
├── src/
│   └── scope_tracker/
│       ├── __init__.py                 ← version string
│       ├── cli.py                      ← click CLI (init, add, init-sheet, run, status, doctor)
│       ├── installer.py               ← dependency checks, scaffold, MCP wizard, config writer
│       ├── runner.py                  ← loads config, calls run_pipeline.py per project
│       └── scripts/                  ← all pipeline scripts (see above)
│       └── prompts/                  ← all prompt files (see above)
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── sample_run_state.json
    │   ├── sample_prd_raw.txt         ← plain text PRD with User Stories table
    │   ├── sample_prd_comments.json
    │   ├── sample_config.json
    │   └── mock_claude.sh             ← fake claude binary returning hardcoded JSON
    ├── test_diff_prd.py
    ├── test_diff_slack.py
    ├── test_sheet_manager.py
    ├── test_conflict_manager.py
    ├── test_run_pipeline.py
    ├── test_installer.py
    └── test_e2e.py
```

### `pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "scope-tracker"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = [
    "click>=8.0",
    "rich>=13.0",
    "openpyxl>=3.1",
    "pymupdf>=1.23",
    "requests>=2.31",
    "google-api-python-client>=2.0",
    "google-auth>=2.0",
]

[project.scripts]
scope-tracker = "scope_tracker.cli:main"
```

---

## 12. User Guide Requirements (for `docs/user-guide.md`)

This document is written for non-technical product managers. It must cover:

**PRD format requirements** — exact wording to include:
> Your PRD must have a section with the exact heading "User Stories". This section must
> contain a table (not a bulleted list). The table must have at least two columns:
> - An identifier column with a header named one of: ID, Identifier, #, Ref
>   (configurable in scope_tracker_config.json). Values must be numeric only, in the
>   format 1, 1.3, 1.2.5 etc. Any row without a valid numeric ID is ignored.
> - A user story column with a header named one of: User Story, Story, Feature,
>   Requirement, Description (configurable). This is the feature text that gets
>   imported into your tracker.
> Other columns in the table are ignored. Inline comments on story rows are imported.

**How to do UAT** — explain the UAT # Status columns, what each status means, that
Effective Status is auto-computed, what Blocker means.

**How conflicts work** — explain that the tool will post in scope-tracker Slack when
it finds a conflict, how to reply, and that it will be picked up automatically.

**How to add items manually** — leave Source column empty. Tool never touches these rows.

**How to update dropdown options** — edit `scope_tracker_config.json` and run again.

---

## 13. Amendments

| Date | Amendment | Reason |
|---|---|---|
| 2026-03-19 | Replaced local xlsx registry with Google Sheet as single source of truth | Simpler UX, one file, no format mismatch |
| 2026-03-19 | Removed audit_coverage.py, verify_coverage.py, write_xlsx.py, export_sources.py, dedup_registry.py | Superseded by sheet_manager.py |
| 2026-03-19 | PRD features extracted from User Stories table only, numeric IDs required | Eliminates LLM guessing about what is a feature |
| 2026-03-19 | PRD/Slack read gated on modifiedTime/watermark check | Performance, avoid redundant reads |
| 2026-03-19 | Conflict resolution flow via Slack thread reply | User resolves in context, not in a config file |
| 2026-03-19 | `pyproject.toml` build-backend changed from `setuptools.backends.legacy:build` to `setuptools.build_meta` | Original value is not a valid setuptools backend |
