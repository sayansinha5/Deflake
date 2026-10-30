"""Install project dependencies only — never the project itself."""
from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore

# Always available for Deflake scans. Installed into the repo venv, not the system.
SCAN_TOOLS = ("pytest", "pytest-randomly", "pytest-timeout")


def _read_toml(path: Path) -> dict:
    if tomllib is None or not path.is_file():
        return {}
    return tomllib.loads(path.read_text(encoding="utf-8"))


def requirement_files(src: Path) -> list[Path]:
    files = sorted(src.glob("requirements*.txt"))
    return [p for p in files if p.is_file()]


def pyproject_dependencies(src: Path) -> list[str]:
    data = _read_toml(src / "pyproject.toml")
    project = data.get("project") or {}
    deps = project.get("dependencies") or []
    return [str(d).strip() for d in deps if str(d).strip()]


def setup_cfg_install_requires(src: Path) -> list[str]:
    path = src / "setup.cfg"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?ms)^\[options\](.*?)(?=^\[|\Z)", text)
    if not match:
        return []
    block = match.group(1)
    req = re.search(r"(?ms)^install_requires\s*=\s*(.*?)(?=^\S|\Z)", block)
    if not req:
        return []
    lines = []
    for line in req.group(1).splitlines():
        item = line.strip().strip(",")
        if item and not item.startswith("#"):
            lines.append(item)
    return lines


def dependency_args(src: Path) -> tuple[list[str], list[str]]:
    """
    Return (pip_args_parts, inline_requirements).

    Prefer requirements*.txt files. Otherwise use pyproject/setup.cfg dependency
    lists. Never returns `.` or editable install flags.
    """
    files = requirement_files(src)
    if files:
        args: list[str] = []
        for path in files:
            args.extend(["-r", str(path)])
        return args, []
    inline = pyproject_dependencies(src) + setup_cfg_install_requires(src)
    # Refuse any attempt to install the project itself.
    cleaned = [
        dep for dep in inline
        if dep not in {".", "./", ".*"} and not dep.startswith("-e") and not dep.startswith("--editable")
    ]
    return [], cleaned


def build_pip_command(python: Path, src: Path) -> list[str]:
    file_args, inline = dependency_args(src)
    cmd = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
    cmd.extend(file_args)
    cmd.extend(inline)
    cmd.extend(SCAN_TOOLS)
    return cmd
