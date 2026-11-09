import json
import socket
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).parents[2]
NODE = {"labels": {"node": "n1"}}
IMAGE = "ghcr.io/nanofaas/workbench-supervisor:test"


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )


def ports(n: int) -> list[int]:
    socks = [socket.socket() for _ in range(n)]
    try:
        for s in socks:
            s.bind(("127.0.0.1", 0))
        return [s.getsockname()[1] for s in socks]
    finally:
        for s in socks:
            s.close()


@pytest.fixture(scope="module")
def image() -> str:
    done = docker(
        "build", "-t", IMAGE, "-f", str(ROOT / "images/supervisor/Dockerfile"),
        str(ROOT),
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    return IMAGE


def test_supervisor_faults_when_exporter_stops(run_playbook, image, host_get, tmp_path):
    ne_port, pr_port, sv_port = ports(3)
    target = {
        "kind": "scrape_up",
        "params": {"job": "node", "labels": {"node": "n1"}},
        # The supervisor starts once Prometheus reports up: no cold-start slack needed.
        "toleratedSeconds": 10,
    }
    vs = {
        "instances": [
            {"name": "ne", "component": "node-exporter", "config": {"port": ne_port}},
            {
                "name": "pr",
                "component": "prometheus",
                "config": {
                    "port": pr_port,
                    "data_dir": str(tmp_path / "d"),
                    "scrape_interval": "1s",
                    "jobs": {"node": [{"target": f"127.0.0.1:{ne_port}", **NODE}]},
                },
            },
            {
                "name": "sv",
                "component": "supervisor",
                "config": {
                    "image": image,
                    "port": sv_port,
                    "prometheus_url": f"http://127.0.0.1:{pr_port}",
                    "interval": 1,
                    "targets": {"ne": target},
                },
            },
        ]
    }

    def status() -> dict:
        return json.loads(host_get(f"http://127.0.0.1:{sv_port}/status") or "{}")

    def wait_for(state: str, seconds: int) -> dict:
        report: dict = {}
        for _ in range(seconds):
            report = status()
            if report.get("state") == state:
                return report
            time.sleep(1)
        pytest.fail(f"never {state}: {report}")

    up = (
        f"http://127.0.0.1:{pr_port}/api/v1/query"
        "?query=up%7Bjob%3D%22node%22%2Cnode%3D%22n1%22%7D"
    )
    try:
        # Exporter and Prometheus first: a slow first scrape must not fault
        # the target (a fault is sticky) before the test looks at it.
        first = {"instances": vs["instances"][:2]}
        done = run_playbook("deploy", first)
        assert done.returncode == 0, done.stdout + done.stderr
        for _ in range(60):
            values = json.loads(host_get(up) or "{}").get("data", {}).get("result", [])
            if values and values[0]["value"][1] == "1":
                break
            time.sleep(1)
        else:
            pytest.fail(f"Prometheus never saw the exporter up: {host_get(up)}")
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        user = docker("inspect", "-f", "{{.Config.User}}", "wb-sv").stdout.strip()
        assert user not in ("", "0", "root")
        wait_for("healthy", 20)
        assert docker("stop", "wb-ne").returncode == 0
        report = wait_for("fault", 30)
        assert [a["kind"] for a in report["anomalies"]] == ["scrape_up"]
        assert report["targets"]["ne"]["failing"] is True
        # It only signals: the stopped exporter stays stopped.
        assert (
            docker("inspect", "-f", "{{.State.Running}}", "wb-ne").stdout.strip()
            == "false"
        )
    finally:
        run_playbook("undeploy", vs)
