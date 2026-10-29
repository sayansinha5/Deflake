"""Turns evidence into model text, and search text that cannot carry a repo path."""
import re

from app.security.redact import redact

_PATH_MARKS = ("/", "\\", "::", ".py", ".pyx")
_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_LIBRARY = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,40}")


def untrusted(text: str) -> str:
    return f"<untrusted>\n{redact(text)}\n</untrusted>"


def clean_query(query: str, library: str | None) -> str:
    """A Tavily query: no paths, line numbers, addresses, or repository names."""
    kept: list[str] = []
    for token in redact(query or "").split():
        if any(mark in token for mark in _PATH_MARKS):
            continue
        if _ADDR.search(token) or token.isdigit():
            continue
        kept.append(token)
    text = " ".join(kept)
    lib = (library or "").strip()
    if _LIBRARY.fullmatch(lib) and lib.lower() not in text.lower():
        text = f"{text} {lib}".strip()
    text = text[:120].strip()
    return text or "flaky test intermittent failure"


def error_signature(failing_samples: list) -> str:
    for sample in failing_samples or []:
        traceback = sample.get("traceback") or ""
        for line in reversed(traceback.splitlines()):
            line = line.strip()
            if line and not line.startswith("File ") and not line.startswith("Traceback"):
                return clean_query(line, None)
    return "flaky test intermittent failure"


def evidence_text(failing: list, passing: list) -> tuple[str, set[str]]:
    blocks: list[str] = []
    ids: set[str] = set()
    for kind, samples in (("failing", failing or []), ("passing", passing or [])):
        for index, sample in enumerate(samples, start=1):
            sample_id = f"{kind}-{index}"
            ids.add(sample_id)
            traceback = "\n".join(redact(sample.get("traceback") or "").splitlines()[:40])
            window = ", ".join(str(item) for item in (sample.get("order_window") or [])[:11])
            outcome = sample.get("outcome")
            duration = sample.get("duration_ms")
            blocks.append(
                f"{sample_id} outcome={outcome} duration_ms={duration}\n"
                f"order window: {window}\n{traceback}"
            )
    return "\n\n".join(blocks), ids
