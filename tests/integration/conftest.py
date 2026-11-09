"""Fixtures that run the collection's playbooks against localhost and Docker."""

import json
import socket
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPS_CACHE = ROOT / ".ansible" / "collections"  # gitignored, survives sessions


def _docker_up() -> bool:
    try:
        done = subprocess.run(
            ["docker", "info"], capture_output=True, check=False, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if _docker_up():
        return
    skip = pytest.mark.skip(reason="docker daemon not available")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def galaxy_deps(tool) -> Path:
    """Install the galaxy.yml dependencies once, into a cache that persists."""
    deps = yaml.safe_load((ROOT / "galaxy.yml").read_text())["dependencies"]
    for name, version in deps.items():
        manifest = (
            DEPS_CACHE / "ansible_collections" / Path(*name.split("."))
            / "MANIFEST.json"
        )  # fmt: skip
        if manifest.is_file():
            installed = json.loads(manifest.read_text())["collection_info"]["version"]
            if installed == version:
                continue
        done = tool(
            "ansible-galaxy", "collection", "install", f"{name}:{version}",
            "-p", DEPS_CACHE, "--force",
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
    return DEPS_CACHE


@pytest.fixture
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def run_playbook(tool, collections_path, galaxy_deps, tmp_path):
    """Run a collection playbook against an inventory (localhost by default)."""
    env = {
        "ANSIBLE_COLLECTIONS_PATH": f"{collections_path}:{galaxy_deps}",
        "ANSIBLE_HOME": str(tmp_path / "ansible-home"),
        "ANSIBLE_NOCOLOR": "1",
    }

    def go(
        name: str, host_vars: dict, inventory: str = "localhost,", **extra_env: str
    ) -> subprocess.CompletedProcess:
        vars_file = tmp_path / "vars.json"
        vars_file.write_text(json.dumps(host_vars))
        # No -c local: the playbooks pick the local connection themselves.
        return tool(
            "ansible-playbook", "-i", inventory,
            "-e", f"workbench_vars={vars_file}",
            f"nanofaas.workbench.{name}",
            env={**env, **extra_env},
        )  # fmt: skip

    return go
