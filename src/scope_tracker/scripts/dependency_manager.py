"""Self-healing dependency management for scope-tracker.

Automatically installs missing Python packages and resolves fixable setup
issues without asking the user. Only prompts when something genuinely
requires their input (e.g. an API token).

Functions:
    ensure_python_deps() — check and auto-install missing Python packages.
    ensure_directories(st_dir) — create missing project directories.
    ensure_google_oauth_token(config, st_dir) — handle missing/expired OAuth token.

All human-readable log output goes to stderr.
"""

import importlib
import os
import subprocess
import sys
from typing import Any


# Required packages mapped to their pip install names
REQUIRED_PACKAGES: dict[str, str] = {
    "googleapiclient": "google-api-python-client",
    "google.auth": "google-auth",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "requests": "requests",
    "openpyxl": "openpyxl",
    "click": "click",
    "rich": "rich",
}


def _log(msg: str) -> None:
    """Log a human-readable message to stderr.

    Args:
        msg: The message to log.
    """
    print(f"[dependency_manager] {msg}", file=sys.stderr)


def ensure_python_deps() -> list[str]:
    """Check if required Python packages are importable. Auto-install missing ones.

    Iterates over REQUIRED_PACKAGES, attempts to import each. If any are missing,
    runs `pip install` for them automatically. Logs what was installed to stderr.

    Returns:
        List of pip package names that were installed (empty if all present).

    Raises:
        SystemExit: If pip install fails, prints the exact command the user
            should run manually and exits with code 1.
    """
    missing: list[str] = []

    for import_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return []

    _log(f"Missing packages detected: {', '.join(missing)}. Installing...")

    pip_cmd = [sys.executable, "-m", "pip", "install"] + missing
    try:
        result = subprocess.run(
            pip_cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            _log(f"pip install failed:\n{result.stderr}")
            _log(
                f"Please run manually: {sys.executable} -m pip install {' '.join(missing)}"
            )
            sys.exit(1)
    except subprocess.TimeoutExpired:
        _log("pip install timed out after 120 seconds.")
        _log(
            f"Please run manually: {sys.executable} -m pip install {' '.join(missing)}"
        )
        sys.exit(1)
    except Exception as e:
        _log(f"pip install error: {e}")
        _log(
            f"Please run manually: {sys.executable} -m pip install {' '.join(missing)}"
        )
        sys.exit(1)

    _log(f"Installed: {', '.join(missing)}")
    return missing


def ensure_directories(st_dir: str, project_names: list[str] | None = None) -> list[str]:
    """Create any missing directories in the scope-tracker structure.

    Args:
        st_dir: Path to the scope-tracker/ directory.
        project_names: List of project names to check/create folders for.
            If None, only checks top-level dirs.

    Returns:
        List of directories that were created.
    """
    st_dir = os.path.expanduser(os.path.abspath(st_dir))
    created: list[str] = []

    # Top-level directories
    for subdir in ["scripts", "prompts"]:
        path = os.path.join(st_dir, subdir)
        if not os.path.isdir(path):
            os.makedirs(path, exist_ok=True)
            created.append(path)
            _log(f"Created missing directory: {path}")

    # Per-project directories
    if project_names:
        for name in project_names:
            for sub in ["system", "outputs"]:
                path = os.path.join(st_dir, name, sub)
                if not os.path.isdir(path):
                    os.makedirs(path, exist_ok=True)
                    created.append(path)
                    _log(f"Created missing directory: {path}")

    return created


def ensure_google_oauth_token(config: dict[str, Any], st_dir: str) -> bool:
    """Handle missing or expired Google OAuth token gracefully.

    If token.json is missing or expired, triggers the OAuth consent flow
    automatically (opens browser). Does not error with a cryptic message.

    Args:
        config: The scope_tracker_config.json contents.
        st_dir: Path to the scope-tracker/ directory.

    Returns:
        True if token is valid (either already existed or was refreshed/created).
        False if no Google Sheets config is present (nothing to do).
    """
    gs_config = config.get("google_sheets", {})
    client_secret_path = gs_config.get("client_secret_path", "")

    if not client_secret_path:
        return False

    client_secret_path = os.path.expanduser(os.path.abspath(client_secret_path))
    if not os.path.isfile(client_secret_path):
        _log(
            f"Google client_secret.json not found at: {client_secret_path}\n"
            "Run `scope-tracker init` to reconfigure Google Sheets credentials."
        )
        return False

    token_path = os.path.join(os.path.expanduser(os.path.abspath(st_dir)), "token.json")

    # Try loading existing token
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = None
        if os.path.isfile(token_path):
            try:
                creds = Credentials.from_authorized_user_file(
                    token_path,
                    ["https://www.googleapis.com/auth/spreadsheets"],
                )
            except Exception:
                creds = None

        if creds and creds.valid:
            return True

        if creds and creds.expired and creds.refresh_token:
            try:
                _log("Google OAuth token expired. Refreshing...")
                creds.refresh(Request())
                with open(token_path, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                _log("Token refreshed successfully.")
                return True
            except Exception as e:
                _log(f"Token refresh failed: {e}. Will re-authenticate.")

        # Need fresh consent flow
        from google_auth_oauthlib.flow import InstalledAppFlow

        _log("Google OAuth token missing or invalid. Opening browser for consent...")
        flow = InstalledAppFlow.from_client_secrets_file(
            client_secret_path,
            ["https://www.googleapis.com/auth/spreadsheets"],
        )
        creds = flow.run_local_server(port=0)

        os.makedirs(os.path.dirname(token_path) or ".", exist_ok=True)
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        _log(f"Token saved to {token_path}")
        return True

    except ImportError:
        _log(
            "Google auth libraries not installed. "
            "Run: pip install google-auth google-auth-oauthlib google-api-python-client"
        )
        return False
    except Exception as e:
        _log(f"Google OAuth error: {e}")
        return False
