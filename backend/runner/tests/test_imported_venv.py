"""Imported repos must run against the workspace copy, not code installed into the venv."""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip("resource")

from runner.sandbox import Limits, run_job  # noqa: E402
from runner.schemas import Job  # noqa: E402

LIMITS = Limits(max_parallel=1)


def _make_imported(tmp_path: Path) -> tuple[Path, Path]:
    """Build repos-data/{id}/src + venv with a trap package installed into the venv."""
    data = tmp_path / "repos-data"
    repo = data / "sample-import"
    src = repo / "src"
    pkg = src / "widget"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('VALUE = "from-workspace"\n', encoding="utf-8")
    tests = src / "tests"
    tests.mkdir()
    (tests / "test_widget.py").write_text(
        textwrap.dedent("""
            import widget

            def test_value():
                assert widget.VALUE == "from-workspace"
        """).lstrip(),
        encoding="utf-8",
    )
    (src / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\npythonpath = [\".\"]\n",
        encoding="utf-8",
    )

    # Runner has no outbound network: reuse image site-packages for pytest plugins.
    venv = repo / "venv"
    subprocess.check_call([sys.executable, "-m", "venv", "--system-site-packages", str(venv)])
    python = venv / "bin" / "python"
    site = subprocess.check_output(
        [str(python), "-c", "import site; print(site.getsitepackages()[0])"],
        text=True,
    ).strip()
    trap = Path(site) / "widget"
    trap.mkdir()
    (trap / "__init__.py").write_text('VALUE = "from-venv"\n', encoding="utf-8")

    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "empty-repos").mkdir(exist_ok=True)
    return data, work


def test_imported_repo_uses_workspace_not_venv_install(tmp_path: Path):
    data, work = _make_imported(tmp_path)
    result = run_job(
        Job(repo_id="sample-import", mode="tests", tests=["tests/test_widget.py"]),
        repos_dir=tmp_path / "empty-repos",
        work_dir=work,
        limits=LIMITS,
        repos_data_dir=data,
    )
    assert result.iterations[0].status == "ok"
    outcomes = {r.test_id: r.outcome for r in result.iterations[0].results}
    assert outcomes["tests/test_widget.py::test_value"] == "passed"


def test_patch_changes_workspace_copy_not_venv(tmp_path: Path):
    data, work = _make_imported(tmp_path)
    # Break the workspace value; the venv trap still says from-venv.
    (data / "sample-import" / "src" / "widget" / "__init__.py").write_text(
        'VALUE = "broken"\n', encoding="utf-8",
    )
    patch = (
        "--- a/widget/__init__.py\n"
        "+++ b/widget/__init__.py\n"
        "@@ -1 +1 @@\n"
        '-VALUE = "broken"\n'
        '+VALUE = "from-workspace"\n'
    )
    result = run_job(
        Job(
            repo_id="sample-import",
            patch=patch,
            mode="tests",
            tests=["tests/test_widget.py"],
        ),
        repos_dir=tmp_path / "empty-repos",
        work_dir=work,
        limits=LIMITS,
        repos_data_dir=data,
    )
    assert result.patch_applied
    outcomes = {r.test_id: r.outcome for r in result.iterations[0].results}
    assert outcomes["tests/test_widget.py::test_value"] == "passed"
