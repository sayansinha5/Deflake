"""Detect pytest support, Python version bounds, and editable paths."""
from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore

_VERSION_PART = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


def _read_toml(path: Path) -> dict:
    if tomllib is None or not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def has_pytest(src: Path) -> bool:
    if (src / "pytest.ini").is_file() or (src / "conftest.py").is_file():
        return True
    if list(src.rglob("test_*.py")) or list(src.rglob("*_test.py")):
        return True
    pyproject = _read_toml(src / "pyproject.toml")
    tool = pyproject.get("tool") or {}
    if "pytest" in tool:
        return True
    setup_cfg = src / "setup.cfg"
    if setup_cfg.is_file() and "pytest" in setup_cfg.read_text(encoding="utf-8", errors="replace").lower():
        return True
    return False


def requires_python(src: Path) -> str | None:
    pyproject = _read_toml(src / "pyproject.toml")
    project = pyproject.get("project") or {}
    req = project.get("requires-python")
    if isinstance(req, str) and req.strip():
        return req.strip()
    setup_cfg = src / "setup.cfg"
    if setup_cfg.is_file():
        text = setup_cfg.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"(?m)^python_requires\s*=\s*(.+)$", text)
        if match:
            return match.group(1).strip()
    return None


def _parse_version(text: str) -> tuple[int, int, int] | None:
    match = _VERSION_PART.search(text)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    return major, minor, patch


def supports_python_312(spec: str | None) -> bool:
    """Return False only when the specifier clearly excludes 3.12."""
    if not spec:
        return True
    target = (3, 12, 0)
    # Split on comma for combined markers like ">=3.9,<3.12"
    parts = [p.strip() for p in spec.split(",") if p.strip()]
    if not parts:
        return True
    for part in parts:
        if part.startswith(">="):
            ver = _parse_version(part[2:])
            if ver and ver > (3, 12, 99):
                return False
        elif part.startswith(">"):
            ver = _parse_version(part[1:])
            if ver and ver >= (3, 12, 0):
                # >3.12 excludes 3.12; >3.11 does not
                if ver >= target:
                    return False
        elif part.startswith("<="):
            ver = _parse_version(part[2:])
            if ver and ver < target:
                return False
        elif part.startswith("<"):
            ver = _parse_version(part[1:])
            if ver and ver <= target:
                return False
        elif part.startswith("=="):
            ver = _parse_version(part[2:])
            if ver and ver[:2] != (3, 12):
                return False
        elif part.startswith("!="):
            ver = _parse_version(part[2:])
            if ver and ver[:2] == (3, 12):
                return False
    return True


_SKIP_DIRS = {
    ".git", ".github", ".venv", "venv", "node_modules", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    "egg-info",
}


def editable_paths(src: Path) -> list[str]:
    """Package folders and test folders. Never venv, .github, config or lock files."""
    found: set[str] = set()
    if (src / "src").is_dir():
        for child in (src / "src").iterdir():
            if child.is_dir() and not child.name.startswith(".") and child.name not in _SKIP_DIRS:
                found.add(f"src/{child.name}/**")
    for child in src.iterdir():
        if not child.is_dir() or child.name.startswith(".") or child.name in _SKIP_DIRS:
            continue
        if child.name in {"tests", "test"}:
            found.add(f"{child.name}/**")
            continue
        if child.name == "src":
            continue
        if (child / "__init__.py").is_file() or any(child.glob("*.py")):
            # Treat top-level Python packages / modules dirs as editable.
            if (child / "__init__.py").is_file():
                found.add(f"{child.name}/**")
    # Flat test files at repo root
    if any(src.glob("test_*.py")) or any(src.glob("*_test.py")):
        found.add("*.py")
    if not found:
        # Fall back to common layouts so a prepare can still proceed.
        if (src / "tests").is_dir():
            found.add("tests/**")
        if (src / "src").is_dir():
            found.add("src/**")
    return sorted(found)
