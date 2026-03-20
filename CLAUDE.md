# CLAUDE.md — Working Instructions for Claude Code

This file is read automatically by Claude Code at the start of every session.
Follow every rule here without exception.

---

## 1. Working Protocol — Group-by-Group Execution

This is a long build. To avoid context bloat and maintain accuracy, work is broken into
logical groups defined in `TASKS.md`. Follow this protocol precisely on every session.

### On every session start:

1. Read `TASKS.md` in full.
2. Find the first group whose status is `PENDING`. If all groups are `DONE`, tell the user
   the build is complete and stop.
3. Read `REQUIREMENTS.md` — specifically the section(s) relevant to that group.
4. Execute every task in the group, one at a time.
5. After completing each individual task: update its status to `DONE` in `TASKS.md` immediately.
   Do not batch-update at the end. Update as you go.
6. After all tasks in the group are `DONE`: update the group's own status to `DONE` in `TASKS.md`.
7. **STOP.** Print a clear completion summary to the terminal:
   - Which group just completed
   - What was built / changed
   - What the next group is
   - The exact phrase: "Ready for next group — run `clear` then ask me to continue."
8. Wait. Do not proceed to the next group under any circumstances until the user
   explicitly asks to continue in a new session.

### On resume (new session after user confirms):

Same protocol from step 1. `TASKS.md` is the source of truth for where you are.
Never rely on conversation history to determine progress — always read the file.

### Never:
- Skip ahead to a future group without user confirmation
- Mark a task `DONE` if it is not fully implemented and working
- Start a new group in the same session that completed the previous one
- Assume a task is done because something similar exists — verify it

---

## 2. Documentation Rule — Always Keep Docs in Sync

Every time you change any code, you must update all affected documentation before
marking the task done. "Done" means code + docs, never just code.

Documents to keep updated (once created):

| Document | Update when... |
|---|---|
| `README.md` | Any user-facing behaviour changes (commands, install steps, config format) |
| `docs/architecture.md` | Any pipeline step added/removed/changed, any new script, any new MCP dependency |
| `docs/configuration.md` | Any change to `scope_tracker_config.json` schema or `.mcp.json` format |
| `docs/user-guide.md` | Any change to CLI commands, prompts, or output format |
| `REQUIREMENTS.md` | Only if an approved design decision changes — note it as an amendment at the bottom |

If a doc does not exist yet (early groups), skip it. Once it exists, it must stay current.

---

## 3. Code Standards

Apply these on every file you write or modify.

### Python
- Type hints on every function signature
- Docstring on every module (top) and every non-trivial function: what it does, args, return
- All file paths resolved with `os.path.expanduser()` and `os.path.abspath()`
- Every `subprocess.run()` call wrapped in try/except with a human-readable error message
- Every external file read wrapped in try/except — never assume a file exists
- Scripts exit with code 0 on success, non-zero on error
- All stdout output from pipeline scripts is JSON — never mix human text and JSON on stdout
- Use `stderr` for human-readable log lines; `stdout` for machine-readable JSON output
- No hardcoded paths anywhere — all paths derived from config or arguments
- No `print` debugging left in committed code

### LLM prompt files
- Each `claude -p` call reads its system prompt from a `.md` file in `prompts/`
- Prompt files are versioned alongside code — if the prompt changes, update the file
- Every prompt file has a header comment describing: purpose, inputs expected, output format

### Tests
- Every new script gets a corresponding test file in `tests/`
- Tests use `pytest` and mock external calls (no real Slack/Drive calls in tests)
- Tests must pass before a task is marked `DONE`
- At minimum: one happy-path test and one error-path test per script

### Git hygiene (once repo is initialised)
- Commit after each completed task group, not after individual tasks
- Commit message format: `[Group N] Short description of what was built`
- Never commit: `.mcp.json` (contains credentials), `*_run_state.json`, `outputs/`, `*.xlsx`

### Auto commit + push after every change
After **every** code or file change — including bug fixes, hotfixes, and ad-hoc edits outside
of the normal group workflow — you must:
1. `git add` the changed files
2. `git commit` with a descriptive message
3. `git push origin main`
4. Confirm to the user with: "Committed and pushed: `<commit message>`"

Do this automatically. Never ask the user to push manually. Never leave changes unpushed.

---

## 4. File Structure Reference

Once built, the installed tool creates this structure in the user's chosen directory:

```
scope-tracker/                        ← created by `scope-tracker init`
├── .mcp.json                         ← MCP server configs (gitignored — has credentials)
├── scope_tracker_config.json         ← project list and global settings
├── _master_run_log.xlsx              ← created on first run
├── scripts/                          ← all pipeline Python scripts (installed by package)
│   ├── run_pipeline.py               ← main orchestrator
│   ├── diff_prd.py
│   ├── diff_uat.py
│   ├── write_xlsx.py
│   ├── export_sources.py
│   ├── audit_coverage.py
│   ├── verify_coverage.py
│   ├── dedup_registry.py
│   ├── update_state.py
│   └── read_state.py
├── prompts/                          ← claude -p prompt files (installed by package)
│   ├── prd_extract.md
│   ├── slack_classify.md
│   ├── canonical_merge.md
│   └── slack_report.md
└── {project-name}/                   ← one folder per project
    ├── system/                       ← intermediate files (not user-facing)
    │   ├── {name}_run_state.json
    │   ├── {name}_payload.json
    │   ├── {name}_state_updates.json
    │   ├── {name}_slack_manifest.json
    │   ├── {name}_prefetch_results.json
    │   └── {name}_steps_executed.json
    └── outputs/                      ← user-facing outputs
        ├── scope_tracker_{name}.xlsx
        ├── {name}_sources_prd.json
        ├── {name}_sources_slack.json
        └── {name}_sources_uat.json
```

---

## 5. Key Design Decisions (do not override without noting an amendment in REQUIREMENTS.md)

- Distribution: `pip install git+https://github.com/...` — not PyPI
- Install location: wherever the user runs `scope-tracker init` — not a fixed path
- LLM calls: via `claude -p` subprocess — not API calls, not inline in Python
- MCP access: via `.mcp.json` in the project directory — auto-generated by `init`
- Source data: Google Drive (PRD docs + UAT sheets), Slack (decisions), Confluence (PRD, optional)
- No local input files required after setup — all data fetched live via MCP
- Three LLM steps only: PRD extraction, Slack classification, canonical merge
- Everything else is deterministic Python — no LLM for hashing, diffs, xlsx writing, auditing

---

## 6. Dependency Check Order (for `scope-tracker init`)

Check these in order. Stop with a clear message if any is missing before it's needed:

1. `python3` ≥ 3.10
2. `claude` CLI — must be installed and authenticated. If missing: print install URL and stop.
3. `git` — needed for pip install from GitHub
4. Python packages: `openpyxl`, `pypdf2` or `pymupdf`, `click`, `rich` (for terminal UI)

MCP server credentials are collected interactively during `scope-tracker init` and written
to `.mcp.json`. The user is told explicitly that `.mcp.json` must never be committed.
