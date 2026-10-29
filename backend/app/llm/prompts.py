"""Loads versioned prompt files. The version is stored on each llm_calls row."""
from pathlib import Path

_DIR = Path(__file__).resolve().parent / "prompts"


def _load(name: str) -> tuple[str, str]:
    text = (_DIR / f"{name}.md").read_text(encoding="utf-8")
    header, _, body = text.partition("\n")
    if not header.startswith("version: "):
        raise RuntimeError(f"prompt {name} is missing a version header")
    version = header.removeprefix("version: ").strip()
    if not version or not body.strip():
        raise RuntimeError(f"prompt {name} is empty")
    return version, body.strip()


PROMPTS: dict[str, tuple[str, str]] = {
    name: _load(name) for name in (
        "classify", "search", "diagnose", "match", "patch", "escalate",
    )
}


def prompt(name: str) -> tuple[str, str]:
    return PROMPTS[name]
