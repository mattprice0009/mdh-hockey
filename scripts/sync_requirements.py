#!/usr/bin/env python3
"""Validate imported dependencies and sync requirements.txt from setup.py."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SETUP_PATH = PROJECT_ROOT / "setup.py"
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

def distribution_name(requirement: str) -> str:
    """Extract a distribution name from a PEP 508 requirement string."""
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    if not match:
        raise ValueError(f"Unsupported requirement in setup.py: {requirement!r}")
    return normalize_distribution(match.group(1))

def install_requires() -> list[str]:
    """Read the literal install_requires list from setup.py."""
    tree = ast.parse(SETUP_PATH.read_text(encoding="utf-8"), filename=str(SETUP_PATH))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "setup":
            continue
        for keyword in node.keywords:
            if keyword.arg == "install_requires":
                value = ast.literal_eval(keyword.value)
                if not isinstance(value, list) or not all(
                    isinstance(item, str) for item in value
                ):
                    raise ValueError(
                        "setup.py install_requires must be a literal list of strings"
                    )
                return value
    raise ValueError("setup.py must call setup() with install_requires")

def python_sources() -> list[Path]:
    """Return project Python sources, excluding generated and environment folders."""
    return sorted(
        path
        for path in PROJECT_ROOT.rglob("*.py")
        if path != SETUP_PATH
        and not any(
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

def dependency_audit(
    requirements: list[str],
) -> tuple[list[tuple[str, str]], list[str]]:
    """Return missing imports and declared distributions that are no longer used."""
    sources = python_sources()
    local_modules = local_module_names(sources)
    standard_library = set(sys.stdlib_module_names) | {"__future__"}
    external_imports = imported_modules(sources) - local_modules - standard_library
    declared = {distribution_name(requirement) for requirement in requirements}
    imported_distributions = {
        normalize_distribution(
            IMPORT_TO_DISTRIBUTION.get(imported, imported.replace("_", "-"))
        )
        for imported in external_imports
    }
    missing = []
    for imported in sorted(external_imports):
        distribution = IMPORT_TO_DISTRIBUTION.get(imported, imported.replace("_", "-"))
        if normalize_distribution(distribution) not in declared:
            missing.append((imported, distribution))
    unused = sorted(declared - imported_distributions)
    return missing, unused

def rendered_requirements(requirements: list[str]) -> str:
    """Render requirements.txt using setup.py as the source of truth."""
    return "".join(f"{requirement}\n" for requirement in requirements)

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
    """Validate imports and update or check requirements.txt."""
    args = parse_args()
    requirements = install_requires()
    missing, unused = dependency_audit(requirements)
    if missing:
        print(
            "Dependencies imported by source files but missing from setup.py:",
            file=sys.stderr,
        )
        for imported, distribution in missing:
            print(f"  {imported} (add {distribution!r} to install_requires)", file=sys.stderr)
    if unused:
        print(
            "Dependencies in setup.py that are no longer imported by source files:",
            file=sys.stderr,
        )
        for distribution in unused:
            print(f"  {distribution} (remove it from install_requires)", file=sys.stderr)
    if missing or unused:
        return 1

    expected = rendered_requirements(requirements)
    actual = (
        REQUIREMENTS_PATH.read_text(encoding="utf-8")
        if REQUIREMENTS_PATH.exists()
        else ""
    )
    if actual == expected:
        print("setup.py matches source imports; requirements.txt is current.")
        return 0
    if args.check:
        print(
            "requirements.txt is out of date; run scripts/sync_requirements.py",
            file=sys.stderr,
        )
        return 1

    REQUIREMENTS_PATH.write_text(expected, encoding="utf-8")
    print("Generated requirements.txt from setup.py.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
