"""Fixtures that run the collection's playbooks against localhost and Docker."""

import json
import socket
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ECHO_IMAGE = (
    "busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec"
)
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


@pytest.fixture
def host_get():
    """GET/POST from inside the Docker host's network (Docker Desktop's is a VM)."""
    image = yaml.safe_load((ROOT / "roles/common/defaults/main.yml").read_text())[
        "common_probe_image"
    ]

    def go(url: str, post: bool = False) -> str:
        args = ["--post-data="] if post else []
        done = subprocess.run(
            ["docker", "run", "--rm", "--network", "host", image,
             "wget", "-qO-", *args, url],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        return done.stdout

    return go


@pytest.fixture
def echo(tmp_path, free_port):
    """Serve a host-network HTTP target answering POSTs with a JSON body."""
    cgi = tmp_path / "www" / "cgi-bin" / "echo"
    cgi.parent.mkdir(parents=True)
    cgi.write_text(
        '#!/bin/sh\nprintf "Content-type: application/json\\r\\n\\r\\n"\n'
        'echo \'{"status":"success","executionId":"e1"}\'\n'
    )
    cgi.chmod(0o755)
    name = f"wb-test-echo-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
    done = subprocess.run(
        ["docker", "run", "-d", "--name", name, "--network", "host",
        "-v", f"{tmp_path / 'www'}:/www:ro", ECHO_IMAGE,
        "httpd", "-f", "-p", f"127.0.0.1:{free_port}", "-h", "/www"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    yield f"http://127.0.0.1:{free_port}/cgi-bin/echo"
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
