from pathlib import Path

from preparer.deps import build_pip_command, dependency_args


def test_requirements_file_preferred(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["ignored==1.0"]\n', encoding="utf-8",
    )
    files, inline = dependency_args(tmp_path)
    assert files == ["-r", str(tmp_path / "requirements.txt")]
    assert inline == []


def test_pyproject_dependencies_used_without_requirements(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["httpx>=0.27", "."]\n',
        encoding="utf-8",
    )
    files, inline = dependency_args(tmp_path)
    assert files == []
    assert inline == ["httpx>=0.27"]


def test_pip_command_never_installs_project(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["packaging"]\n',
        encoding="utf-8",
    )
    cmd = build_pip_command(Path("/venv/bin/python"), tmp_path)
    assert "." not in cmd
    assert "-e" not in cmd
    assert "--editable" not in cmd
    assert "pytest" in cmd
    assert "pytest-randomly" in cmd
    assert "pytest-timeout" in cmd
