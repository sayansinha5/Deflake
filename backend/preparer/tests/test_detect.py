from pathlib import Path

from preparer.detect import editable_paths, has_pytest, supports_python_312


def test_has_pytest_from_tests(tmp_path: Path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    assert has_pytest(tmp_path) is True


def test_has_pytest_from_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = [\"tests\"]\n", encoding="utf-8",
    )
    assert has_pytest(tmp_path) is True


def test_supports_python_312_bounds():
    assert supports_python_312(None) is True
    assert supports_python_312(">=3.9") is True
    assert supports_python_312(">=3.12") is True
    assert supports_python_312("<3.12") is False
    assert supports_python_312(">=3.13") is False
    assert supports_python_312("==3.11") is False


def test_editable_paths_src_layout(tmp_path: Path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("")
    (tmp_path / "tests").mkdir()
    (tmp_path / ".github").mkdir()
    paths = editable_paths(tmp_path)
    assert "src/pkg/**" in paths
    assert "tests/**" in paths
    assert not any(".github" in p for p in paths)
