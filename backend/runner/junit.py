from dataclasses import dataclass
from pathlib import PurePosixPath

from defusedxml import ElementTree

TRACEBACK_MAX_CHARS = 4000


@dataclass(frozen=True)
class TestResult:
    test_id: str
    outcome: str  # passed | failed | error | skipped | timeout
    duration_ms: int
    traceback: str | None = None


@dataclass(frozen=True)
class ParsedReport:
    results: list[TestResult]
    collection_errors: list[str]


def truncate(text: str, limit: int = TRACEBACK_MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    cut = len(text) - 2 * half
    return f"{text[:half]}\n[... {cut} characters cut ...]\n{text[-half:]}"


def _node_id(file: str, classname: str, name: str) -> str:
    module = ".".join(PurePosixPath(file).with_suffix("").parts)
    parts = [file]
    if classname.startswith(module + "."):
        parts.extend(classname[len(module) + 1:].split("."))
    parts.append(name)
    return "::".join(parts)


def _is_timeout(message: str) -> bool:
    return message.startswith("Failed: Timeout") or "from pytest-timeout" in message


def parse_junit(xml_text: str) -> ParsedReport:
    """Parses pytest's xunit1 JUnit XML, which carries a file attribute for exact node IDs."""
    root = ElementTree.fromstring(xml_text)
    results: list[TestResult] = []
    collection_errors: list[str] = []

    for case in root.iter("testcase"):
        file = case.get("file")
        classname = case.get("classname", "")
        name = case.get("name", "")
        duration_ms = int(round(float(case.get("time") or 0) * 1000))
        failure = case.find("failure")
        error = case.find("error")
        skipped = case.find("skipped")

        if not file and error is not None:
            detail = error.text or error.get("message") or "collection error"
            collection_errors.append(truncate(f"{classname}.{name}: {detail}".strip(". ")))
            continue

        node_id = _node_id(file or classname.replace(".", "/") + ".py", classname, name)
        if failure is not None:
            message = failure.get("message") or ""
            outcome = "timeout" if _is_timeout(message) else "failed"
            text = failure.text or message
            results.append(TestResult(node_id, outcome, duration_ms, truncate(text)))
        elif error is not None:
            text = error.text or error.get("message") or ""
            outcome = "timeout" if _is_timeout(error.get("message") or "") else "error"
            results.append(TestResult(node_id, outcome, duration_ms, truncate(text)))
        elif skipped is not None:
            results.append(TestResult(node_id, "skipped", duration_ms))
        else:
            results.append(TestResult(node_id, "passed", duration_ms))
    return ParsedReport(results=results, collection_errors=collection_errors)
