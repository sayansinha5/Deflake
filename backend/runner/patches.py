import re
import subprocess
from pathlib import Path, PurePosixPath

MAX_PATCH_BYTES = 200_000

_PATH_PREFIXES = ("--- ", "+++ ", "rename from ", "rename to ", "copy from ", "copy to ")


class PatchRejected(Exception):
    pass


def _clean_path(raw: str) -> str | None:
    path = raw.split("\t", 1)[0].strip()
    if path == "/dev/null":
        return None
    if path.startswith('"'):
        raise PatchRejected("quoted or escaped paths are not allowed")
    if path.startswith(("a/", "b/")):
        path = path[2:]
    return path


def paths_in_patch(patch: str) -> set[str]:
    paths: set[str] = set()
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            for part in line[len("diff --git "):].split(" "):
                if (p := _clean_path(part)) is not None:
                    paths.add(p)
        for prefix in _PATH_PREFIXES:
            if line.startswith(prefix):
                if (p := _clean_path(line[len(prefix):])) is not None:
                    paths.add(p)
    return paths


def check_paths(patch: str) -> set[str]:
    if len(patch.encode()) > MAX_PATCH_BYTES:
        raise PatchRejected("patch is too large")
    if "\x00" in patch:
        raise PatchRejected("patch contains NUL bytes")
    if "GIT binary patch" in patch or "Binary files " in patch:
        raise PatchRejected("binary patches are not allowed")
    paths = paths_in_patch(patch)
    if not paths:
        raise PatchRejected("patch names no files")
    for path in paths:
        pure = PurePosixPath(path)
        if not path or "\\" in path or pure.is_absolute() or ".." in pure.parts:
            raise PatchRejected(f"path outside the repository: {path}")
    return paths


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def _read_target(workspace: Path, path: str) -> list[str] | None:
    target = (workspace / path).resolve()
    root = workspace.resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target.read_text(encoding="utf-8").splitlines()


def _preimage(body: list[str]) -> list[str] | None:
    lines: list[str] = []
    for line in body:
        if line.startswith("\\"):
            return None
        if line.startswith("+"):
            continue
        if line.startswith(("-", " ")):
            lines.append(line[1:])
            continue
        return None
    return lines


def _extend_hunk(
    header: str, body: list[str], file_lines: list[str], next_old: int | None,
) -> tuple[str, list[str]]:
    """git apply anchors a hunk with no trailing context to EOF.

    A mid-file change is rejected even when every old line matches. Copy up to
    three following source lines into the hunk so the match is no longer tied
    to the end of the file.
    """
    if not body or body[-1].startswith((" ", "\\")):
        return header, body
    match = _HUNK.match(header)
    pre = _preimage(body)
    if match is None or pre is None or match.group(1) == "0":
        return header, body
    start = int(match.group(1)) - 1
    end = start + len(pre)
    if start < 0 or file_lines[start:end] != pre:
        return header, body
    limit = len(file_lines) if next_old is None else min(len(file_lines), next_old - 1)
    extra = file_lines[end:min(end + 3, limit)]
    if not extra:
        return header, body
    extended = [*body, *(f" {line}" for line in extra)]
    old_count = sum(not line.startswith(("+", "\\")) for line in extended)
    new_count = sum(not line.startswith(("-", "\\")) for line in extended)
    suffix = match.group(5)
    rewritten = (
        f"@@ -{match.group(1)},{old_count} +{match.group(3)},{new_count} @@{suffix}"
    )
    return rewritten, extended


def _with_trailing_context(patch: str, workspace: Path) -> str:
    lines = patch.splitlines()
    out: list[str] = []
    file_lines: list[str] | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("+++ "):
            path = _clean_path(line[len("+++ "):])
            file_lines = _read_target(workspace, path) if path else None
            out.append(line)
            index += 1
            continue
        if file_lines is None or _HUNK.match(line) is None:
            if line.startswith("--- "):
                file_lines = None
            out.append(line)
            index += 1
            continue
        body_at = index + 1
        end = body_at
        while end < len(lines) and not lines[end].startswith(("@@", "--- ", "diff --git ")):
            end += 1
        next_old = None
        if end < len(lines) and lines[end].startswith("@@"):
            nxt = _HUNK.match(lines[end])
            next_old = int(nxt.group(1)) if nxt else None
        header, body = _extend_hunk(line, lines[body_at:end], file_lines, next_old)
        out.append(header)
        out.extend(body)
        index = end
    text = "\n".join(out)
    if patch.endswith("\n"):
        text += "\n"
    return text


def apply_patch(patch: str, workspace: Path) -> None:
    """Rejects unsafe paths, dry-runs with git apply --check, then applies."""
    check_paths(patch)
    patch = _with_trailing_context(patch, workspace)
    patch_file = workspace.parent / "change.patch"
    patch_file.write_text(patch, encoding="utf-8", newline="\n")
    base = ["git", "apply", "--whitespace=nowarn", "-p1", str(patch_file)]
    check = subprocess.run(  # noqa: S603
        [*base[:2], "--check", *base[2:]], cwd=workspace, capture_output=True, text=True,
        check=False, timeout=30,
    )
    if check.returncode != 0:
        raise PatchRejected(f"patch does not apply: {check.stderr.strip()[:500]}")
    subprocess.run(base, cwd=workspace, capture_output=True, text=True, check=True,  # noqa: S603
                   timeout=30)
    for path in paths_in_patch(patch):
        target = (workspace / path).resolve()
        if target.exists() and not target.is_relative_to(workspace.resolve()):
            raise PatchRejected(f"path escapes the repository: {path}")
