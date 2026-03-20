# Start Here — scope-tracker Build Prompt

Paste everything below this line into Claude Code to begin the build.

---

## Prompt

You are about to build **scope-tracker** — a Python CLI tool that tracks software project
scope and UAT status by reading a PRD (Google Doc or Confluence), a Slack channel, and
a manually maintained Google Sheet, then keeping everything in sync automatically.

Before writing a single line of code, read these three files in full. They are your
complete specification, working protocol, and task tracker. Do not rely on this prompt
for any design details — everything is in those files.

**Read in this order:**

1. `CLAUDE.md` — your working protocol, code standards, and standing rules.
   Follow every instruction in this file without exception for the entire build.
   If you find anything missing, unclear, or that would improve your ability to
   execute this build accurately, **enhance CLAUDE.md** with the addition before
   proceeding. Do not remove or override any existing rule — only add.

2. `REQUIREMENTS.md` — the full product specification. Every design decision,
   every script, every prompt file, every config format, every column in the sheet,
   every CLI command, and every edge case is documented here. When in doubt about
   how something should work, the answer is in this file.

3. `TASKS.md` — the execution tracker. Logically grouped tasks with statuses.
   This tells you exactly what to build and in what order.

**After reading all three files, do the following:**

1. Confirm to me in one short paragraph what you understand this project to be,
   which group you are starting with, and how many tasks are in that group.

2. Begin executing Group 1 immediately — do not wait for further instruction.

3. Follow the working protocol in `CLAUDE.md` precisely:
   - Update each task status to DONE in `TASKS.md` as you complete it
   - Do not batch-update at the end
   - After all tasks in the group are DONE, update the group status
   - Stop and print the confirmation message exactly as specified in `CLAUDE.md`
   - Do not begin Group 2 until I explicitly ask you to continue

The files are located in the same directory as this prompt file.
