"""Installer module for scope-tracker.

Handles dependency checks, directory scaffolding, MCP wizard prompts,
and config file generation during `scope-tracker init` and `scope-tracker add`.
"""

import json
import os
import shutil
import subprocess
import sys
from importlib import resources
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console(stderr=True)


# ---------------------------------------------------------------------------
# 6.1 — Dependency checking
# ---------------------------------------------------------------------------

def _check_binary(name: str, version_flag: str = "--version") -> dict[str, Any]:
    """Check if a binary is available on PATH and return version info."""
    try:
        result = subprocess.run(
            [name, version_flag],
            capture_output=True, text=True, timeout=15,
        )
        version_str = (result.stdout.strip() or result.stderr.strip()).split("\n")[0]
        return {"tool": name, "found": True, "message": version_str, "install_url": ""}
    except FileNotFoundError:
        return {"tool": name, "found": False, "message": f"{name} not found on PATH", "install_url": ""}
    except subprocess.TimeoutExpired:
        return {"tool": name, "found": False, "message": f"{name} timed out", "install_url": ""}
    except Exception as exc:
        return {"tool": name, "found": False, "message": str(exc), "install_url": ""}


def _check_python_version() -> dict[str, Any]:
    """Check python3 >= 3.10."""
    major, minor = sys.version_info.major, sys.version_info.minor
    if major >= 3 and minor >= 10:
        return {
            "tool": "python3",
            "found": True,
            "message": f"Python {major}.{minor}.{sys.version_info.micro}",
            "install_url": "",
        }
    return {
        "tool": "python3",
        "found": False,
        "message": f"Python {major}.{minor} found — 3.10+ required",
        "install_url": "https://www.python.org/downloads/",
    }


def check_dependencies() -> list[dict[str, Any]]:
    """Check all required dependencies and return results.

    Checks in order: python3 >= 3.10, claude CLI, git, node/npx.
    Prints a rich table of results. Raises SystemExit if any required
    dependency is missing.

    Returns:
        List of dicts with keys: tool, found, message, install_url
    """
    results: list[dict[str, Any]] = []

    # 1. Python >= 3.10
    results.append(_check_python_version())

    # 2. claude CLI
    claude_result = _check_binary("claude")
    if not claude_result["found"]:
        claude_result["install_url"] = "https://claude.ai/code"
        claude_result["message"] = (
            "Claude Code CLI not found. "
            "Install from https://claude.ai/code"
        )
    results.append(claude_result)

    # 3. git
    git_result = _check_binary("git")
    if not git_result["found"]:
        git_result["install_url"] = "https://git-scm.com/downloads"
    results.append(git_result)

    # 4. node / npx (needed for MCP servers)
    node_result = _check_binary("node")
    if not node_result["found"]:
        node_result["install_url"] = "https://nodejs.org/"
        node_result["message"] = (
            "Node.js not found — required for MCP servers. "
            "Install from https://nodejs.org/"
        )
    results.append(node_result)

    npx_result = _check_binary("npx")
    if not npx_result["found"]:
        npx_result["install_url"] = "https://nodejs.org/"
    results.append(npx_result)

    # Print table
    table = Table(title="Dependency Check")
    table.add_column("Tool", style="bold")
    table.add_column("Status")
    table.add_column("Details")

    any_missing = False
    for r in results:
        if r["found"]:
            status = "[green]✓ Found[/green]"
        else:
            status = "[red]✗ Missing[/red]"
            any_missing = True
        table.add_row(r["tool"], status, r["message"])

    console.print(table)

    if any_missing:
        console.print("\n[red bold]Missing dependencies detected. Install them and try again.[/red bold]")
        raise SystemExit(1)

    console.print("\n[green]All dependencies found. Setting up scope-tracker...[/green]")
    return results


# ---------------------------------------------------------------------------
# 6.2 — Directory scaffolding
# ---------------------------------------------------------------------------

def scaffold_directories(base_path: str) -> str:
    """Create the scope-tracker directory structure and copy package files.

    Creates scope-tracker/ with scripts/, prompts/, .gitignore.
    Copies all files from the installed package's scripts/ and prompts/
    into the right places.

    Args:
        base_path: Parent directory where scope-tracker/ will be created.

    Returns:
        Absolute path to the created scope-tracker/ directory.
    """
    base_path = os.path.expanduser(os.path.abspath(base_path))
    st_dir = os.path.join(base_path, "scope-tracker")
    scripts_dir = os.path.join(st_dir, "scripts")
    prompts_dir = os.path.join(st_dir, "prompts")

    os.makedirs(scripts_dir, exist_ok=True)
    os.makedirs(prompts_dir, exist_ok=True)

    # Copy scripts from installed package
    pkg_scripts = resources.files("scope_tracker") / "scripts"
    for item in pkg_scripts.iterdir():
        name = item.name
        if name.startswith("__") or name.endswith(".pyc") or name == ".gitkeep":
            continue
        dest = os.path.join(scripts_dir, name)
        content = item.read_text(encoding="utf-8")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)

    # Copy prompts from installed package
    pkg_prompts = resources.files("scope_tracker") / "prompts"
    for item in pkg_prompts.iterdir():
        name = item.name
        if name.startswith("__") or name.endswith(".pyc") or name == ".gitkeep":
            continue
        dest = os.path.join(prompts_dir, name)
        content = item.read_text(encoding="utf-8")
        with open(dest, "w", encoding="utf-8") as f:
            f.write(content)

    return st_dir


# ---------------------------------------------------------------------------
# 6.3 — Slack MCP wizard
# ---------------------------------------------------------------------------

def run_slack_mcp_wizard() -> dict[str, str]:
    """Prompt user for Slack MCP credentials.

    Collects SLACK_BOT_TOKEN and SLACK_TEAM_ID interactively.
    Validates token format (must start with xoxb-).

    Returns:
        Dict with 'SLACK_BOT_TOKEN' and 'SLACK_TEAM_ID' keys.
    """
    console.print(Panel(
        "[bold]Slack MCP Configuration[/bold]\n\n"
        "You need a Slack Bot Token and Team ID.\n"
        "To create a Slack bot, visit: [link]https://api.slack.com/apps[/link]",
        title="Slack Setup",
    ))

    while True:
        token = click.prompt("Enter your Slack Bot Token (xoxb-...)", type=str).strip()
        if token.startswith("xoxb-"):
            break
        console.print("[red]Token must start with 'xoxb-'. Please try again.[/red]")

    team_id = click.prompt("Enter your Slack Team ID (T...)", type=str).strip()

    return {"SLACK_BOT_TOKEN": token, "SLACK_TEAM_ID": team_id}


# ---------------------------------------------------------------------------
# 6.4 — GDrive MCP wizard
# ---------------------------------------------------------------------------

def run_gdrive_mcp_wizard() -> dict[str, str]:
    """Prompt user for Google Drive MCP credentials.

    Asks for the path to a Google credentials JSON file.
    Validates the file exists and contains 'client_id'.

    Returns:
        Dict with 'GDRIVE_CREDENTIALS_FILE' key.
    """
    console.print(Panel(
        "[bold]Google Drive MCP Configuration[/bold]\n\n"
        "You need a Google OAuth2 credentials JSON file.\n"
        "Create one at: [link]https://console.cloud.google.com[/link]\n"
        "Go to APIs & Services → Credentials → Create OAuth client ID → Desktop app.\n"
        "Download the JSON file.",
        title="Google Drive Setup",
    ))

    while True:
        cred_path = click.prompt(
            "Path to your Google credentials JSON file", type=str,
        ).strip()
        cred_path = os.path.expanduser(os.path.abspath(cred_path))

        if not os.path.isfile(cred_path):
            console.print(f"[red]File not found: {cred_path}[/red]")
            continue

        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                cred_data = json.load(f)
            # Check for client_id in top-level or inside "installed"/"web" key
            has_client_id = (
                "client_id" in cred_data
                or "client_id" in cred_data.get("installed", {})
                or "client_id" in cred_data.get("web", {})
            )
            if not has_client_id:
                console.print("[red]JSON file does not contain a 'client_id' key. Please provide valid OAuth credentials.[/red]")
                continue
            break
        except json.JSONDecodeError:
            console.print("[red]File is not valid JSON. Please try again.[/red]")
            continue

    return {"GDRIVE_CREDENTIALS_FILE": cred_path}


# ---------------------------------------------------------------------------
# 6.5 — Confluence MCP wizard
# ---------------------------------------------------------------------------

def run_confluence_mcp_wizard() -> dict[str, str]:
    """Prompt user for Confluence MCP credentials.

    Collects Atlassian site name, user email, and API token.
    Uses @aashari/mcp-server-atlassian-confluence package.

    Returns:
        Dict with 'ATLASSIAN_SITE_NAME', 'ATLASSIAN_USER_EMAIL', 'ATLASSIAN_API_TOKEN' keys.
    """
    console.print(Panel(
        "[bold]Confluence MCP Configuration[/bold]\n\n"
        "You need your Atlassian site name, email, and an API token.\n"
        "Create an API token at: [link]https://id.atlassian.com[/link]\n"
        "Go to Security → API tokens → Create API token.",
        title="Confluence Setup",
    ))

    while True:
        site_name = click.prompt(
            "Atlassian site name (e.g. 'yourteam' from yourteam.atlassian.net)",
            type=str,
        ).strip()
        if site_name and "." not in site_name and "/" not in site_name:
            break
        console.print("[red]Enter just the site name (e.g. 'yourteam'), not the full URL.[/red]")

    email = click.prompt("Atlassian user email", type=str).strip()
    api_token = click.prompt("Atlassian API token", type=str).strip()

    return {
        "ATLASSIAN_SITE_NAME": site_name,
        "ATLASSIAN_USER_EMAIL": email,
        "ATLASSIAN_API_TOKEN": api_token,
    }


# ---------------------------------------------------------------------------
# 6.6 — Write .mcp.json
# ---------------------------------------------------------------------------

def write_mcp_config(base_path: str, mcp_config: dict[str, Any]) -> str:
    """Write .mcp.json to the scope-tracker directory.

    Always includes 'slack'. Includes 'gdrive' only if provided.
    Includes 'confluence' only if provided.

    Args:
        base_path: Path to scope-tracker/ directory.
        mcp_config: Dict with keys 'slack' (required), optionally 'gdrive', 'confluence'.

    Returns:
        Path to the written .mcp.json file.
    """
    base_path = os.path.expanduser(os.path.abspath(base_path))
    mcp_path = os.path.join(base_path, ".mcp.json")

    servers: dict[str, Any] = {}

    # Slack is always included
    if "slack" in mcp_config:
        servers["slack"] = {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-slack"],
            "env": mcp_config["slack"],
        }

    # GDrive only if configured
    if "gdrive" in mcp_config:
        servers["gdrive"] = {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-gdrive"],
            "env": mcp_config["gdrive"],
        }

    # Confluence only if configured
    if "confluence" in mcp_config:
        servers["confluence"] = {
            "command": "npx",
            "args": ["-y", "@aashari/mcp-server-atlassian-confluence"],
            "env": mcp_config["confluence"],
        }

    output = {"mcpServers": servers}

    with open(mcp_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    return mcp_path


# ---------------------------------------------------------------------------
# 6.7 — Project wizard
# ---------------------------------------------------------------------------

def run_project_wizard(existing_mcp_servers: list[str]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Run interactive project setup wizard.

    Prompts for project name, Slack channel, PRD source configuration.
    Triggers MCP wizard for new MCP servers not already configured.

    Args:
        existing_mcp_servers: List of MCP server names already in .mcp.json
            (e.g. ['slack', 'gdrive']).

    Returns:
        Tuple of (project_config_dict, new_mcp_config_or_None).
        new_mcp_config is a dict like {'gdrive': {...}} if a new MCP server
        was configured, otherwise None.
    """
    console.print(Panel("[bold]Add a New Project[/bold]", title="Project Setup"))

    # Project name
    while True:
        name = click.prompt(
            "Project name (used as folder name, lowercase, no spaces)",
            type=str,
        ).strip().lower().replace(" ", "-")
        if name:
            break
        console.print("[red]Name cannot be empty.[/red]")

    # Slack channel
    slack_channel = click.prompt(
        "Slack channel to monitor for scope decisions (no # prefix)",
        type=str,
    ).strip().lstrip("#")

    # PRD source
    console.print("\nPRD source — where does your PRD live?")
    console.print("  [1] Google Doc")
    console.print("  [2] Confluence page")
    console.print("  [3] None")
    prd_choice = click.prompt("Choose", type=click.IntRange(1, 3))

    prd_source: dict[str, Any] = {"type": "none", "url": "", "last_modified": None}
    new_mcp: dict[str, Any] | None = None

    if prd_choice == 1:
        # Google Doc
        while True:
            doc_url = click.prompt("Paste the Google Doc URL", type=str).strip()
            if doc_url.startswith("https://docs.google.com/document/"):
                break
            console.print("[red]URL must start with 'https://docs.google.com/document/'. Try again.[/red]")

        prd_source = {
            "type": "google-drive",
            "url": doc_url,
            "last_modified": None,
        }

        # Check if GDrive MCP is already configured
        if "gdrive" not in existing_mcp_servers:
            console.print("\n[yellow]Google Drive MCP not yet configured. Setting it up now...[/yellow]")
            gdrive_creds = run_gdrive_mcp_wizard()
            new_mcp = {"gdrive": gdrive_creds}

    elif prd_choice == 2:
        # Confluence
        while True:
            conf_url = click.prompt("Paste the Confluence page URL", type=str).strip()
            if conf_url.startswith("https://"):
                break
            console.print("[red]URL must start with 'https://'. Try again.[/red]")

        prd_source = {
            "type": "confluence",
            "url": conf_url,
            "last_modified": None,
        }

        # Check if Confluence MCP is already configured
        if "confluence" not in existing_mcp_servers:
            console.print("\n[yellow]Confluence MCP not yet configured. Setting it up now...[/yellow]")
            conf_creds = run_confluence_mcp_wizard()
            new_mcp = {"confluence": conf_creds}

    project_config = {
        "name": name,
        "enabled": True,
        "folder": name,
        "slack_channel": slack_channel,
        "sheet_url": "",
        "prd_source": prd_source,
        "slack_last_run_timestamp": None,
        "run_count": 0,
        "last_run_date": None,
    }

    return project_config, new_mcp


# ---------------------------------------------------------------------------
# 6.8 — Write config
# ---------------------------------------------------------------------------

def write_config(base_path: str, config: dict[str, Any]) -> str:
    """Write scope_tracker_config.json to the given directory.

    Creates an empty projects list if none exists in the config.

    Args:
        base_path: Path to scope-tracker/ directory.
        config: Full configuration dict.

    Returns:
        Path to the written config file.
    """
    base_path = os.path.expanduser(os.path.abspath(base_path))
    config_path = os.path.join(base_path, "scope_tracker_config.json")

    if "projects" not in config:
        config["projects"] = []

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    return config_path


def load_config(config_path: str) -> dict[str, Any]:
    """Load scope_tracker_config.json from disk.

    Args:
        config_path: Absolute path to the config file.

    Returns:
        Parsed configuration dict.

    Raises:
        FileNotFoundError: If the config file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    config_path = os.path.expanduser(os.path.abspath(config_path))
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_path}")
    except json.JSONDecodeError as exc:
        raise json.JSONDecodeError(
            f"Invalid JSON in config file: {config_path}", exc.doc, exc.pos,
        )


# ---------------------------------------------------------------------------
# 6.9 — Write .gitignore
# ---------------------------------------------------------------------------

def write_gitignore(base_path: str) -> str:
    """Write .gitignore to the scope-tracker directory.

    Includes all entries specified in the project requirements.

    Args:
        base_path: Path to scope-tracker/ directory.

    Returns:
        Path to the written .gitignore file.
    """
    base_path = os.path.expanduser(os.path.abspath(base_path))
    gitignore_path = os.path.join(base_path, ".gitignore")

    entries = [
        ".mcp.json",
        "*.xlsx",
        "outputs/",
        "system/",
        "__pycache__/",
        "*.pyc",
        ".env",
        "dist/",
        "*.egg-info/",
        "credentials.json",
        "token.json",
        ".venv/",
    ]

    with open(gitignore_path, "w", encoding="utf-8") as f:
        f.write("\n".join(entries))
        f.write("\n")

    return gitignore_path


# ---------------------------------------------------------------------------
# Helper — create project folder structure
# ---------------------------------------------------------------------------

def create_project_folders(base_path: str, project_name: str) -> str:
    """Create the folder structure for a new project.

    Creates {base_path}/{project_name}/system/ and {base_path}/{project_name}/outputs/.

    Args:
        base_path: Path to scope-tracker/ directory.
        project_name: Name of the project (used as folder name).

    Returns:
        Path to the project directory.
    """
    base_path = os.path.expanduser(os.path.abspath(base_path))
    project_dir = os.path.join(base_path, project_name)
    os.makedirs(os.path.join(project_dir, "system"), exist_ok=True)
    os.makedirs(os.path.join(project_dir, "outputs"), exist_ok=True)
    return project_dir


# ---------------------------------------------------------------------------
# Helper — build default config
# ---------------------------------------------------------------------------

def build_default_config(
    reporting_channel: str = "scope-tracker",
    timezone: str = "Asia/Kolkata",
) -> dict[str, Any]:
    """Build a default scope_tracker_config.json structure.

    Args:
        reporting_channel: Slack channel for run reports.
        timezone: Default timezone string.

    Returns:
        Config dict ready to have projects appended.
    """
def run_google_sheets_wizard() -> dict[str, str]:
    """Prompt user for Google Sheets OAuth2 client_secret.json path.

    Validates the file exists and contains a client_id key.

    Returns:
        Dict with 'client_secret_path' key.
    """
    console.print(Panel(
        "[bold]Google Sheets Configuration[/bold]\n\n"
        "You need a Google OAuth2 client_secret.json file for Sheets access.\n"
        "Create one at: [link]https://console.cloud.google.com[/link]\n"
        "Go to APIs & Services → Credentials → Create OAuth client ID → Desktop app.\n"
        "Enable the Google Sheets API for your project.\n"
        "Download the JSON file.",
        title="Google Sheets Setup",
    ))

    while True:
        cred_path = click.prompt(
            "Path to your Google client_secret.json file", type=str,
        ).strip()
        cred_path = os.path.expanduser(os.path.abspath(cred_path))

        if not os.path.isfile(cred_path):
            console.print(f"[red]File not found: {cred_path}[/red]")
            continue

        try:
            with open(cred_path, "r", encoding="utf-8") as f:
                cred_data = json.load(f)
            has_client_id = (
                "client_id" in cred_data
                or "client_id" in cred_data.get("installed", {})
                or "client_id" in cred_data.get("web", {})
            )
            if not has_client_id:
                console.print("[red]JSON file does not contain a 'client_id' key. "
                              "Please provide valid OAuth credentials.[/red]")
                continue
            break
        except json.JSONDecodeError:
            console.print("[red]File is not valid JSON. Please try again.[/red]")
            continue

    return {"client_secret_path": cred_path}


def build_default_config(
    reporting_channel: str = "scope-tracker",
    timezone: str = "Asia/Kolkata",
    google_sheets_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a default scope_tracker_config.json structure.

    Args:
        reporting_channel: Slack channel for run reports.
        timezone: Default timezone string.
        google_sheets_config: Google Sheets config dict with client_secret_path.

    Returns:
        Config dict ready to have projects appended.
    """
    return {
        "global_settings": {
            "reporting_slack_channel": reporting_channel,
            "reporting_slack_last_read": None,
            "default_timezone": timezone,
        },
        "sheet_config": {
            "uat_rounds": 5,
            "status_options": [
                "To be tested",
                "Passed",
                "Passed with iteration",
                "Failed",
                "Blocked",
            ],
            "version_options": [
                "LIVE",
                "Next release",
                "Parked",
                "Fast follower",
            ],
            "scope_decision_options": [
                "In Scope",
                "Fast Follower",
                "Pushed to V2",
                "Parked",
                "Active Blocker",
                "Conflicting Signal",
            ],
            "blocker_options": ["Yes", "No"],
            "prd_identifier_column_names": ["ID", "Identifier", "#", "Ref"],
            "prd_story_column_names": [
                "User Story",
                "Story",
                "Feature",
                "Requirement",
                "Description",
            ],
        },
        "google_sheets": google_sheets_config or {},
        "projects": [],
    }
