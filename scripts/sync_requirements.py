#!/usr/bin/env python3
"""Sync requirements.txt with third-party imports used by the project."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "venv",
}
IMPORT_TO_DISTRIBUTION = {
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
}

def normalize_distribution(name: str) -> str:
    """Return the normalized form used to compare distribution names."""
    return re.sub(r"[-_.]+", "-", name).lower()

def python_sources() -> list[Path]:
    """Return project Python sources, excluding generated and environment folders."""
    return sorted(
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if not any(
            part in IGNORED_DIRECTORIES
            or part.endswith(".egg-info")
            or part.endswith(".venv")
            for part in path.relative_to(PROJECT_ROOT).parts
        )
    )

def local_module_names(sources: list[Path]) -> set[str]:
    """Return import roots provided by this repository."""
    modules = {path.stem for path in sources if path.name != "__init__.py"}
    modules.update(
        path.parent.name
        for path in sources
        if path.name == "__init__.py" and path.parent != PROJECT_ROOT
    )
    return modules

def imported_modules(sources: list[Path]) -> set[str]:
    """Collect top-level absolute imports from the project sources."""
    imports: set[str] = set()
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports.add(node.module.partition(".")[0])
    return imports

def used_distributions() -> set[str]:
    """Return third-party distribution names imported by project sources."""
    sources = python_sources()
    local_modules = local_module_names(sources)
    standard_library = set(sys.stdlib_module_names) | {"__future__"}
    external_imports = imported_modules(sources) - local_modules - standard_library
    return {
        normalize_distribution(
            IMPORT_TO_DISTRIBUTION.get(imported, imported.replace("_", "-"))
        )
        for imported in external_imports
    }

def requirement_name(requirement: str) -> str:
    """Extract a distribution name from a requirements line."""
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    if not match:
        raise ValueError(f"Unsupported requirement: {requirement!r}")
    return normalize_distribution(match.group(1))

def rendered_requirements(used: set[str], existing: list[str]) -> str:
    """Keep existing constraints and add newly imported distributions."""
    by_name = {requirement_name(line): line for line in existing if line.strip()}
    lines = [by_name.get(name, name) for name in sorted(used)]
    return "".join(f"{line}\n" for line in lines)

def parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of updating an out-of-date requirements.txt",
    )
    return parser.parse_args()

def main() -> int:
    """Update or check requirements.txt against imported third-party packages."""
    args = parse_args()
    existing = (
        REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
        if REQUIREMENTS_PATH.exists()
        else []
    )
    expected = rendered_requirements(used_distributions(), existing)
    actual = "".join(f"{line}\n" for line in existing if line.strip())
    if actual == expected:
        print("requirements.txt covers all third-party imports and is current.")
        return 0
    if args.check:
        print(
            "requirements.txt is out of date; run scripts/sync_requirements.py",
            file=sys.stderr,
        )
        return 1

    REQUIREMENTS_PATH.write_text(expected, encoding="utf-8")
    print("Generated requirements.txt from project imports.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
