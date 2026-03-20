"""Tests for dependency_manager.py — self-healing dependency management.

Tests:
    (a) missing package triggers pip install
    (b) all packages present → no-op
    (c) pip failure shows user-friendly message
"""

import subprocess
from unittest import mock

import pytest

from scope_tracker.scripts.dependency_manager import (
    REQUIRED_PACKAGES,
    ensure_directories,
    ensure_python_deps,
)


class TestEnsurePythonDeps:
    """Tests for ensure_python_deps()."""

    def test_all_packages_present_returns_empty(self) -> None:
        """When all packages are importable, returns empty list."""
        # All packages in REQUIRED_PACKAGES should be importable in test env
        result = ensure_python_deps()
        assert result == []

    def test_missing_package_triggers_pip_install(self) -> None:
        """When a package is not importable, pip install is called."""
        original_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "openpyxl":
                raise ImportError("No module named 'openpyxl'")
            return original_import(name, *args, **kwargs)

        with mock.patch("importlib.import_module", side_effect=fake_import):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                result = ensure_python_deps()

        assert "openpyxl" in result
        mock_run.assert_called_once()
        # Verify pip install was called with the missing package
        call_args = mock_run.call_args[0][0]
        assert "pip" in call_args
        assert "install" in call_args
        assert "openpyxl" in call_args

    def test_multiple_missing_packages(self) -> None:
        """When multiple packages are missing, all are installed in one pip call."""
        def fake_import(name, *args, **kwargs):
            if name in ("openpyxl", "requests"):
                raise ImportError(f"No module named '{name}'")
            return __import__(name)

        with mock.patch("importlib.import_module", side_effect=fake_import):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")
                result = ensure_python_deps()

        assert "openpyxl" in result
        assert "requests" in result
        mock_run.assert_called_once()

    def test_pip_failure_exits_with_message(self, capsys: pytest.CaptureFixture) -> None:
        """When pip install fails, exits with code 1 and prints user-friendly message."""
        def fake_import(name, *args, **kwargs):
            if name == "openpyxl":
                raise ImportError("No module named 'openpyxl'")
            return __import__(name)

        with mock.patch("importlib.import_module", side_effect=fake_import):
            with mock.patch("subprocess.run") as mock_run:
                mock_run.return_value = mock.Mock(
                    returncode=1,
                    stdout="",
                    stderr="ERROR: Could not install packages",
                )
                with pytest.raises(SystemExit) as exc_info:
                    ensure_python_deps()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "pip install" in captured.err.lower() or "Please run manually" in captured.err

    def test_pip_timeout_exits_with_message(self, capsys: pytest.CaptureFixture) -> None:
        """When pip install times out, exits with code 1 and prints user-friendly message."""
        def fake_import(name, *args, **kwargs):
            if name == "openpyxl":
                raise ImportError("No module named 'openpyxl'")
            return __import__(name)

        with mock.patch("importlib.import_module", side_effect=fake_import):
            with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pip", timeout=120)):
                with pytest.raises(SystemExit) as exc_info:
                    ensure_python_deps()

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "timed out" in captured.err.lower()


class TestEnsureDirectories:
    """Tests for ensure_directories()."""

    def test_creates_missing_top_level_dirs(self, tmp_path: object) -> None:
        """Creates scripts/ and prompts/ if missing."""
        st_dir = str(tmp_path)
        created = ensure_directories(st_dir)
        assert any("scripts" in c for c in created)
        assert any("prompts" in c for c in created)

    def test_creates_project_dirs(self, tmp_path: object) -> None:
        """Creates system/ and outputs/ for each project."""
        import os

        st_dir = str(tmp_path)
        os.makedirs(os.path.join(st_dir, "scripts"))
        os.makedirs(os.path.join(st_dir, "prompts"))

        created = ensure_directories(st_dir, project_names=["demo"])
        assert any("system" in c for c in created)
        assert any("outputs" in c for c in created)

    def test_skips_existing_dirs(self, tmp_path: object) -> None:
        """Does not re-create directories that already exist."""
        import os

        st_dir = str(tmp_path)
        os.makedirs(os.path.join(st_dir, "scripts"))
        os.makedirs(os.path.join(st_dir, "prompts"))

        created = ensure_directories(st_dir)
        assert created == []
