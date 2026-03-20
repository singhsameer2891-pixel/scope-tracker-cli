"""Tests for scope_tracker.installer module.

Covers: dependency checks, directory scaffolding, MCP config writing,
config roundtrip, project wizard, and gitignore generation.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from scope_tracker.installer import (
    build_default_config,
    check_dependencies,
    create_project_folders,
    load_config,
    run_project_wizard,
    scaffold_directories,
    write_config,
    write_gitignore,
    write_mcp_config,
)


# ---------------------------------------------------------------------------
# (a) check_dependencies detects missing binary
# ---------------------------------------------------------------------------

class TestCheckDependencies:
    """Tests for check_dependencies()."""

    @patch("scope_tracker.installer.subprocess.run")
    def test_all_found(self, mock_run: MagicMock) -> None:
        """When all binaries exist, returns all found=True and no SystemExit."""
        mock_run.return_value = MagicMock(
            stdout="v1.0.0\n", stderr="", returncode=0,
        )
        results = check_dependencies()
        assert all(r["found"] for r in results if r["tool"] != "python3")
        # python3 check uses sys.version_info, not subprocess
        python_result = [r for r in results if r["tool"] == "python3"][0]
        assert python_result["found"] is True

    @patch("scope_tracker.installer.subprocess.run")
    def test_missing_claude(self, mock_run: MagicMock) -> None:
        """When claude binary is missing, raises SystemExit."""
        def side_effect(cmd, **kwargs):
            if cmd[0] == "claude":
                raise FileNotFoundError("claude not found")
            return MagicMock(stdout="v1.0.0\n", stderr="", returncode=0)

        mock_run.side_effect = side_effect
        with pytest.raises(SystemExit):
            check_dependencies()

    @patch("scope_tracker.installer.subprocess.run")
    def test_missing_node(self, mock_run: MagicMock) -> None:
        """When node is missing, raises SystemExit."""
        def side_effect(cmd, **kwargs):
            if cmd[0] in ("node", "npx"):
                raise FileNotFoundError(f"{cmd[0]} not found")
            return MagicMock(stdout="v1.0.0\n", stderr="", returncode=0)

        mock_run.side_effect = side_effect
        with pytest.raises(SystemExit):
            check_dependencies()

    @patch("scope_tracker.installer.subprocess.run")
    def test_returns_correct_structure(self, mock_run: MagicMock) -> None:
        """Results have correct dict structure."""
        mock_run.return_value = MagicMock(
            stdout="v1.0.0\n", stderr="", returncode=0,
        )
        results = check_dependencies()
        for r in results:
            assert "tool" in r
            assert "found" in r
            assert "message" in r
            assert "install_url" in r


# ---------------------------------------------------------------------------
# (b) scaffold creates correct directory tree
# ---------------------------------------------------------------------------

class TestScaffoldDirectories:
    """Tests for scaffold_directories()."""

    def test_creates_directory_structure(self, tmp_path: object) -> None:
        """Creates scope-tracker/ with scripts/ and prompts/ subdirectories."""
        base = str(tmp_path)
        st_dir = scaffold_directories(base)

        assert os.path.isdir(st_dir)
        assert os.path.basename(st_dir) == "scope-tracker"
        assert os.path.isdir(os.path.join(st_dir, "scripts"))
        assert os.path.isdir(os.path.join(st_dir, "prompts"))

    def test_copies_script_files(self, tmp_path: object) -> None:
        """Copies Python script files from the package into scripts/."""
        base = str(tmp_path)
        st_dir = scaffold_directories(base)
        scripts_dir = os.path.join(st_dir, "scripts")

        expected_scripts = [
            "diff_prd.py",
            "diff_slack.py",
            "update_state.py",
            "run_pipeline.py",
            "sheet_manager.py",
            "conflict_manager.py",
            "call_llm.py",
        ]
        for script in expected_scripts:
            assert os.path.isfile(os.path.join(scripts_dir, script)), f"Missing: {script}"

    def test_copies_prompt_files(self, tmp_path: object) -> None:
        """Copies prompt .md files from the package into prompts/."""
        base = str(tmp_path)
        st_dir = scaffold_directories(base)
        prompts_dir = os.path.join(st_dir, "prompts")

        expected_prompts = [
            "prd_fetch_meta.md",
            "prd_fetch_content.md",
            "prd_extract.md",
            "slack_fetch.md",
            "slack_classify.md",
            "slack_match.md",
            "conflict_resolve.md",
            "slack_report.md",
        ]
        for prompt in expected_prompts:
            assert os.path.isfile(os.path.join(prompts_dir, prompt)), f"Missing: {prompt}"

    def test_idempotent(self, tmp_path: object) -> None:
        """Running scaffold twice does not fail."""
        base = str(tmp_path)
        scaffold_directories(base)
        st_dir = scaffold_directories(base)
        assert os.path.isdir(st_dir)


# ---------------------------------------------------------------------------
# (c) write_mcp_config omits gdrive block when not needed
# ---------------------------------------------------------------------------

class TestWriteMcpConfig:
    """Tests for write_mcp_config()."""

    def test_slack_only(self, tmp_path: object) -> None:
        """When only slack creds provided, .mcp.json has no gdrive or confluence."""
        base = str(tmp_path)
        mcp_config = {
            "slack": {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_TEAM_ID": "T123"},
        }
        path = write_mcp_config(base, mcp_config)
        with open(path) as f:
            data = json.load(f)

        assert "slack" in data["mcpServers"]
        assert "gdrive" not in data["mcpServers"]
        assert "confluence" not in data["mcpServers"]

    def test_includes_gdrive(self, tmp_path: object) -> None:
        """When gdrive creds provided, .mcp.json includes gdrive block."""
        base = str(tmp_path)
        mcp_config = {
            "slack": {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_TEAM_ID": "T123"},
            "gdrive": {"GDRIVE_CREDENTIALS_FILE": "/path/to/creds.json"},
        }
        path = write_mcp_config(base, mcp_config)
        with open(path) as f:
            data = json.load(f)

        assert "gdrive" in data["mcpServers"]
        assert data["mcpServers"]["gdrive"]["env"]["GDRIVE_CREDENTIALS_FILE"] == "/path/to/creds.json"

    def test_includes_confluence(self, tmp_path: object) -> None:
        """When confluence creds provided, .mcp.json includes confluence block."""
        base = str(tmp_path)
        mcp_config = {
            "slack": {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_TEAM_ID": "T123"},
            "confluence": {
                "CONFLUENCE_URL": "https://team.atlassian.net/wiki",
                "CONFLUENCE_USERNAME": "user@example.com",
                "CONFLUENCE_API_TOKEN": "tok-123",
            },
        }
        path = write_mcp_config(base, mcp_config)
        with open(path) as f:
            data = json.load(f)

        assert "confluence" in data["mcpServers"]

    def test_mcp_server_structure(self, tmp_path: object) -> None:
        """Each MCP server entry has command, args, and env."""
        base = str(tmp_path)
        mcp_config = {
            "slack": {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_TEAM_ID": "T123"},
        }
        path = write_mcp_config(base, mcp_config)
        with open(path) as f:
            data = json.load(f)

        slack = data["mcpServers"]["slack"]
        assert slack["command"] == "npx"
        assert isinstance(slack["args"], list)
        assert "@modelcontextprotocol/server-slack" in slack["args"]
        assert slack["env"]["SLACK_BOT_TOKEN"] == "xoxb-test"


# ---------------------------------------------------------------------------
# (d) write_config roundtrip
# ---------------------------------------------------------------------------

class TestWriteConfig:
    """Tests for write_config() and load_config()."""

    def test_roundtrip(self, tmp_path: object) -> None:
        """Config written and loaded back is identical."""
        base = str(tmp_path)
        config = build_default_config()
        config["projects"].append({
            "name": "test-project",
            "enabled": True,
            "folder": "test-project",
            "slack_channel": "test-scope",
            "sheet_url": "",
            "prd_source": {"type": "none", "url": "", "last_modified": None},
            "slack_last_run_timestamp": None,
            "run_count": 0,
            "last_run_date": None,
        })

        config_path = write_config(base, config)
        loaded = load_config(config_path)

        assert loaded == config

    def test_creates_empty_projects_if_missing(self, tmp_path: object) -> None:
        """If config has no 'projects' key, write_config creates an empty list."""
        base = str(tmp_path)
        config = {"global_settings": {"reporting_slack_channel": "test"}}
        config_path = write_config(base, config)
        loaded = load_config(config_path)
        assert loaded["projects"] == []

    def test_load_missing_file_raises(self, tmp_path: object) -> None:
        """Loading a non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config(os.path.join(str(tmp_path), "nonexistent.json"))


# ---------------------------------------------------------------------------
# (e) project wizard returns correct dict structure
# ---------------------------------------------------------------------------

class TestProjectWizard:
    """Tests for run_project_wizard()."""

    @patch("scope_tracker.installer.click.prompt")
    def test_returns_correct_structure_no_prd(self, mock_prompt: MagicMock) -> None:
        """With PRD type 'none', returns project config without MCP trigger."""
        # Simulate: name="myapp", channel="myapp-scope", prd_choice=3 (none)
        mock_prompt.side_effect = ["myapp", "myapp-scope", 3]

        project_config, new_mcp = run_project_wizard(["slack"])

        assert project_config["name"] == "myapp"
        assert project_config["enabled"] is True
        assert project_config["folder"] == "myapp"
        assert project_config["slack_channel"] == "myapp-scope"
        assert project_config["prd_source"]["type"] == "none"
        assert project_config["run_count"] == 0
        assert new_mcp is None

    @patch("scope_tracker.installer.run_gdrive_mcp_wizard")
    @patch("scope_tracker.installer.click.prompt")
    def test_google_drive_triggers_gdrive_wizard(
        self, mock_prompt: MagicMock, mock_gdrive: MagicMock,
    ) -> None:
        """When Google Doc selected and gdrive not in existing MCP, triggers wizard."""
        mock_prompt.side_effect = [
            "myapp",
            "myapp-scope",
            1,  # Google Doc
            "https://docs.google.com/document/d/abc123/edit",
        ]
        mock_gdrive.return_value = {"GDRIVE_CREDENTIALS_FILE": "/path/creds.json"}

        project_config, new_mcp = run_project_wizard(["slack"])

        assert project_config["prd_source"]["type"] == "google-drive"
        assert project_config["prd_source"]["url"] == "https://docs.google.com/document/d/abc123/edit"
        assert new_mcp is not None
        assert "gdrive" in new_mcp
        mock_gdrive.assert_called_once()

    @patch("scope_tracker.installer.click.prompt")
    def test_google_drive_skips_wizard_if_already_configured(
        self, mock_prompt: MagicMock,
    ) -> None:
        """When Google Doc selected but gdrive already in MCP, no wizard triggered."""
        mock_prompt.side_effect = [
            "myapp",
            "myapp-scope",
            1,  # Google Doc
            "https://docs.google.com/document/d/abc123/edit",
        ]

        project_config, new_mcp = run_project_wizard(["slack", "gdrive"])

        assert project_config["prd_source"]["type"] == "google-drive"
        assert new_mcp is None

    @patch("scope_tracker.installer.run_confluence_mcp_wizard")
    @patch("scope_tracker.installer.click.prompt")
    def test_confluence_triggers_wizard(
        self, mock_prompt: MagicMock, mock_conf: MagicMock,
    ) -> None:
        """When Confluence selected and not in existing MCP, triggers wizard."""
        mock_prompt.side_effect = [
            "myapp",
            "myapp-scope",
            2,  # Confluence
            "https://team.atlassian.net/wiki/spaces/PROJ/pages/123",
        ]
        mock_conf.return_value = {
            "CONFLUENCE_URL": "https://team.atlassian.net/wiki",
            "CONFLUENCE_USERNAME": "user@example.com",
            "CONFLUENCE_API_TOKEN": "tok",
        }

        project_config, new_mcp = run_project_wizard(["slack"])

        assert project_config["prd_source"]["type"] == "confluence"
        assert new_mcp is not None
        assert "confluence" in new_mcp


# ---------------------------------------------------------------------------
# Additional helper tests
# ---------------------------------------------------------------------------

class TestWriteGitignore:
    """Tests for write_gitignore()."""

    def test_contains_required_entries(self, tmp_path: object) -> None:
        """Written .gitignore contains all required entries."""
        base = str(tmp_path)
        path = write_gitignore(base)
        with open(path) as f:
            content = f.read()

        required = [
            ".mcp.json",
            "*.xlsx",
            "outputs/",
            "system/",
            "__pycache__/",
            "*.pyc",
            ".env",
            "credentials.json",
        ]
        for entry in required:
            assert entry in content, f"Missing gitignore entry: {entry}"


class TestCreateProjectFolders:
    """Tests for create_project_folders()."""

    def test_creates_system_and_outputs(self, tmp_path: object) -> None:
        """Creates project/system/ and project/outputs/ directories."""
        base = str(tmp_path)
        project_dir = create_project_folders(base, "test-project")

        assert os.path.isdir(os.path.join(project_dir, "system"))
        assert os.path.isdir(os.path.join(project_dir, "outputs"))


class TestBuildDefaultConfig:
    """Tests for build_default_config()."""

    def test_default_values(self) -> None:
        """Default config has expected structure and values."""
        config = build_default_config()
        assert config["global_settings"]["reporting_slack_channel"] == "scope-tracker"
        assert config["global_settings"]["default_timezone"] == "Asia/Kolkata"
        assert config["sheet_config"]["uat_rounds"] == 5
        assert config["projects"] == []

    def test_custom_values(self) -> None:
        """Custom channel and timezone are applied."""
        config = build_default_config(
            reporting_channel="custom-channel",
            timezone="US/Eastern",
        )
        assert config["global_settings"]["reporting_slack_channel"] == "custom-channel"
        assert config["global_settings"]["default_timezone"] == "US/Eastern"
