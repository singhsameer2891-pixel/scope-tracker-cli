"""Helper module for calling the Claude CLI with prompt files.

Reads a prompt template file, substitutes {{PLACEHOLDER}} values,
and invokes `claude -p` as a subprocess. MCP servers are loaded
automatically from .mcp.json in the working directory.

This module is imported by all pipeline scripts that need LLM calls.
It is not a standalone CLI script.
"""

import os
import subprocess
import sys
from typing import Any


def call_llm(
    prompt_file: str,
    placeholders: dict[str, Any],
    cwd: str,
    timeout: int = 300,
    expected_output_files: list[str] | None = None,
) -> str:
    """Call claude -p with a prompt template after placeholder substitution.

    Args:
        prompt_file: Absolute path to the .md prompt template file.
        placeholders: Dict of {{KEY}} -> value replacements.
        cwd: Working directory for the subprocess (should contain .mcp.json).
        timeout: Subprocess timeout in seconds. Default 300.
        expected_output_files: Optional list of file paths that the LLM should create.
            If provided and any file is missing after the call, raises RuntimeError.

    Returns:
        The stdout string from the claude process.

    Raises:
        RuntimeError: If the claude process exits with a non-zero code,
            or if expected output files are missing.
        FileNotFoundError: If the prompt file does not exist.
    """
    prompt_path = os.path.expanduser(os.path.abspath(prompt_file))

    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")

    for key, value in placeholders.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", str(value))

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--dangerously-skip-permissions"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "claude CLI not found. Install from https://claude.ai/code"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"claude -p timed out after {timeout}s for {prompt_file}"
        )

    if result.returncode != 0:
        stderr_snippet = result.stderr[:500] if result.stderr else "(no stderr)"
        raise RuntimeError(
            f"claude -p failed for {prompt_file} (exit {result.returncode}): "
            f"{stderr_snippet}"
        )

    # Log LLM stdout to stderr for debugging
    if result.stdout:
        print(f"[call_llm] LLM response (first 500 chars): {result.stdout[:500]}", file=sys.stderr)

    # Verify expected output files were created
    if expected_output_files:
        missing = [f for f in expected_output_files if not os.path.exists(f)]
        if missing:
            raise RuntimeError(
                f"claude -p for {prompt_file} exited 0 but did not create expected files: "
                f"{missing}. LLM stdout: {result.stdout[:500]}"
            )

    return result.stdout
