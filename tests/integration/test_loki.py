import json
import shutil
import subprocess
import time
from pathlib import Path
import urllib.request

import pytest

pytestmark = pytest.mark.docker

LABEL = "nanofaas.workbench/instance"


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )


def vars_for(port: int, data_dir, **kw) -> dict:
    return {
        "instances": [
            {
                "name": "lk",
                "component": "loki",
                "config": {"port": port, "data_dir": str(data_dir)},
                **kw,
            }
        ]
    }


def ready(port: int) -> int:
    for _ in range(60):
        try:
            return urllib.request.urlopen(
                f"http://127.0.0.1:{port}/ready", timeout=3
            ).status
        except OSError:
            time.sleep(1)
    return 0


def test_loki_ready_and_writes_to_data_dir(run_playbook, free_port, tmp_path):
    data = tmp_path / "loki-data"
    try:
        done = run_playbook("deploy", vars_for(free_port, data, cpuset="0"))
        assert done.returncode == 0, done.stdout + done.stderr
        assert ready(free_port) == 200
        used = shutil.disk_usage(tmp_path)
        if used.used / used.total < 0.9:  # Loki's WAL refuses writes above 90%
            push_one(free_port)
        assert any(data.iterdir())
        assert "127.0.0.1" in docker("port", "wb-lk").stdout
        info = json.loads(docker("inspect", "wb-lk").stdout)[0]
        assert info["HostConfig"]["CpusetCpus"] == "0"  # test_loki_cpuset_applied
    finally:
        run_playbook("undeploy", vars_for(free_port, data))


def push_one(port: int) -> None:
    push = urllib.request.Request(
        f"http://127.0.0.1:{port}/loki/api/v1/push",
        data=json.dumps(
            {"streams": [{"stream": {"a": "b"},
                          "values": [[str(time.time_ns()), "hello"]]}]}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )  # fmt: skip
    assert urllib.request.urlopen(push, timeout=5).status == 204


def test_config_file_override(run_playbook, free_port, tmp_path):
    data = tmp_path / "d"
    cfg = tmp_path / "loki.yaml"
    bundled = Path(__file__).parents[2] / "roles/loki/files/loki.yaml"
    cfg.write_text(bundled.read_text().replace("72h", "24h"))
    vs = vars_for(free_port, data)
    vs["instances"][0]["config"]["config_file"] = str(cfg)
    try:
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        assert ready(free_port) == 200
    finally:
        run_playbook("undeploy", vs)


def test_deploy_is_idempotent(run_playbook, free_port, tmp_path):
    vs = vars_for(free_port, tmp_path / "d")
    try:
        assert run_playbook("deploy", vs).returncode == 0
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        # Only the playbook's own group_by reports a change.
        changed = [ln for ln in done.stdout.splitlines() if ln.startswith("changed:")]
        assert len(changed) == 1, done.stdout
    finally:
        run_playbook("undeploy", vs)


def test_undeploy_after_partial_deploy(run_playbook, free_port, tmp_path):
    vs = vars_for(free_port, tmp_path / "d")
    vs["instances"].append(
        {"name": "ne", "component": "node-exporter", "config": {"port": free_port}}
    )
    docker("run", "-d", "--name", "wb-ne", "--label", f"{LABEL}=ne", "busybox",
           "sleep", "300")  # fmt: skip
    try:
        done = run_playbook("undeploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        assert docker("ps", "-a", "--filter", "name=wb-ne",
                      "--format", "{{.Names}}").stdout.split() == []  # fmt: skip
    finally:
        docker("rm", "-f", "wb-ne")


def test_collect_is_noop_locally(run_playbook, free_port, tmp_path):
    vs = vars_for(free_port, tmp_path / "d")
    done = run_playbook("collect", vs, ANSIBLE_STDOUT_CALLBACK="default")
    assert done.returncode == 0, done.stdout + done.stderr
