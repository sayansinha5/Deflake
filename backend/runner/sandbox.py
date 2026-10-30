import os
import random
import resource
import shutil
import signal
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from runner.junit import parse_junit, truncate
from runner.patches import PatchRejected, apply_patch
from runner.schemas import Iteration, Job, JobResult, TestOutcome

COPY_IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", ".pytest_cache", ".venv", "venv",
)


@dataclass(frozen=True)
class Limits:
    mem_mb: int = 1024
    cpu_seconds: int = 120
    max_processes: int = 256
    max_file_mb: int = 50
    max_parallel: int = 4

    @classmethod
    def from_env(cls) -> "Limits":
        return cls(
            mem_mb=int(os.environ.get("RUNNER_MEM_LIMIT_MB", 1024)),
            cpu_seconds=int(os.environ.get("RUNNER_CPU_SECONDS", 120)),
            max_parallel=int(os.environ.get("RUNNER_MAX_PARALLEL", 4)),
        )


@dataclass(frozen=True)
class ResolvedRepo:
    source_dir: Path
    python: Path
    imported: bool


class JobError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def resolve_repo(
    repos_dir: Path,
    repo_id: str,
    repos_data_dir: Path | None = None,
) -> ResolvedRepo:
    """Prefer an imported prepare layout under repos-data; else demo repos_dir."""
    if repos_data_dir is not None:
        root = repos_data_dir.resolve()
        imported_src = (root / repo_id / "src").resolve()
        if imported_src.is_dir() and imported_src.is_relative_to(root):
            # venv/bin/python is usually a symlink into the image's Python. Check
            # the path under repos-data, not the resolved target outside the volume.
            python = root / repo_id / "venv" / "bin" / "python"
            if not python.parent.resolve().is_relative_to(root) or not python.exists():
                raise JobError(
                    "repo_not_ready",
                    f"imported repository {repo_id!r} has no virtualenv",
                )
            return ResolvedRepo(source_dir=imported_src, python=python, imported=True)

    root = repos_dir.resolve()
    repo = (root / repo_id).resolve()
    if not repo.is_relative_to(root) or not repo.is_dir():
        raise JobError("unknown_repo", f"repository {repo_id!r} is not available")
    return ResolvedRepo(source_dir=repo, python=Path(sys.executable), imported=False)


def _limit_child(limits: Limits):
    def apply() -> None:
        mem = limits.mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NPROC, (limits.max_processes, limits.max_processes))
        size = limits.max_file_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (size, size))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    return apply


def _pythonpath(workspace: Path) -> str:
    parts = [str(workspace)]
    src = workspace / "src"
    if src.is_dir():
        parts.insert(0, str(src))
    return os.pathsep.join(parts)


def _pytest_command(
    python: Path,
    job: Job,
    seed: int,
    junit_path: Path,
    order_file: Path | None,
) -> list[str]:
    cmd = [
        str(python), "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "-p", "randomly", f"--randomly-seed={seed}",
        f"--timeout={job.timeout_s}", "--timeout-method=signal",
        "-o", "junit_family=xunit1", f"--junitxml={junit_path}",
    ]
    if not job.random_order:
        cmd.append("--randomly-dont-reorganize")
    if order_file is not None:
        cmd += ["-p", "deflake_order", f"--deflake-order-file={order_file}"]
    elif job.mode == "tests" and job.tests:
        cmd += list(job.tests)
    return cmd


def _run_iteration(
    job: Job,
    index: int,
    seed: int,
    hash_seed: int,
    base: Path,
    python: Path,
    job_dir: Path,
    limits: Limits,
) -> Iteration:
    it_dir = job_dir / f"it-{index}"
    workspace = it_dir / "repo"
    shutil.copytree(base, workspace, ignore=COPY_IGNORE, symlinks=False)
    junit_path = it_dir / "junit.xml"
    order_file = None
    if job.order is not None:
        order_file = it_dir / "order.txt"
        order_file.write_text("\n".join(job.order) + "\n", encoding="utf-8")

    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workspace),
        "PYTHONHASHSEED": str(hash_seed),
        "PYTHONPATH": _pythonpath(workspace),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    started = time.monotonic()
    status = "ok"
    error = None
    proc = subprocess.Popen(  # noqa: S603
        _pytest_command(python, job, seed, junit_path, order_file),
        cwd=workspace, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True, preexec_fn=_limit_child(limits),
    )
    try:
        output, _ = proc.communicate(timeout=job.iteration_timeout_s)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        output, _ = proc.communicate()
        status = "timeout"
        error = f"iteration exceeded {job.iteration_timeout_s}s and was killed"
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    duration_ms = int((time.monotonic() - started) * 1000)
    text = (output or b"").decode("utf-8", errors="replace")

    results: list[TestOutcome] = []
    if junit_path.exists():
        report = parse_junit(junit_path.read_text(encoding="utf-8", errors="replace"))
        results = [TestOutcome(**vars(r)) for r in report.results]
        if report.collection_errors and status == "ok":
            status = "collection_error"
            error = truncate("\n".join(report.collection_errors))
    elif status == "ok":
        status = "crashed"
        error = truncate(text) or "pytest exited without writing a report"
    if status == "ok" and proc.returncode in (2, 3, 4):
        status = "collection_error"
        error = truncate(text)

    return Iteration(
        index=index, seed=seed, hash_seed=hash_seed, status=status,
        exit_code=proc.returncode, duration_ms=duration_ms,
        order=[r.test_id for r in results], results=results, error=error,
    )


def run_job(
    job: Job,
    repos_dir: Path,
    work_dir: Path,
    limits: Limits | None = None,
    repos_data_dir: Path | None = None,
) -> JobResult:
    limits = limits or Limits.from_env()
    resolved = resolve_repo(repos_dir, job.repo_id, repos_data_dir=repos_data_dir)
    rng = random.SystemRandom()
    seeds = job.seeds or [rng.randrange(2**32) for _ in range(job.iterations)]
    hash_seeds = job.hash_seeds or [rng.randrange(2**32) for _ in range(job.iterations)]

    job_dir = work_dir / f"job-{uuid.uuid4().hex}"
    job_dir.mkdir(parents=True)
    try:
        base = job_dir / "base" / "repo"
        shutil.copytree(resolved.source_dir, base, ignore=COPY_IGNORE, symlinks=False)
        if job.patch:
            try:
                apply_patch(job.patch, base)
            except PatchRejected as exc:
                raise JobError("patch_rejected", str(exc)) from exc

        with ThreadPoolExecutor(max_workers=limits.max_parallel) as pool:
            futures = [
                pool.submit(
                    _run_iteration, job, i, seeds[i], hash_seeds[i],
                    base, resolved.python, job_dir, limits,
                )
                for i in range(job.iterations)
            ]
            iterations = [f.result() for f in futures]
        return JobResult(repo_id=job.repo_id, patch_applied=bool(job.patch), iterations=iterations)
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
