"""Deterministic patch checks G1–G9. A model does not decide these."""
import ast
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from io import StringIO
from pathlib import PurePosixPath

from unidiff import PatchSet, UnidiffParseError

from runner.patches import PatchRejected, check_paths

MAX_LINES = 80
MAX_FILES = 3

_FORBIDDEN_NAMES = {
    "pytest.ini", "pyproject.toml", "setup.py", "setup.cfg", "tox.ini",
    "pipfile", "jenkinsfile", "package.json", "package-lock.json", "uv.lock",
    "poetry.lock",
}
_NETWORK_ROOTS = {"requests", "httpx", "aiohttp", "urllib", "socket"}
_DANGEROUS_ROOTS = _NETWORK_ROOTS | {"subprocess", "pickle", "ctypes"}
_DANGEROUS_CALLS = {"eval", "exec", "os.system", "os.popen"}
_ORDER_TEXT = ("no:randomly", "randomly-seed", "pytest-randomly", "PYTEST_ADDOPTS")


@dataclass(frozen=True)
class Violation:
    rule: str
    message: str
    lines: str = ""

    def as_dict(self) -> dict:
        return {"rule": self.rule, "message": self.message, "lines": self.lines[:500]}


def _chain(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _chain(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _chain(node.func)
    return ""


def _calls(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    return [
        (_chain(node.func), node) for node in ast.walk(tree) if isinstance(node, ast.Call)
    ]


def _added_text(patched) -> list[str]:
    lines = []
    for hunk in patched:
        for line in hunk:
            if line.is_added:
                lines.append(line.value.rstrip("\n").rstrip("\r"))
    return lines


def _excerpt(lines: list[str], *needles: str) -> str:
    picked = [line for line in lines if any(needle in line for needle in needles)]
    chosen = picked or lines
    return "\n".join(chosen[:8])[:500]


def is_editable(path: str, editable_paths: list[str]) -> bool:
    if not editable_paths:
        return False
    return any(_matches(path, pattern) for pattern in editable_paths)


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/**"):
        root = pattern[:-3].rstrip("/")
        return path == root or path.startswith(root + "/")
    return fnmatchcase(path, pattern)


def _forbidden(path: str) -> str | None:
    pure = PurePosixPath(path)
    if any(part.startswith(".") for part in pure.parts):
        return f"{path} is in a hidden folder"
    name = pure.name.lower()
    if name in _FORBIDDEN_NAMES or name.startswith("requirements") and name.endswith(".txt"):
        return f"{path} is a config or dependency file"
    if name.endswith(".lock") or path.startswith((".github/", ".circleci/", ".gitlab/")):
        return f"{path} is a config or lock file"
    if name in {".gitlab-ci.yml"} or name.startswith("azure-pipelines"):
        return f"{path} is CI config"
    binary = {".png", ".jpg", ".jpeg", ".gif", ".pyc", ".so", ".dll", ".exe", ".whl", ".zip"}
    if pure.suffix.lower() in binary:
        return f"{path} is a binary file"
    return None


def _apply(original: str, patched) -> str:
    source = original.splitlines()
    out: list[str] = []
    index = 0
    for hunk in patched:
        start = 0 if hunk.source_start == 0 else hunk.source_start - 1
        if start < index or start > len(source):
            raise ValueError("hunk starts past the file")
        out.extend(source[index:start])
        index = start
        for line in hunk:
            text = line.value.rstrip("\n").rstrip("\r")
            if line.is_context or line.is_removed:
                if index >= len(source) or source[index] != text:
                    raise ValueError("hunk context does not match")
                index += 1
            if line.is_added or line.is_context:
                out.append(text)
    out.extend(source[index:])
    if not out:
        return ""
    body = "\n".join(out)
    if original.endswith("\n") or original == "":
        body += "\n"
    return body


def _count(tree: ast.AST, kind: type) -> int:
    return sum(1 for node in ast.walk(tree) if isinstance(node, kind))


def _test_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in getattr(tree, "body", []):
        is_func = isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        if is_func and node.name.startswith("test"):
            names.add(node.name)
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                is_func = isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
                if is_func and item.name.startswith("test"):
                    names.add(f"{node.name}.{item.name}")
    return names


def _assert_counts(tree: ast.AST) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in getattr(tree, "body", []):
        funcs = []
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            funcs.append((node.name, node))
        elif isinstance(node, ast.ClassDef):
            funcs.extend(
                (f"{node.name}.{item.name}", item)
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)
            )
        for name, func in funcs:
            if name.split(".")[-1].startswith("test"):
                counts[name] = _count(func, ast.Assert)
    return counts


def _timeouts(tree: ast.AST) -> list[float]:
    values: list[float] = []
    for name, call in _calls(tree):
        if name == "timeout" or name.endswith(".timeout"):
            if call.args and isinstance(call.args[0], ast.Constant):
                if isinstance(call.args[0].value, int | float):
                    values.append(float(call.args[0].value))
        for keyword in call.keywords:
            if keyword.arg == "timeout" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, int | float):
                    values.append(float(keyword.value.value))
    return values


def _approx_limits(tree: ast.AST) -> list[float]:
    limits: list[float] = []
    for name, call in _calls(tree):
        if not name.endswith("approx"):
            continue
        for keyword in call.keywords:
            if keyword.arg in {"rel", "abs"} and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, int | float):
                    limits.append(float(keyword.value.value))
    return limits


def _decorators(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for dec in node.decorator_list:
                names.append(_chain(dec))
    return names


def _broad_tries(tree: ast.AST) -> int:
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        has_assert = any(isinstance(item, ast.Assert) for item in ast.walk(node))
        broad = any(
            handler.type is None or (
                isinstance(handler.type, ast.Name)
                and handler.type.id in {"Exception", "BaseException"}
            )
            for handler in node.handlers
        )
        if has_assert and broad:
            found += 1
    return found


def _assert_loops(tree: ast.AST) -> int:
    found = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.For | ast.While | ast.AsyncFor):
            if any(isinstance(item, ast.Assert) for item in ast.walk(node)):
                found += 1
    return found


def _hashseed_assigns(tree: ast.AST) -> int:
    found = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Subscript):
                continue
            if _chain(target.value) not in {"os.environ", "environ"}:
                continue
            slice_node = target.slice
            if isinstance(slice_node, ast.Constant) and slice_node.value == "PYTHONHASHSEED":
                found += 1
    return found


def _constant_asserts(tree: ast.AST) -> int:
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Assert) and isinstance(node.test, ast.Constant)
    )


def _skip_marks(tree: ast.AST) -> int:
    marks = 0
    for name in _decorators(tree):
        if "skip" in name or "xfail" in name:
            marks += 1
    for name, _call in _calls(tree):
        if name in {"pytest.skip", "skip", "pytest.xfail", "xfail"}:
            marks += 1
    return marks


def _semantic(before: ast.AST, after: ast.AST, added: list[str]) -> list[Violation]:
    found: list[Violation] = []
    before_calls = _calls(before)
    after_calls = _calls(after)

    def named(calls, predicate) -> int:
        return sum(1 for name, call in calls if predicate(name, call))

    def is_sleep(name: str, _call: ast.Call) -> bool:
        return name == "sleep" or name.endswith(".sleep")

    def is_wait(name: str, call: ast.Call) -> bool:
        if name not in {"wait", "wait_for"} and not name.endswith((".wait", ".wait_for")):
            return False
        constants = [
            arg for arg in call.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, int | float)
        ]
        keywords = [
            keyword for keyword in call.keywords
            if keyword.arg in {"timeout", "delay"}
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, int | float)
        ]
        return bool(constants or keywords)

    sleeps = named(after_calls, is_sleep) > named(before_calls, is_sleep)
    waits = named(after_calls, is_wait) > named(before_calls, is_wait)
    if sleeps or waits:
        found.append(Violation("G1", "The diff adds a wait.", _excerpt(added, "sleep", "wait")))

    retry_names = [
        name for name in _decorators(after) if name not in _decorators(before)
        and ("flaky" in name or "retry" in name)
    ]
    if retry_names or _assert_loops(after) > _assert_loops(before):
        found.append(Violation(
            "G2", "The diff adds a retry or a loop around an assertion.",
            _excerpt(added, "flaky", "retry", "for ", "while "),
        ))

    removed_tests = _test_names(before) - _test_names(after)
    if removed_tests or _skip_marks(after) > _skip_marks(before):
        detail = ", ".join(sorted(removed_tests)) or "skip or xfail"
        found.append(Violation(
            "G3", f"The diff skips or drops a test ({detail}).",
            _excerpt(added, "skip", "xfail"),
        ))

    weaker = False
    before_asserts = _assert_counts(before)
    after_asserts = _assert_counts(after)
    for name, count in before_asserts.items():
        if name in after_asserts and after_asserts[name] < count:
            weaker = True
    before_approx = _approx_limits(before)
    after_approx = _approx_limits(after)
    if before_approx and after_approx and max(after_approx) > max(before_approx):
        weaker = True
    if _approx_calls(after) > _approx_calls(before):
        weaker = True
    constants = _constant_asserts(after) > _constant_asserts(before)
    swallowed = _broad_tries(after) > _broad_tries(before)
    if constants or swallowed:
        weaker = True
    if weaker:
        found.append(Violation(
            "G4", "The diff weakens an assertion.",
            _excerpt(added, "assert", "approx", "except"),
        ))

    before_timeout = _timeouts(before)
    after_timeout = _timeouts(after)
    keyword_grew = bool(
        before_timeout and after_timeout and max(after_timeout) > 2 * max(before_timeout)
    )
    if keyword_grew or _bounds_grew(before, after):
        found.append(Violation(
            "G5", "A timeout more than doubled.", _excerpt(added, "timeout", "<"),
        ))

    def roots(calls) -> set[str]:
        return {_chain_root(name) for name, _call in calls}

    def exact(calls) -> set[str]:
        return {name for name, _call in calls}

    new_roots = roots(after_calls) - roots(before_calls)
    new_exact = exact(after_calls) - exact(before_calls)
    new_imports = _import_roots(after) - _import_roots(before)
    dangerous_import = new_imports & (_DANGEROUS_ROOTS | {"eval", "exec"})
    if new_roots & _DANGEROUS_ROOTS or new_exact & _DANGEROUS_CALLS or dangerous_import:
        found.append(Violation(
            "G8", "The diff adds a dangerous import or call.",
            _excerpt(added, "subprocess", "socket", "eval", "exec", "pickle", "httpx", "requests"),
        ))

    new_seed = any(name in {"random.seed", "numpy.random.seed"} for name in new_exact)
    hashseed = _hashseed_assigns(after) > _hashseed_assigns(before)
    order_text = any(any(marker in line for marker in _ORDER_TEXT) for line in added)
    if new_seed or hashseed or order_text:
        found.append(Violation(
            "G9", "The diff pins order or a seed to hide the flake.",
            _excerpt(added, "seed", "randomly", "PYTHONHASHSEED"),
        ))
    return found


def _approx_calls(tree: ast.AST) -> int:
    return sum(1 for name, _call in _calls(tree) if name == "approx" or name.endswith(".approx"))


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _compare_bounds(tree: ast.AST) -> list[tuple[str, str, float]]:
    found: list[tuple[str, str, float]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        left = ast.dump(node.left)
        for op, comp in zip(node.ops, node.comparators, strict=False):
            if not isinstance(comp, ast.Constant):
                continue
            number = _number(comp.value)
            if number is not None:
                found.append((type(op).__name__, left, number))
    return found


def _bounds_grew(before: ast.AST, after: ast.AST) -> bool:
    previous = {(op, left): value for op, left, value in _compare_bounds(before)}
    for op, left, value in _compare_bounds(after):
        old = previous.get((op, left))
        if old is None or old <= 0:
            continue
        if op in {"Lt", "LtE"} and value > 2 * old:
            return True
        if op in {"Gt", "GtE"} and value < old / 2:
            return True
    return False


_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)


def prepare_diff(diff: str) -> str:
    """Turn the model's diff text into a unified diff unidiff can read."""
    # A context line can be a single space. strip() would delete it and break the hunk.
    text = diff.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    text = _BR.sub("\n", text)
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    text = re.sub(r"(?m)^-- (?=[ab]/)", "--- ", text)
    text = re.sub(r"(?m)^--(?=[ab]/)", "--- ", text)
    if "\n" not in text:
        text = _explode_diff(text)
    if text and not text.endswith("\n"):
        text += "\n"
    return text


def _explode_diff(text: str) -> str:
    text = re.sub(r"(?<!^)(?<!\n)(\+\+\+|@@)", r"\n\1", text)
    text = re.sub(r"(?m)^(---|\+\+\+)(?=\S)", r"\1 ", text)
    out: list[str] = []
    for line in text.split("\n"):
        match = re.match(r"(@@.*?@@)\s*(.*)", line)
        if match and match.group(2):
            out.append(match.group(1))
            out.extend(_split_body(match.group(2)))
        else:
            out.append(line)
    return "\n".join(out)


def _split_body(body: str) -> list[str]:
    parts = re.split(r" (?=[+\-])", body.strip())
    lines: list[str] = []
    for part in parts:
        if not part:
            continue
        if part[0] in "+- ":
            lines.append(part)
        else:
            lines.append(f" {part}")
    return lines


def _chain_root(name: str) -> str:
    return name.split(".", 1)[0]


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _sections(diff: str) -> list[tuple[str, list[list[str]]]]:
    path = ""
    sections: list[tuple[str, list[list[str]]]] = []
    hunks: list[list[str]] = []
    current: list[str] | None = None

    def finish() -> None:
        nonlocal current
        if path and hunks:
            sections.append((path, hunks))
        current = None

    for line in diff.splitlines():
        if line.startswith("--- "):
            finish()
            raw = line[4:].split("\t", 1)[0].strip()
            path = raw[2:] if raw.startswith("a/") else raw
            hunks = []
            current = None
            continue
        if line.startswith("+++ ") or line.startswith("\\"):
            continue
        if line.startswith("@@"):
            current = []
            hunks.append(current)
            continue
        if current is None:
            continue
        if line[:1] in "+- ":
            current.append(line)
        elif line == "":
            current.append(" ")
    finish()
    return sections


def _insertion(source: list[str], body: list[str]) -> tuple[int, list[str]] | None:
    """Place added lines after the longest unique run of real context lines."""
    before: list[str] = []
    added: list[str] = []
    for line in body:
        if line.startswith("+"):
            added.append(line)
            continue
        if added or not line.startswith(" ") or not line.strip():
            if added:
                break
            continue
        before.append(line[1:])
    if not before or not added:
        return None
    for length in range(len(before), 0, -1):
        found = _locate(source, before[-length:])
        if found is None:
            continue
        start, matched = found
        return start, [" " + line for line in matched] + added
    return None


def _locate(source: list[str], old: list[str]) -> tuple[int, list[str]] | None:
    if not old:
        return None
    n = len(old)
    exact = [
        i for i in range(len(source) - n + 1)
        if source[i:i + n] == old
    ]
    if len(exact) == 1:
        return exact[0], old
    folded = [line.rstrip() for line in old]
    loose = [
        i for i in range(len(source) - n + 1)
        if [line.rstrip() for line in source[i:i + n]] == folded
    ]
    if len(loose) == 1:
        return loose[0], source[loose[0]:loose[0] + n]
    return None


def _alias_paths(diff: str, originals: dict[str, str]) -> str:
    """Map a bare filename onto the one shown file with that name."""
    by_name: dict[str, list[str]] = {}
    for key in originals:
        by_name.setdefault(PurePosixPath(key).name, []).append(key)
    out: list[str] = []
    for line in diff.splitlines():
        if line.startswith("--- ") or line.startswith("+++ "):
            prefix = line[:3]
            raw = line[4:].split("\t", 1)[0].strip()
            path = raw[2:] if raw.startswith(("a/", "b/")) else raw
            hits = by_name.get(PurePosixPath(path).name, [])
            if path not in originals and len(hits) == 1:
                side = "a/" if prefix == "---" else "b/"
                line = f"{prefix} {side}{hits[0]}"
        out.append(line)
    text = "\n".join(out)
    if diff.endswith("\n"):
        text += "\n"
    return text


def repair_hunks(diff: str, originals: dict[str, str]) -> tuple[str, list[Violation]]:
    """Fill in hunk line numbers and snap context lines to the real file."""
    sections = _sections(diff)
    if not sections:
        return diff, []
    rendered: list[str] = []
    problems: list[Violation] = []
    for path, hunks in sections:
        rendered.append(f"--- a/{path}")
        rendered.append(f"+++ b/{path}")
        source = originals.get(path, "").splitlines()
        for body in hunks:
            if not any(line[:1] in "+-" for line in body):
                continue
            old = [line[1:] for line in body if line[:1] in " -"]
            if not old:
                problems.append(Violation(
                    "apply", f"{path}: the hunk has no context lines.", "\n".join(body[:8]),
                ))
                continue
            found = _locate(source, old)
            removed_only = False
            if found is None:
                removed = [line[1:] for line in body if line.startswith("-")]
                found = _locate(source, removed)
                removed_only = found is not None
            if found is None and not any(line.startswith("-") for line in body):
                inserted = _insertion(source, body)
                if inserted is not None:
                    start, rebuilt = inserted
                    old_count = sum(1 for line in rebuilt if line[:1] in " -")
                    new_count = sum(1 for line in rebuilt if line[:1] in " +")
                    rendered.append(f"@@ -{start + 1},{old_count} +{start + 1},{new_count} @@")
                    rendered.extend(rebuilt)
                    continue
            if found is None:
                problems.append(Violation(
                    "apply",
                    f"{path}: hunk context does not match the file. Copy existing lines unchanged.",
                    "\n".join(body[:8]),
                ))
                continue
            start, matched = found
            if removed_only:
                body = ["-" + line for line in matched] + [
                    line for line in body if line.startswith("+")
                ]
            rebuilt: list[str] = []
            index = 0
            for line in body:
                if line.startswith("+"):
                    rebuilt.append(line)
                elif line[:1] in "- ":
                    rebuilt.append(line[:1] + matched[index])
                    index += 1
            new_count = sum(1 for line in rebuilt if line[:1] in " +")
            rendered.append(f"@@ -{start + 1},{len(matched)} +{start + 1},{new_count} @@")
            rendered.extend(rebuilt)
    if problems:
        return diff, problems
    if not any(line.startswith("@@") for line in rendered):
        return diff, [Violation("apply", "The diff has no hunks.")]
    return "\n".join(rendered) + "\n", []


def _changed_count(diff: str) -> int:
    return sum(
        1 for line in diff.splitlines()
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )


def review_patch(
    diff: str, originals: dict[str, str], editable_paths: list[str],
) -> tuple[str, list[Violation]]:
    """Return the diff to store and every violation. No violations means it may be proposed."""
    diff = _alias_paths(prepare_diff(diff), originals)
    preview = "\n".join(diff.splitlines()[:8])[:500]
    repaired, problems = repair_hunks(diff, originals)
    candidate = repaired if not problems else diff
    try:
        paths = check_paths(candidate if not problems else diff)
    except PatchRejected as exc:
        text = str(exc)
        if "too large" in text:
            return diff, [Violation("G7", text, preview)]
        if "names no files" in text:
            return diff, [Violation(
                "apply",
                "The diff needs a --- a/<path> line and a +++ b/<path> line for each file.",
                preview,
            )]
        return diff, [Violation("G6", text, preview)]

    found: list[Violation] = list(problems)
    if len(paths) > MAX_FILES:
        found.append(Violation(
            "G7", f"The diff touches {len(paths)} files; the limit is {MAX_FILES}.",
        ))
    changed = _changed_count(diff)
    if changed == 0:
        found.append(Violation("apply", "The diff does not change any line.", preview))
    if changed > MAX_LINES:
        found.append(Violation(
            "G7", f"The diff changes {changed} lines; the limit is {MAX_LINES}.",
        ))
    for path in sorted(paths):
        reason = _forbidden(path)
        if reason:
            found.append(Violation("G6", reason))
        elif not is_editable(path, editable_paths):
            found.append(Violation("G6", f"{path} is outside the editable paths."))
    if found:
        return diff, found

    try:
        patchset = PatchSet(StringIO(candidate))
    except UnidiffParseError as exc:
        return diff, [Violation("apply", f"The diff could not be parsed: {exc}", preview)]
    if not list(patchset):
        return diff, [Violation(
            "apply", "The diff has no hunks. Put each diff line in its own lines entry.", preview,
        )]

    for patched in patchset:
        path = patched.path
        added = _added_text(patched)
        try:
            updated = _apply(originals.get(path, ""), patched)
            after = ast.parse(updated)
            before = ast.parse(originals.get(path, "") or "")
        except (ValueError, SyntaxError) as exc:
            found.append(Violation("apply", f"{path}: {exc}", _excerpt(added)))
            continue
        found.extend(_semantic(before, after, added))
    return (candidate if not found else diff), found


def check_patch(diff: str, originals: dict[str, str], editable_paths: list[str]) -> list[Violation]:
    """Return every violation. An empty list means the patch may be proposed."""
    _stored, violations = review_patch(diff, originals, editable_paths)
    return violations
