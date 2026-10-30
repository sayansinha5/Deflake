"""Clone a GitHub repo, install dependencies only, collect pytest tests."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from preparer.deps import build_pip_command
from preparer.detect import editable_paths, has_pytest, requires_python, supports_python_312
from preparer.redact import redact
from preparer.schemas import PrepareJob, PrepareResult

PLUGIN_SOURCE = Path(__file__).resolve().parent.parent / "runner" / "plugins" / "deflake_order.py"
_COLLECTED = re.compile(r"(\d+)\s+tests?\s+collected|collected\s+(\d+)\s+items?")


class PrepareError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _run(
    cmd: list[str],
    *,
    cwd: Path | None,
    env: dict[str, str],
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise PrepareError(f"Command timed out after {timeout_s}s: {' '.join(cmd[:3])}…") from exc


def _tail(text: str, lines: int = 40) -> str:
    parts = (text or "").splitlines()
    return "\n".join(parts[-lines:])


def _dir_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total / (1024 * 1024)


def _base_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/home/preparer"),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_LFS_SKIP_SMUDGE": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_NO_INPUT": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _clone(job: PrepareJob, src: Path) -> tuple[str, str]:
    if src.exists():
        shutil.rmtree(src)
    src.parent.mkdir(parents=True, exist_ok=True)

    env = _base_env()
    cmd = [
        "git",
        "-c", "core.hooksPath=/dev/null",
        "-c", "advice.detachedHead=false",
        "clone",
        "--depth", "1",
        "--single-branch",
        "--no-recurse-submodules",
    ]
    if job.branch:
        cmd.extend(["--branch", job.branch])
    if job.token:
        # Pass the token via an extra header. Never put it in the URL.
        cmd.extend(["-c", f"http.extraHeader=AUTHORIZATION: bearer {job.token}"])
    cmd.extend([job.clone_url, str(src)])

    result = _run(cmd, cwd=None, env=env, timeout_s=job.clone_timeout_s)
    if result.returncode != 0:
        detail = redact(_tail(result.stderr or result.stdout or "clone failed"))
        raise PrepareError(
            "Repository not found or not public. Connect GitHub to import private "
            f"repositories. {detail}".strip()
        )

    sha = _run(["git", "rev-parse", "HEAD"], cwd=src, env=env, timeout_s=30)
    if sha.returncode != 0:
        raise PrepareError("Clone succeeded but the commit SHA could not be read.")
    commit = sha.stdout.strip()

    branch = job.branch
    if not branch:
        name = _run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=src, env=env, timeout_s=30,
        )
        branch = (name.stdout or "").strip() or "HEAD"
    return commit, branch


def _create_venv(python: Path, venv: Path) -> Path:
    if venv.exists():
        shutil.rmtree(venv)
    result = _run(
        [str(python), "-m", "venv", str(venv)],
        cwd=None,
        env=_base_env(),
        timeout_s=120,
    )
    if result.returncode != 0:
        raise PrepareError(redact(_tail(result.stderr or result.stdout) or "venv failed"))
    venv_python = venv / "bin" / "python"
    if not venv_python.is_file():
        raise PrepareError("Virtualenv was created without a python binary.")
    return venv_python


def _install_deps(venv_python: Path, src: Path, timeout_s: int) -> None:
    cmd = build_pip_command(venv_python, src)
    joined = " ".join(cmd)
    if " -e " in f" {joined} " or cmd[-1:] == ["."] or "." in cmd[4:]:
        # Pip args after `pip install` must not include the project path.
        if any(part in {".", "-e", "--editable"} or part.startswith("-e") for part in cmd[4:]):
            raise PrepareError("Refusing to install the project package into the virtualenv.")
    result = _run(cmd, cwd=src, env=_base_env(), timeout_s=timeout_s)
    if result.returncode != 0:
        log = redact(_tail((result.stdout or "") + "\n" + (result.stderr or "")))
        raise PrepareError(f"Dependency install failed.\n{log}")


def _install_order_plugin(venv_python: Path) -> None:
    if not PLUGIN_SOURCE.is_file():
        return
    site = _run(
        [str(venv_python), "-c", "import site; print(site.getsitepackages()[0])"],
        cwd=None,
        env=_base_env(),
        timeout_s=30,
    )
    if site.returncode != 0:
        return
    target = Path(site.stdout.strip()) / "deflake_order.py"
    shutil.copyfile(PLUGIN_SOURCE, target)


def _parse_collected(output: str) -> int:
    for line in output.splitlines():
        match = _COLLECTED.search(line)
        if match:
            return int(match.group(1) or match.group(2))
    return sum(1 for line in output.splitlines() if "::" in line)


def _collect(venv_python: Path, src: Path, timeout_s: int) -> int:
    env = _base_env()
    pythonpath = [str(src)]
    if (src / "src").is_dir():
        pythonpath.insert(0, str(src / "src"))
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    # Discourage accidental network use during collection.
    env["http_proxy"] = "http://127.0.0.1:9"
    env["https_proxy"] = "http://127.0.0.1:9"
    env["HTTP_PROXY"] = env["http_proxy"]
    env["HTTPS_PROXY"] = env["https_proxy"]
    env["NO_PROXY"] = ""
    env["no_proxy"] = ""

    result = _run(
        [str(venv_python), "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=src,
        env=env,
        timeout_s=min(timeout_s, 180),
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode not in (0, 1):
        raise PrepareError(
            "pytest collection failed.\n" + redact(_tail(output) or "no output")
        )
    count = _parse_collected(output)
    if count == 0:
        raise PrepareError(
            "No pytest tests found.\n" + redact(_tail(output) or "collection returned no tests")
        )
    return count


def prepare(job: PrepareJob, data_root: Path, system_python: Path | None = None) -> PrepareResult:
    root = (data_root / job.repo_id).resolve()
    if not root.is_relative_to(data_root.resolve()):
        return PrepareResult(repo_id=job.repo_id, status="failed", error="Invalid repository id.")
    src = root / "src"
    venv = root / "venv"
    python = system_python or Path(sys.executable)

    try:
        root.mkdir(parents=True, exist_ok=True)
        commit, branch = _clone(job, src)
        size_mb = _dir_size_mb(src)
        if size_mb > job.max_size_mb:
            raise PrepareError(
                f"Repository is {size_mb:.0f} MB, over the limit of {job.max_size_mb} MB."
            )
        if not has_pytest(src):
            raise PrepareError("No pytest tests found.")
        req = requires_python(src)
        if not supports_python_312(req):
            raise PrepareError(
                "This project needs a Python version Deflake doesn't support yet."
            )
        venv_python = _create_venv(python, venv)
        _install_deps(venv_python, src, job.prepare_timeout_s)
        _install_order_plugin(venv_python)
        test_count = _collect(venv_python, src, job.prepare_timeout_s)
        paths = editable_paths(src)
        return PrepareResult(
            repo_id=job.repo_id,
            status="ready",
            commit_sha=commit,
            default_branch=branch,
            test_count=test_count,
            editable_paths=paths,
            requires_python=req,
        )
    except PrepareError as exc:
        return PrepareResult(repo_id=job.repo_id, status="failed", error=exc.message)
    except Exception as exc:  # noqa: BLE001
        return PrepareResult(
            repo_id=job.repo_id,
            status="failed",
            error=redact(str(exc)) or "Prepare failed.",
        )
    finally:
        # Drop the token from the in-memory model as soon as work finishes.
        try:
            job.token = None
        except Exception:  # noqa: BLE001
            pass
