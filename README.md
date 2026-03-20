# scope-tracker

Automatically track software project scope and UAT status by reading a PRD (Google Doc or Confluence), a Slack channel, and a Google Sheet — keeping everything in sync.

## Install

```bash
pip install git+https://github.com/{owner}/scope-tracker.git
```

## Requirements

- Python >= 3.10
- [Claude Code CLI](https://claude.ai/code) installed and authenticated
- Node.js / npx (for MCP servers)
- Git

## Quick Start

### 1. Initialize

Navigate to the directory where you want to set up scope-tracker and run:

```bash
scope-tracker init
```

This will:
1. **Check dependencies** — verifies Python 3.10+, Claude CLI, Git, and Node.js are installed
2. **Create `scope-tracker/`** — directory with scripts, prompts, and config files
3. **Set up Slack** — prompts for your Slack Bot Token (`xoxb-...`) and Team ID
4. **Add your first project** — walks you through configuring PRD source, Slack channel, and Google Drive/Confluence credentials

After init completes you'll see:

```
scope-tracker/
├── .mcp.json                  ← MCP credentials (gitignored)
├── .gitignore
├── scope_tracker_config.json  ← project config
├── scripts/                   ← pipeline scripts
├── prompts/                   ← LLM prompt templates
└── {project-name}/
    ├── system/                ← intermediate files
    └── outputs/
```

> **Important:** `.mcp.json` contains credentials — never commit it to git.

### 2. Create the UAT Sheet

```bash
scope-tracker init-sheet --project my-project
```

This reads your PRD, extracts all user stories, and creates a fully formatted Google Sheet with:
- Color-coded column bands (Identity, Source, Scope, UAT)
- Dropdown data validation on all status columns
- Conditional formatting (pass/fail/blocked colors)
- Effective Status auto-computation

### 3. Run the Pipeline

```bash
scope-tracker run --verbose
```

On each run, scope-tracker:
1. Checks for conflict resolutions in Slack
2. Checks if the PRD or Slack channel has new content
3. Extracts and classifies any changes
4. Updates the Google Sheet (new rows, updated descriptions, conflict detection)
5. Persists run state
6. Posts a summary to your reporting Slack channel

Use `--dry-run` to preview changes without writing to the sheet or Slack.

### 4. Add More Projects

```bash
scope-tracker add
```

Walks you through adding another project with its own PRD source and Slack channel.

## CLI Commands

| Command | Description |
|---|---|
| `scope-tracker init` | Initialize scope-tracker in the current directory. Creates folder structure, collects MCP credentials, and sets up the first project. |
| `scope-tracker add` | Add a new project interactively. Prompts for project name, Slack channel, and PRD source. |
| `scope-tracker init-sheet --project NAME` | Create the UAT Google Sheet for a project by extracting PRD user stories and populating the sheet with full formatting. |
| `scope-tracker run [--project NAME] [--dry-run] [--verbose]` | Run the full pipeline for all enabled projects (or a single project). Fetches PRD/Slack changes, updates the sheet, and posts a Slack summary. |
| `scope-tracker status` | Print last run summary for each enabled project as a formatted table. |
| `scope-tracker doctor` | Diagnostic check — verifies all dependencies, MCP configs, and project setup. |

## PRD Format Requirements

Your PRD must have a section with the exact heading **"User Stories"**. This section must contain a table with at least:

- An **identifier column** (header: ID, Identifier, #, or Ref) — values must be numeric (`1`, `1.3`, `1.2.5`)
- A **user story column** (header: User Story, Story, Feature, Requirement, or Description)

Other columns in the table are ignored. Inline comments on story rows are imported.

## Command Examples

### `scope-tracker run`

Run the full pipeline for all projects:

```bash
scope-tracker run --verbose
```

Run for a single project in dry-run mode (no writes):

```bash
scope-tracker run --project scalper --dry-run --verbose
```

Sample output:

```
         Run Summary
┏━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━┓
┃ Project ┃ Status    ┃ Steps ┃ Rows Added ┃ Rows Updated ┃ Conflicts ┃
┡━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━┩
│ scalper │ completed │ 6     │ 3          │ 2            │ 1         │
└─────────┴───────────┴───────┴────────────┴──────────────┴───────────┘
```

### `scope-tracker status`

```bash
scope-tracker status
```

Sample output:

```
              Project Status
┏━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┓
┃ Project ┃ Last Run   ┃ Steps ┃ Sheet Rows ┃ PRD Features ┃ Pending Conflicts  ┃
┡━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━┩
│ scalper │ 2026-03-19 │ 6     │ 24         │ 22           │ 1                  │
└─────────┴────────────┴───────┴────────────┴──────────────┴────────────────────┘
```

### `scope-tracker doctor`

```bash
scope-tracker doctor
```

Sample output:

```
        Doctor — Diagnostic Check
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Check                       ┃ Status ┃ Details                     ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ python3 >= 3.10             │ ✓ Pass │ Python 3.12.1               │
│ claude CLI                  │ ✓ Pass │ claude 1.2.0                │
│ git                         │ ✓ Pass │ git version 2.43.0          │
│ node                        │ ✓ Pass │ v20.11.0                    │
│ npx                         │ ✓ Pass │ 10.2.4                      │
│ .mcp.json exists            │ ✓ Pass │ /path/to/.mcp.json          │
│ .mcp.json has 'slack'       │ ✓ Pass │ Present                     │
│ .mcp.json has 'gdrive'      │ ✓ Pass │ Present                     │
│ Project 'scalper' folder    │ ✓ Pass │ /path/to/scalper            │
│ Project 'scalper' run_state │ ✓ Pass │ Valid JSON                  │
│ Project 'scalper' sheet_url │ ✓ Pass │ https://docs.google.com/... │
└─────────────────────────────┴────────┴─────────────────────────────┘

All checks passed.
```

## Configuration

- `scope_tracker_config.json` — project list, sheet settings, dropdown options
- `.mcp.json` — MCP server credentials (auto-generated, never commit)

See `docs/configuration.md` for full field reference.

## Documentation

- [User Guide](docs/user-guide.md) — PRD format, UAT workflow, conflicts, manual rows
- [Architecture](docs/architecture.md) — pipeline steps, scripts, prompts
- [Configuration](docs/configuration.md) — all config fields explained
