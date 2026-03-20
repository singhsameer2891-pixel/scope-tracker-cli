# User Guide

This guide is for product managers and team members who use scope-tracker to manage
project scope and UAT status. No technical setup knowledge is required beyond the
initial install.

---

## PRD Format Requirements

Your PRD must have a section with the exact heading **"User Stories"**. This section
must contain a table (not a bulleted list). The table must have at least two columns:

- **An identifier column** with a header named one of: **ID**, **Identifier**, **#**, **Ref**
  (configurable in `scope_tracker_config.json`). Values must be numeric only, in the
  format `1`, `1.3`, `1.2.5` etc. Any row without a valid numeric ID is ignored.

- **A user story column** with a header named one of: **User Story**, **Story**,
  **Feature**, **Requirement**, **Description** (configurable). This is the feature
  text that gets imported into your tracker.

Other columns in the table are ignored. Inline comments on story rows are imported.

### Example PRD table

| ID  | User Story                                    | Priority |
|-----|-----------------------------------------------|----------|
| 1   | Users can log in with email and password       | High     |
| 1.1 | Users can reset their password via email link  | High     |
| 2   | Users can view their portfolio dashboard       | Medium   |
| 2.1 | Dashboard shows real-time P&L                  | Medium   |

In this example, scope-tracker imports the **ID** and **User Story** columns.
The **Priority** column is ignored. All four rows have valid numeric identifiers
and will be imported.

### What gets ignored

- Rows where the identifier is not numeric (e.g. `US-001`, `F1`, `TBD`) are skipped
- Rows outside the "User Stories" section are ignored
- Bulleted lists, even if they look like features, are not imported — only table rows

### Inline comments

If your PRD is a Google Doc, inline comments on rows within the User Stories table
are imported automatically. Comments from multiple people are concatenated with
author name and date. The most recent comment's decision is applied to the
Scope Decision column.

---

## How the UAT Sheet Works

When you run `scope-tracker init-sheet --project <name>`, a Google Sheet is created
with all your PRD user stories as rows. The sheet has four color-coded sections:

### Column bands

| Band       | Color        | What it contains                                      |
|------------|--------------|-------------------------------------------------------|
| Identity   | Light blue   | Row number, Feature Name, Description                 |
| Source     | Light teal   | Source (PRD/Slack), Source ID, Source Text, PRD info   |
| Scope      | Light purple | Scope Decision, Target Version, Conflict Resolution   |
| UAT        | Warm cream   | UAT round statuses, notes, Effective Status, Blocker  |

### Columns you fill in

These columns are yours to edit. The tool never overwrites them:

- **UAT #1 Status** through **UAT #5 Status** — dropdown with options:
  `To be tested`, `Passed`, `Passed with iteration`, `Failed`, `Blocked`
- **UAT #1 Notes** through **UAT #5 Notes** — free text for your testing notes
- **Blocker?** — dropdown: `Yes` / `No`
- **Tester** — name of the person who tested
- **Test Date** — when the test was done

### Columns the tool manages

These columns are updated automatically on each run. Do not edit them manually:

- **#** — stable row number, never changes
- **Feature Name** — short name derived from the PRD or Slack
- **Description** — full description
- **Source** / **Source ID** — where the item came from (`PRD` or `Slack`)
- **Source Text** — verbatim text from the original source
- **PRD Section** / **PRD Comments** — PRD identifier and inline comments
- **Scope Decision** — initially set from source, can be overridden
- **Target Version** — initially set from source, can be overridden
- **Conflict Resolution** — populated when you resolve a conflict
- **Added Run** / **Last Updated** — timestamps
- **Effective Status** — auto-computed (see below)

### Effective Status

Effective Status is computed automatically on every run. It looks at your UAT round
columns from highest to lowest (UAT #5, then #4, then #3, etc.) and shows the first
non-empty value that is not "To be tested".

- If UAT #3 = "Passed" and UAT #4 = "Failed", Effective Status = **Failed**
  (highest round with a real result)
- If all UAT columns are empty or "To be tested", Effective Status = **To be tested**

This gives you a quick at-a-glance view of where each feature stands.

---

## How to Do UAT

1. Open the Google Sheet for your project
2. Find the feature you are testing
3. In the appropriate UAT round column (e.g. **UAT #1 Status**), select your result
   from the dropdown: `Passed`, `Failed`, `Blocked`, or `Passed with iteration`
4. Add any notes in the corresponding **UAT #1 Notes** column
5. Fill in your name under **Tester** and the date under **Test Date**
6. If there is a blocking issue, set **Blocker?** to `Yes`

The Effective Status column updates automatically on the next pipeline run.

### Multiple UAT rounds

Each round represents a testing cycle. When you start a new round of UAT, use the
next numbered columns (e.g. move from UAT #1 to UAT #2). Previous round results
are preserved for history.

---

## How Conflicts Work

A conflict is raised when the tool finds a disagreement:
- The PRD says a feature is "Pushed to V2" but the sheet shows "In Scope"
- A Slack decision says "Fast Follower" but the sheet shows "In Scope"

### What happens when a conflict is detected

1. The tool posts a message to your scope-tracker Slack channel:
   ```
   Conflict — PRD:1.3 "Chart Switching"
   PRD says: Pushed to V2
   Sheet currently shows: In Scope
   Which is correct? Reply with "PRD" or "Sheet" (or a custom resolution).
   ```
2. The Scope Decision column is set to **Conflicting Signal** until you resolve it
3. The conflict appears in every run report until resolved

### How to resolve a conflict

Reply to the conflict message in Slack. You can say:
- **"PRD"** — accept the PRD's value
- **"Sheet"** — keep what's in the sheet
- **A custom resolution** — e.g. "Actually this is In Scope for V1, confirmed with Priya"

On the next run, the tool reads your reply, updates the Scope Decision, and records
your resolution in the **Conflict Resolution** column on the sheet. The conflict is
then removed from future reports.

### What if you don't reply?

The conflict stays open. It is re-listed in every Slack report under "Awaiting
Resolution" until someone replies.

---

## How to Add Items Manually

You can add rows directly to the Google Sheet for items not tracked in the PRD
or Slack. Simply:

1. Add a new row at the bottom of the sheet
2. Fill in **Feature Name** and **Description**
3. **Leave the Source column empty**

The tool never modifies, updates, or deletes rows where the Source column is empty.
Your manual rows are completely safe. The only interaction is that the tool may detect
a conflict if a PRD or Slack item matches your manual row's scope decision.

---

## How to Update Dropdown Options

All dropdown lists (Scope Decision, Target Version, UAT Status, Blocker) are
configured in `scope_tracker_config.json`. To change them:

1. Open `scope_tracker_config.json` in a text editor
2. Find the `sheet_config` section
3. Edit the relevant list:
   - `status_options` — UAT status dropdown values
   - `scope_decision_options` — Scope Decision dropdown values
   - `version_options` — Target Version dropdown values
   - `blocker_options` — Blocker dropdown values
4. Save the file
5. Run `scope-tracker run` — the updated dropdowns are applied on the next run

### Example

To add a new scope decision option "Descoped":

```json
"scope_decision_options": [
    "In Scope",
    "Fast Follower",
    "Pushed to V2",
    "Parked",
    "Active Blocker",
    "Conflicting Signal",
    "Descoped"
]
```

---

## Running the Pipeline

### Regular run

```bash
scope-tracker run --verbose
```

This checks all sources, updates the sheet, and posts a Slack report.

### Dry run (preview only)

```bash
scope-tracker run --dry-run
```

Runs all checks but does not write to the sheet or post to Slack. Useful for
verifying what would change before committing.

### Single project

```bash
scope-tracker run --project my-project --verbose
```

### Checking status

```bash
scope-tracker status
```

Shows a table with each project's last run date, step count, sheet rows,
PRD features tracked, and pending conflicts.

### Health check

```bash
scope-tracker doctor
```

Verifies all dependencies, MCP credentials, and project configuration.
Shows pass/fail for each check with fix instructions for failures.
