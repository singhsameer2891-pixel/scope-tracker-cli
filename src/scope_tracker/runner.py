"""Runner module for scope-tracker.

Loads configuration, resolves project paths, and invokes run_pipeline.py
for each enabled project during `scope-tracker run`.
"""

import json
import os
import sys
from typing import Any

from rich.console import Console

from scope_tracker.scripts import run_pipeline

console = Console(stderr=True)


def run_project(
    project: dict[str, Any],
    config: dict[str, Any],
    base_path: str,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    """Run the pipeline for a single project.

    Resolves all paths, calls run_pipeline.run() directly, and returns
    the pipeline summary dict.

    Args:
        project: Project config dict from scope_tracker_config.json.
        config: Full config dict.
        base_path: Absolute path to the scope-tracker/ directory.
        dry_run: If True, skip sheet writes and Slack post.
        verbose: If True, print step-by-step progress to stderr.

    Returns:
        Dict with pipeline result including status, steps_executed, and summary.

    Raises:
        RuntimeError: If the pipeline fails with an unrecoverable error.
    """
    base_path = os.path.expanduser(os.path.abspath(base_path))
    project_name = project["name"]
    project_dir = os.path.join(base_path, project.get("folder", project_name))
    config_path = os.path.join(base_path, "scope_tracker_config.json")

    # Ensure project directory exists
    system_dir = os.path.join(project_dir, "system")
    os.makedirs(system_dir, exist_ok=True)

    if verbose:
        console.print(f"\n[bold]Running pipeline for project: {project_name}[/bold]")

    try:
        result = run_pipeline.run(
            project_dir=project_dir,
            config_path=config_path,
            project_name=project_name,
            dry_run=dry_run,
            verbose=verbose,
        )
    except Exception as exc:
        msg = f"Pipeline failed for project '{project_name}': {exc}"
        if verbose:
            console.print(f"[red]{msg}[/red]")
        raise RuntimeError(msg) from exc

    result["project"] = project_name
    return result


def run_all(
    config_path: str,
    project_filter: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> list[dict[str, Any]]:
    """Run the pipeline for all enabled projects (or a single filtered project).

    Reads the config, filters to enabled projects, calls run_project for each,
    and collects results.

    Args:
        config_path: Absolute path to scope_tracker_config.json.
        project_filter: If set, run only the project with this name.
        dry_run: If True, skip sheet writes and Slack post.
        verbose: If True, print step-by-step progress.

    Returns:
        List of result dicts, one per project that was run.

    Raises:
        FileNotFoundError: If config file does not exist.
        ValueError: If project_filter is set but no matching project is found.
    """
    config_path = os.path.expanduser(os.path.abspath(config_path))
    base_path = os.path.dirname(config_path)

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found: {config_path}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config: {config_path}") from exc

    projects = config.get("projects", [])

    # Filter to enabled projects
    enabled = [p for p in projects if p.get("enabled", True)]

    # Apply project name filter if specified
    if project_filter:
        enabled = [p for p in enabled if p["name"] == project_filter]
        if not enabled:
            raise ValueError(
                f"Project '{project_filter}' not found or not enabled. "
                f"Available projects: {[p['name'] for p in projects]}"
            )

    if not enabled:
        if verbose:
            console.print("[yellow]No enabled projects found in config.[/yellow]")
        return []

    results: list[dict[str, Any]] = []
    for project in enabled:
        try:
            result = run_project(
                project=project,
                config=config,
                base_path=base_path,
                dry_run=dry_run,
                verbose=verbose,
            )
            results.append(result)
        except RuntimeError as exc:
            results.append({
                "project": project["name"],
                "status": "error",
                "message": str(exc),
            })

    return results
