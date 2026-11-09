"""Shared fixtures: the collection built and installed from the working tree."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BIN = Path(sys.executable).parent


def run(*cmd: str | Path, env: dict[str, str] | None = None, cwd: Path = ROOT):
    """Run a venv tool (ansible-*) and return the completed process."""
    return subprocess.run(
        [str(BIN / str(cmd[0])), *map(str, cmd[1:])],
        cwd=cwd,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="session")
def tool():
    """Run a venv tool; later integration tests reuse it."""
    return run


@pytest.fixture(scope="session")
def built_tarball(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("build")
    done = run(
        "ansible-galaxy", "collection", "build", ROOT, "--output-path", out, "--force"
    )
    assert done.returncode == 0, done.stderr
    return next(out.glob("nanofaas-workbench-*.tar.gz"))


@pytest.fixture(scope="session")
def collections_path(built_tarball: Path, tmp_path_factory: pytest.TempPathFactory):
    """Return a tmp collections path with the working-tree collection."""
    path = tmp_path_factory.mktemp("collections")
    # --no-deps: dependencies come from Galaxy; CI installs them separately.
    done = run(
        "ansible-galaxy", "collection", "install", built_tarball, "-p", path,
        "--no-deps",
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return path


@pytest.fixture
def ansible_env(collections_path: Path, tmp_path: Path) -> dict[str, str]:
    return {
        "ANSIBLE_COLLECTIONS_PATH": str(collections_path),
        "ANSIBLE_HOME": str(tmp_path / "ansible-home"),
        "ANSIBLE_NOCOLOR": "1",
    }
