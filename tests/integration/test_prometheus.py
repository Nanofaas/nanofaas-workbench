import json
import socket
import subprocess
import tarfile
import time
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.docker

ROOT = Path(__file__).parents[2]
IMAGE = yaml.safe_load((ROOT / "roles/prometheus/defaults/main.yml").read_text())[
    "prometheus_image"
]


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )


def host_net_unreachable() -> bool:
    """Docker Desktop's host network is its VM's: collect cannot reach the API."""
    return docker("info", "--format", "{{.OperatingSystem}}").stdout.strip() == (
        "Docker Desktop"
    )


def prom_vars(port: int, data_dir, jobs: dict) -> dict:
    return {
        "instances": [
            {
                "name": "pr",
                "component": "prometheus",
                "config": {
                    "port": port,
                    "data_dir": str(data_dir),
                    "scrape_interval": "1s",
                    "jobs": jobs,
                },
            }
        ]
    }


def test_empty_job_is_valid(run_playbook, free_port, tmp_path):
    vs = prom_vars(free_port, tmp_path / "d", {"node": []})
    try:
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        check = docker(
            "run", "--rm", "--entrypoint", "promtool",
            "-v", "/tmp/wb-pr/prometheus.yml:/c.yml:ro", IMAGE,
            "check", "config", "/c.yml",
        )  # fmt: skip
        assert check.returncode == 0, check.stdout + check.stderr
    finally:
        run_playbook("undeploy", vs)


def test_scrape_time_not_honored(run_playbook, free_port, tmp_path):
    jobs = {"a": [{"target": "127.0.0.1:1"}], "b": []}
    vs = prom_vars(free_port, tmp_path / "d", jobs)
    try:
        assert run_playbook("deploy", vs).returncode == 0
        cfg = yaml.safe_load(Path("/tmp/wb-pr/prometheus.yml").read_text())
        assert [j["honor_timestamps"] for j in cfg["scrape_configs"]] == [False] * 2
    finally:
        run_playbook("undeploy", vs)


def test_scrape_and_snapshot(run_playbook, free_port, tmp_path, host_get):
    ne_port = free_port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        pr_port = s.getsockname()[1]
    jobs = {"node": [{"target": f"127.0.0.1:{ne_port}", "labels": {"node": "n1"}}]}
    vs = prom_vars(pr_port, tmp_path / "d", jobs)
    vs["instances"].insert(
        0, {"name": "ne", "component": "node-exporter", "config": {"port": ne_port}}
    )
    vs["collect_dir"] = str(tmp_path / "out")
    try:
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        query = f"http://127.0.0.1:{pr_port}/api/v1/query?query=up%7Bjob%3D%22node%22%2Cnode%3D%22n1%22%7D"
        for _ in range(20):
            result = json.loads(host_get(query) or "{}")
            values = result.get("data", {}).get("result", [])
            if values and values[0]["value"][1] == "1":
                break
            time.sleep(1)
        else:
            pytest.fail(f"up != 1: {host_get(query)}")
        snap = json.loads(
            host_get(
                f"http://127.0.0.1:{pr_port}/api/v1/admin/tsdb/snapshot", post=True
            )
        )["data"]["name"]
        assert (tmp_path / "d" / "snapshots" / snap).is_dir()
        if host_net_unreachable():
            pytest.skip(
                "Docker Desktop: host network not reachable, collect needs Linux"
            )
        done = run_playbook("collect", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        tarball = tmp_path / "out" / "localhost" / "pr" / "prometheus-snapshot.tar.gz"
        with tarfile.open(tarball) as t:
            names = t.getnames()
        assert any("meta.json" in n or "chunks_head" in n for n in names), names
    finally:
        run_playbook("undeploy", vs)
