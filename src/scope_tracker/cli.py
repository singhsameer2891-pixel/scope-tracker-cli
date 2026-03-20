"""CLI entry point for scope-tracker.

Provides commands: init, add, init-sheet, run, status, doctor.
All commands use Click for argument parsing and Rich for terminal output.
"""

import json
import os
import subprocess
import sys
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

console = Console()


@click.group()
@click.version_option(package_name="scope-tracker")
def main() -> None:
    """scope-tracker — track project scope and UAT status automatically."""
    from scope_tracker.scripts.dependency_manager import ensure_python_deps

    try:
        ensure_python_deps()
    except SystemExit:
        # ensure_python_deps already printed the error and pip command
        raise


@main.command()
def init() -> None:
    """Initialize scope-tracker in the current directory."""
    from scope_tracker.installer import (
        build_default_config,
        check_dependencies,
        create_project_folders,
        run_google_sheets_wizard,
        run_project_wizard,
        run_slack_mcp_wizard,
        scaffold_directories,
        write_config,
        write_gitignore,
        write_mcp_config,
    )

    # Step 1-4: Check dependencies
    check_dependencies()

    # Step 6-7: Scaffold directories and copy scripts/prompts
    cwd = os.getcwd()
    st_dir = scaffold_directories(cwd)
    console.print(f"[green]Created scope-tracker directory at {st_dir}[/green]")

    # Step 8: Global settings wizard
    reporting_channel = click.prompt(
        "What Slack channel should run reports be posted to?",
        default="scope-tracker",
    ).strip()
    timezone = click.prompt(
        "What is your default timezone?",
        default="Asia/Kolkata",
    ).strip()

    # Google Sheets OAuth2 setup
    gs_config = run_google_sheets_wizard()

    # Copy client_secret.json into scope-tracker dir for self-contained setup
    original_path = gs_config.pop("_original_path", "")
    if original_path:
        dest_secret = os.path.join(st_dir, "client_secret.json")
        if not os.path.isfile(dest_secret):
            import shutil
            shutil.copy2(original_path, dest_secret)
            console.print(f"[green]Copied client_secret.json to {dest_secret}[/green]")
            gs_config["client_secret_path"] = dest_secret
        elif os.path.abspath(original_path) != os.path.abspath(dest_secret):
            console.print(f"[dim]client_secret.json already exists in {st_dir}[/dim]")
            gs_config["client_secret_path"] = dest_secret

    config = build_default_config(
        reporting_channel=reporting_channel,
        timezone=timezone,
        google_sheets_config=gs_config,
    )

    # Step 9: Slack MCP wizard (always required)
    slack_creds = run_slack_mcp_wizard()
    mcp_config: dict = {"slack": slack_creds}

    # Step 10: First project wizard
    existing_mcp = list(mcp_config.keys())
    project_config, new_mcp = run_project_wizard(existing_mcp)
    config["projects"].append(project_config)

    # Merge any new MCP servers from project wizard
    if new_mcp:
        mcp_config.update(new_mcp)

    # Create project folders
    create_project_folders(st_dir, project_config["name"])

    # Step 11-13: Write config files
    write_config(st_dir, config)
    write_mcp_config(st_dir, mcp_config)
    write_gitignore(st_dir)

    console.print(Panel(
        f"[bold green]scope-tracker initialized successfully![/bold green]\n\n"
        f"Directory: {st_dir}\n"
        f"Project: {project_config['name']}\n"
        f"Reporting channel: #{reporting_channel}\n\n"
        f"[bold]Next steps:[/bold]\n"
        f"  1. cd scope-tracker\n"
        f"  2. scope-tracker init-sheet --project {project_config['name']}\n"
        f"  3. scope-tracker run --verbose\n\n"
        f"[dim]Note: .mcp.json contains credentials — never commit it to git.[/dim]",
        title="Setup Complete",
    ))


@main.command()
def add() -> None:
    """Add a new project interactively."""
    from scope_tracker.installer import (
        create_project_folders,
        load_config,
        run_project_wizard,
        write_config,
        write_mcp_config,
    )

    # Find scope-tracker directory
    st_dir = _find_scope_tracker_dir()
    if not st_dir:
        console.print("[red]Could not find scope-tracker/ directory. Run 'scope-tracker init' first.[/red]")
        raise SystemExit(1)

    config_path = os.path.join(st_dir, "scope_tracker_config.json")
    config = load_config(config_path)

    # Determine existing MCP servers
    mcp_path = os.path.join(st_dir, ".mcp.json")
    existing_mcp: list[str] = []
    if os.path.isfile(mcp_path):
        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                mcp_data = json.load(f)
            existing_mcp = list(mcp_data.get("mcpServers", {}).keys())
        except (json.JSONDecodeError, OSError):
            pass

    # Run project wizard
    project_config, new_mcp = run_project_wizard(existing_mcp)

    # Check for duplicate project name
    for p in config.get("projects", []):
        if p["name"] == project_config["name"]:
            console.print(f"[red]Project '{project_config['name']}' already exists.[/red]")
            raise SystemExit(1)

    # Append project to config
    config.setdefault("projects", []).append(project_config)
    write_config(st_dir, config)

    # Update .mcp.json if new MCP servers were added
    if new_mcp and os.path.isfile(mcp_path):
        try:
            with open(mcp_path, "r", encoding="utf-8") as f:
                mcp_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            mcp_data = {"mcpServers": {}}

        # Add new server entries
        for server_name, creds in new_mcp.items():
            if server_name == "gdrive":
                mcp_data["mcpServers"]["gdrive"] = {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-gdrive"],
                    "env": creds,
                }
            elif server_name == "confluence":
                mcp_data["mcpServers"]["confluence"] = {
                    "command": "npx",
                    "args": ["-y", "@aashari/mcp-server-atlassian-confluence"],
                    "env": creds,
                }

        with open(mcp_path, "w", encoding="utf-8") as f:
            json.dump(mcp_data, f, indent=2)
            f.write("\n")

    # Create project folders
    create_project_folders(st_dir, project_config["name"])

    console.print(Panel(
        f"[bold green]Project '{project_config['name']}' added successfully![/bold green]\n\n"
        f"Folder: {os.path.join(st_dir, project_config['name'])}\n\n"
        f"[bold]Next steps:[/bold]\n"
        f"  scope-tracker init-sheet --project {project_config['name']}",
        title="Project Added",
    ))


@main.command(name="init-sheet")
@click.option("--project", required=True, help="Project name to create sheet for.")
def init_sheet(project: str) -> None:
    """Create the UAT Google Sheet for a project."""
    from scope_tracker.installer import load_config, write_config

    # Find scope-tracker directory
    st_dir = _find_scope_tracker_dir()
    if not st_dir:
        console.print("[red]Could not find scope-tracker/ directory. Run 'scope-tracker init' first.[/red]")
        raise SystemExit(1)

    config_path = os.path.join(st_dir, "scope_tracker_config.json")
    config = load_config(config_path)

    # Find the project in config
    project_config = None
    for p in config.get("projects", []):
        if p["name"] == project:
            project_config = p
            break

    if not project_config:
        console.print(f"[red]Project '{project}' not found in config.[/red]")
        raise SystemExit(1)

    if project_config.get("prd_source", {}).get("type") == "none":
        console.print(f"[red]Project '{project}' has no PRD source configured. Cannot create sheet.[/red]")
        raise SystemExit(1)

    project_dir = os.path.join(st_dir, project_config["folder"])
    system_dir = os.path.join(project_dir, "system")
    os.makedirs(system_dir, exist_ok=True)

    # Step 2: Run diff_prd.py with forced read (pass --force to ignore mtime)
    scripts_dir = os.path.join(st_dir, "scripts")
    console.print("[bold]Step 1/4:[/bold] Fetching PRD content...")
    try:
        diff_result = subprocess.run(
            [
                sys.executable,
                os.path.join(scripts_dir, "diff_prd.py"),
                "--project-dir", project_dir,
                "--config", config_path,
                "--project", project,
                "--force",
            ],
            capture_output=True,
            text=True,
            cwd=st_dir,
            timeout=600,
        )
        if diff_result.returncode != 0:
            console.print(f"[red]diff_prd.py failed:[/red]\n{diff_result.stderr}")
            raise SystemExit(1)
        diff_output = json.loads(diff_result.stdout)
        console.print(f"  PRD status: {diff_output.get('status', 'unknown')}")
    except subprocess.TimeoutExpired:
        console.print("[red]diff_prd.py timed out after 10 minutes.[/red]")
        raise SystemExit(1)
    except json.JSONDecodeError:
        console.print(f"[red]diff_prd.py returned invalid JSON:[/red]\n{diff_result.stdout}")
        raise SystemExit(1)

    # Step 3: Extract features using pure Python parser
    console.print("[bold]Step 2/4:[/bold] Extracting user stories from PRD...")
    from scope_tracker.scripts.prd_parser import extract_features

    import datetime
    date_str = datetime.date.today().isoformat()
    raw_path = diff_output.get("raw_path", os.path.join(system_dir, f"{project}_prd_raw.txt"))
    comments_path = diff_output.get("comments_path", os.path.join(system_dir, f"{project}_prd_comments_raw.json"))
    features_output_path = os.path.join(system_dir, f"{project}_prd_features_{date_str}.json")

    sheet_config = config.get("sheet_config", {})
    identifier_col_names = sheet_config.get("prd_identifier_column_names", ["ID", "Identifier", "#", "Ref"])
    story_col_names = sheet_config.get("prd_story_column_names", ["User Story", "Story", "Feature", "Requirement", "Description"])

    try:
        # Read raw PRD text
        with open(raw_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        # Read comments (may not exist)
        comments: list = []
        try:
            with open(comments_path, "r", encoding="utf-8") as f:
                comments = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        features = extract_features(raw_text, comments, identifier_col_names, story_col_names)

        # Write features JSON
        with open(features_output_path, "w", encoding="utf-8") as f:
            json.dump(features, f, indent=2)

        console.print(f"  Extracted {len(features)} features to: {features_output_path}")
    except FileNotFoundError as exc:
        console.print(f"[red]PRD extraction failed:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        console.print(f"[red]PRD extraction failed:[/red] {exc}")
        raise SystemExit(1)

    # Step 4: Create Google Sheet via direct API
    console.print("[bold]Step 3/4:[/bold] Creating Google Sheet...")

    # Verify Google Sheets credentials are configured
    gs_config = config.get("google_sheets", {})
    client_secret_path = gs_config.get("client_secret_path", "")
    if not client_secret_path:
        console.print("[red]Google Sheets client_secret_path not configured.[/red]")
        console.print("Run [bold]scope-tracker init[/bold] to configure Google Sheets credentials.")
        raise SystemExit(1)

    try:
        from scope_tracker.scripts.sheet_manager import create_sheet, build_headers

        sheet_output = create_sheet(
            config=config,
            project_config=project_config,
            project_dir=project_dir,
            prd_features_path=features_output_path,
        )
        sheet_url = sheet_output.get("sheet_url", "")
        console.print(f"  Sheet URL: {sheet_url}")
    except FileNotFoundError as exc:
        console.print(f"[red]Sheet creation failed:[/red] {exc}")
        raise SystemExit(1)
    except Exception as exc:
        console.print(f"[red]Sheet creation failed:[/red] {exc}")
        raise SystemExit(1)

    # Step 5: Update config with sheet_url
    console.print("[bold]Step 4/4:[/bold] Updating config...")
    if sheet_url:
        for p in config["projects"]:
            if p["name"] == project:
                p["sheet_url"] = sheet_url
                break
        write_config(st_dir, config)

    console.print(Panel(
        f"[bold green]Sheet created for project '{project}'![/bold green]\n\n"
        f"URL: {sheet_url}\n\n"
        f"Run [bold]scope-tracker run --project {project} --verbose[/bold] to start tracking.",
        title="Sheet Ready",
    ))


@main.command()
@click.option("--project", default=None, help="Run for a specific project only.")
@click.option("--dry-run", is_flag=True, help="Skip all writes, print what would happen.")
@click.option("--verbose", is_flag=True, help="Print each step as it runs.")
def run(project: str | None, dry_run: bool, verbose: bool) -> None:
    """Run the full pipeline for all enabled projects."""
    from rich.table import Table
    from scope_tracker.runner import run_all

    st_dir = _find_scope_tracker_dir()
    if not st_dir:
        console.print("[red]Could not find scope-tracker/ directory. Run 'scope-tracker init' first.[/red]")
        raise SystemExit(1)

    config_path = os.path.join(st_dir, "scope_tracker_config.json")

    if dry_run:
        console.print("[yellow]Dry-run mode — no writes to sheet or Slack.[/yellow]")

    try:
        results = run_all(
            config_path=config_path,
            project_filter=project,
            dry_run=dry_run,
            verbose=verbose,
        )
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)

    if not results:
        console.print("[yellow]No projects to run.[/yellow]")
        return

    # Print summary table
    table = Table(title="Run Summary")
    table.add_column("Project", style="bold")
    table.add_column("Status")
    table.add_column("Steps")
    table.add_column("Rows Added")
    table.add_column("Rows Updated")
    table.add_column("Conflicts")

    for r in results:
        status_str = r.get("status", "unknown")
        if status_str == "completed":
            status_display = "[green]completed[/green]"
        elif status_str == "error":
            status_display = "[red]error[/red]"
        else:
            status_display = status_str

        summary = r.get("summary", {})
        table.add_row(
            r.get("project", "?"),
            status_display,
            str(r.get("steps_executed", "—")),
            str(summary.get("rows_added", "—")),
            str(summary.get("rows_updated", "—")),
            str(summary.get("conflicts_detected", "—")),
        )

    console.print(table)


@main.command()
def status() -> None:
    """Print last run summary for each enabled project."""
    from rich.table import Table

    st_dir = _find_scope_tracker_dir()
    if not st_dir:
        console.print("[red]Could not find scope-tracker/ directory. Run 'scope-tracker init' first.[/red]")
        raise SystemExit(1)

    config_path = os.path.join(st_dir, "scope_tracker_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        console.print(f"[red]Could not read config: {exc}[/red]")
        raise SystemExit(1)

    projects = [p for p in config.get("projects", []) if p.get("enabled", True)]

    if not projects:
        console.print("[yellow]No enabled projects found.[/yellow]")
        return

    table = Table(title="Project Status")
    table.add_column("Project", style="bold")
    table.add_column("Last Run")
    table.add_column("Steps")
    table.add_column("Sheet Rows")
    table.add_column("PRD Features")
    table.add_column("Pending Conflicts")

    for p in projects:
        project_name = p["name"]
        project_dir = os.path.join(st_dir, p.get("folder", project_name))

        # Read run_state.json
        run_state: dict = {}
        state_path = os.path.join(project_dir, "system", f"{project_name}_run_state.json")
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                run_state = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # Read steps_executed.json
        steps_data: dict = {}
        steps_path = os.path.join(project_dir, "system", f"{project_name}_steps_executed.json")
        try:
            with open(steps_path, "r", encoding="utf-8") as f:
                steps_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        last_run = run_state.get("last_run_date", "—")
        steps_executed = str(steps_data.get("steps_executed", "—"))
        sheet_rows = str(run_state.get("sheet", {}).get("last_row_number", "—"))
        prd_features = str(run_state.get("prd", {}).get("feature_count", "—"))
        pending_conflicts = str(
            len([c for c in run_state.get("conflicts", []) if not c.get("resolved", False)])
        )

        table.add_row(project_name, last_run, steps_executed, sheet_rows, prd_features, pending_conflicts)

    console.print(table)


@main.command()
@click.option("--fix", is_flag=True, help="Auto-fix issues that can be resolved automatically.")
def doctor(fix: bool) -> None:
    """Diagnostic check for all dependencies and configuration."""
    from rich.table import Table
    from scope_tracker.scripts.dependency_manager import (
        ensure_directories,
        ensure_python_deps,
    )

    st_dir = _find_scope_tracker_dir()

    # (name, passed, detail, auto_fixable, fix_func)
    checks: list[tuple[str, bool, str, bool, Any]] = []
    fixed: list[str] = []

    def _add_check(
        name: str, passed: bool, detail: str,
        auto_fixable: bool = False, fix_func: Any = None,
    ) -> None:
        checks.append((name, passed, detail, auto_fixable, fix_func))

    # 1. python3 >= 3.10
    major, minor = sys.version_info.major, sys.version_info.minor
    py_ok = major >= 3 and minor >= 10
    _add_check("python3 >= 3.10", py_ok, f"Python {major}.{minor}.{sys.version_info.micro}")

    # 2. Python packages (auto-fixable)
    def _fix_python_deps() -> str:
        installed = ensure_python_deps()
        return f"Installed: {', '.join(installed)}" if installed else "All present"

    try:
        ensure_python_deps()
        _add_check("Python packages", True, "All required packages importable")
    except SystemExit:
        _add_check("Python packages", False, "Missing packages", True, _fix_python_deps)

    # 3. claude CLI
    claude_ok, claude_msg = _check_binary("claude")
    _add_check("claude CLI", claude_ok, claude_msg)

    # 4. git
    git_ok, git_msg = _check_binary("git")
    _add_check("git", git_ok, git_msg)

    # 5. node/npx
    node_ok, node_msg = _check_binary("node")
    _add_check("node", node_ok, node_msg)
    npx_ok, npx_msg = _check_binary("npx")
    _add_check("npx", npx_ok, npx_msg)

    # Config-level checks (only if scope-tracker dir found)
    if st_dir:
        # .mcp.json exists and has slack key
        mcp_path = os.path.join(st_dir, ".mcp.json")
        mcp_data: dict = {}
        if os.path.isfile(mcp_path):
            try:
                with open(mcp_path, "r", encoding="utf-8") as f:
                    mcp_data = json.load(f)
            except (json.JSONDecodeError, OSError):
                _add_check(".mcp.json", False, "File exists but is not valid JSON")

        mcp_servers = mcp_data.get("mcpServers", {})
        _add_check(".mcp.json exists", os.path.isfile(mcp_path),
                    mcp_path if os.path.isfile(mcp_path) else "Not found — run 'scope-tracker init'")
        _add_check(".mcp.json has 'slack'", "slack" in mcp_servers,
                    "Present" if "slack" in mcp_servers else "Missing — run 'scope-tracker init'")

        # Load config for project checks
        config_path = os.path.join(st_dir, "scope_tracker_config.json")
        config: dict = {}
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _add_check("scope_tracker_config.json", False, "Could not read config")

        projects = config.get("projects", [])

        # Check if gdrive/confluence needed
        needs_gdrive = any(
            p.get("prd_source", {}).get("type") == "google-drive"
            for p in projects if p.get("enabled", True)
        )
        needs_confluence = any(
            p.get("prd_source", {}).get("type") == "confluence"
            for p in projects if p.get("enabled", True)
        )

        if needs_gdrive:
            has_gdrive = "gdrive" in mcp_servers
            _add_check(".mcp.json has 'gdrive'", has_gdrive,
                        "Present" if has_gdrive else "Missing — a project uses Google Drive. Run 'scope-tracker init'.")

        if needs_confluence:
            has_conf = "confluence" in mcp_servers
            _add_check(".mcp.json has 'confluence'", has_conf,
                        "Present" if has_conf else "Missing — a project uses Confluence. Run 'scope-tracker init'.")

        # Google OAuth token check
        gs_config = config.get("google_sheets", {})
        client_secret_path = gs_config.get("client_secret_path", "")
        if client_secret_path:
            token_path = os.path.join(st_dir, "token.json")
            token_ok = os.path.isfile(token_path)

            def _fix_oauth_token() -> str:
                from scope_tracker.scripts.dependency_manager import ensure_google_oauth_token
                ok = ensure_google_oauth_token(config, st_dir)
                return "Token created via browser consent" if ok else "Failed to create token"

            _add_check(
                "Google OAuth token",
                token_ok,
                "Present" if token_ok else "Missing — will be created on next Google Sheets operation",
                auto_fixable=not token_ok,
                fix_func=_fix_oauth_token if not token_ok else None,
            )

        # Per-project checks
        enabled_projects = [p for p in projects if p.get("enabled", True)]
        for p in enabled_projects:
            pname = p["name"]
            pfolder = os.path.join(st_dir, p.get("folder", pname))

            # Folder exists (auto-fixable)
            folder_exists = os.path.isdir(pfolder)

            def _make_fix_folder(path: str, name: str):
                def _fix() -> str:
                    ensure_directories(st_dir, [name])
                    return f"Created {path}"
                return _fix

            _add_check(
                f"Project '{pname}' folder",
                folder_exists,
                pfolder if folder_exists else f"Missing",
                auto_fixable=not folder_exists,
                fix_func=_make_fix_folder(pfolder, pname) if not folder_exists else None,
            )

            # run_state.json valid
            state_path = os.path.join(pfolder, "system", f"{pname}_run_state.json")
            if os.path.isfile(state_path):
                try:
                    with open(state_path, "r", encoding="utf-8") as f:
                        json.load(f)
                    _add_check(f"Project '{pname}' run_state.json", True, "Valid JSON")
                except json.JSONDecodeError:
                    _add_check(f"Project '{pname}' run_state.json", False, "Invalid JSON")
            else:
                _add_check(f"Project '{pname}' run_state.json", True, "Not yet created (first run pending)")

            # sheet_url set
            sheet_url = p.get("sheet_url", "")
            has_sheet = bool(sheet_url)
            _add_check(f"Project '{pname}' sheet_url", has_sheet,
                        sheet_url if has_sheet else "Not set — run 'scope-tracker init-sheet'")
    else:
        _add_check("scope-tracker/ directory", False,
                    "Not found — run 'scope-tracker init' first")

    # Auto-fix pass (if --fix flag provided)
    if fix:
        for i, (name, passed, detail, auto_fixable, fix_func) in enumerate(checks):
            if not passed and auto_fixable and fix_func:
                try:
                    result_msg = fix_func()
                    checks[i] = (name, True, f"Auto-fixed: {result_msg}", False, None)
                    fixed.append(name)
                except Exception as e:
                    checks[i] = (name, False, f"Auto-fix failed: {e}", False, None)

    # Print results
    table = Table(title="Doctor — Diagnostic Check")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    any_failed = False
    any_fixable = False
    for name, passed, detail, auto_fixable, _ in checks:
        if passed:
            status_str = "[green]✓ Pass[/green]"
        else:
            if auto_fixable:
                status_str = "[yellow]✗ Fixable[/yellow]"
                any_fixable = True
            else:
                status_str = "[red]✗ Fail[/red]"
            any_failed = True
        table.add_row(name, status_str, detail)

    console.print(table)

    if fixed:
        console.print(f"\n[green bold]Auto-fixed {len(fixed)} issue(s): {', '.join(fixed)}[/green bold]")

    if any_failed:
        if any_fixable and not fix:
            console.print("\n[yellow]Some issues can be auto-fixed. Run: scope-tracker doctor --fix[/yellow]")
        console.print("\n[red bold]Some checks failed. See details above.[/red bold]")
        raise SystemExit(1)
    else:
        console.print("\n[green bold]All checks passed.[/green bold]")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_binary(name: str) -> tuple[bool, str]:
    """Check if a binary is available on PATH.

    Args:
        name: Binary name to check.

    Returns:
        Tuple of (found, message).
    """
    try:
        result = subprocess.run(
            [name, "--version"],
            capture_output=True, text=True, timeout=15,
        )
        version = (result.stdout.strip() or result.stderr.strip()).split("\n")[0]
        return True, version
    except FileNotFoundError:
        return False, f"{name} not found on PATH"
    except subprocess.TimeoutExpired:
        return False, f"{name} timed out"
    except Exception as exc:
        return False, str(exc)


def _find_scope_tracker_dir() -> str | None:
    """Find the scope-tracker/ directory.

    Searches for scope-tracker/ in the current directory, or checks if
    the current directory itself is named scope-tracker.

    Returns:
        Absolute path to scope-tracker/ directory, or None if not found.
    """
    cwd = os.getcwd()

    # Check if we're inside scope-tracker/
    if os.path.basename(cwd) == "scope-tracker":
        config_path = os.path.join(cwd, "scope_tracker_config.json")
        if os.path.isfile(config_path):
            return cwd

    # Check for scope-tracker/ in current directory
    st_dir = os.path.join(cwd, "scope-tracker")
    if os.path.isdir(st_dir):
        config_path = os.path.join(st_dir, "scope_tracker_config.json")
        if os.path.isfile(config_path):
            return st_dir

    return None
