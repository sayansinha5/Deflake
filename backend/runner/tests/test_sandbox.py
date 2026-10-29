import os
import socket
import textwrap

import pytest

pytest.importorskip("resource")

from runner.sandbox import JobError, Limits, run_job  # noqa: E402
from runner.schemas import Job  # noqa: E402

LIMITS = Limits(max_parallel=2)

TESTS = {
    "test_basic.py": """
        def test_ok():
            assert True

        def test_bad():
            assert 1 == 2
    """,
    "test_hang.py": """
        import time

        def test_hangs():
            time.sleep(60)
    """,
    "test_net.py": """
        import socket

        def test_outbound():
            socket.create_connection(("1.1.1.1", 80), timeout=3).close()
    """,
    "test_env.py": """
        import os

        def test_env_is_scrubbed():
            # LC_CTYPE is set by Python's own UTF-8 locale coercion, not passed in.
            assert set(os.environ) <= {"PATH", "HOME", "PYTHONHASHSEED", "LC_CTYPE",
                                       "PYTEST_CURRENT_TEST", "PYTEST_VERSION"}
    """,
}


@pytest.fixture
def dirs(tmp_path):
    repos = tmp_path / "repos"
    repo = repos / "sample"
    (repo / "tests").mkdir(parents=True)
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    for name, body in TESTS.items():
        (repo / "tests" / name).write_text(textwrap.dedent(body).lstrip("\n"))
    work = tmp_path / "work"
    work.mkdir()
    return repos, work


def _run(dirs, **job):
    repos, work = dirs
    return run_job(Job(repo_id="sample", **job), repos, work, LIMITS)


def _outcomes(iteration):
    return {r.test_id: r.outcome for r in iteration.results}


def test_runs_selected_tests_with_outcomes(dirs):
    result = _run(dirs, mode="tests", tests=["tests/test_basic.py"], iterations=2)
    assert len(result.iterations) == 2
    for it in result.iterations:
        assert it.status == "ok"
        assert _outcomes(it) == {"tests/test_basic.py::test_ok": "passed",
                                 "tests/test_basic.py::test_bad": "failed"}


def test_hanging_test_killed_at_timeout(dirs):
    result = _run(dirs, mode="tests", tests=["tests/test_hang.py"], timeout_s=2)
    it = result.iterations[0]
    assert _outcomes(it) == {"tests/test_hang.py::test_hangs": "timeout"}
    assert it.duration_ms < 30_000


def test_iteration_wall_clock_limit_kills_process_group(dirs):
    result = _run(dirs, mode="tests", tests=["tests/test_hang.py"], timeout_s=120,
                  iteration_timeout_s=5)
    assert result.iterations[0].status == "timeout"


def test_traversal_patch_rejected(dirs):
    patch = ("diff --git a/../evil.py b/../evil.py\n--- /dev/null\n+++ b/../evil.py\n"
             "@@ -0,0 +1 @@\n+x = 1\n")
    with pytest.raises(JobError) as exc:
        _run(dirs, patch=patch)
    assert exc.value.code == "patch_rejected"


def test_valid_patch_is_applied(dirs):
    patch = ("--- a/tests/test_basic.py\n+++ b/tests/test_basic.py\n@@ -4,2 +4,2 @@\n"
             " def test_bad():\n-    assert 1 == 2\n+    assert 2 == 2\n")
    result = _run(dirs, patch=patch, mode="tests", tests=["tests/test_basic.py"])
    assert result.patch_applied
    assert _outcomes(result.iterations[0])["tests/test_basic.py::test_bad"] == "passed"


def test_patch_that_does_not_apply_is_rejected(dirs):
    patch = ("--- a/tests/test_basic.py\n+++ b/tests/test_basic.py\n@@ -1,1 +1,1 @@\n"
             "-this line is not there\n+x\n")
    with pytest.raises(JobError) as exc:
        _run(dirs, patch=patch)
    assert "does not apply" in exc.value.message


def test_explicit_order_is_respected(dirs):
    order = ["tests/test_basic.py::test_bad", "tests/test_env.py::test_env_is_scrubbed",
             "tests/test_basic.py::test_ok"]
    result = _run(dirs, mode="tests", order=order, random_order=False)
    assert result.iterations[0].order == order


def test_seeds_are_reported_and_reused(dirs):
    result = _run(dirs, mode="tests", tests=["tests/test_basic.py"], iterations=2,
                  seeds=[11, 22], hash_seeds=[33, 44])
    assert [(i.seed, i.hash_seed) for i in result.iterations] == [(11, 33), (22, 44)]


def test_environment_is_scrubbed(dirs):
    result = _run(dirs, mode="tests", tests=["tests/test_env.py"])
    assert _outcomes(result.iterations[0]) == {"tests/test_env.py::test_env_is_scrubbed": "passed"}


def test_workspace_removed_after_job(dirs):
    _, work = dirs
    _run(dirs, mode="tests", tests=["tests/test_basic.py"], iterations=2)
    assert list(work.iterdir()) == []


def test_workspace_removed_after_rejected_patch(dirs):
    _, work = dirs
    with pytest.raises(JobError):
        _run(dirs, patch="diff --git a/../x b/../x\n")
    assert list(work.iterdir()) == []


def test_collection_error_reported(dirs):
    repos, _ = dirs
    (repos / "sample" / "tests" / "test_broken.py").write_text("import not_a_real_module\n")
    result = _run(dirs, timeout_s=2)
    it = result.iterations[0]
    assert it.status == "collection_error"
    assert "not_a_real_module" in it.error


def test_unknown_repo_rejected(dirs):
    repos, work = dirs
    with pytest.raises(JobError):
        run_job(Job(repo_id="missing"), repos, work, LIMITS)


@pytest.mark.skipif(os.environ.get("RUNNER_INTEGRATION") != "1",
                    reason="only meaningful inside the runner container")
def test_outbound_network_blocked_in_container(dirs):
    with pytest.raises(OSError):
        socket.create_connection(("1.1.1.1", 80), timeout=3).close()
    result = _run(dirs, mode="tests", tests=["tests/test_net.py"])
    assert _outcomes(result.iterations[0]) == {"tests/test_net.py::test_outbound": "failed"}
