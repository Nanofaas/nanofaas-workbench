import json
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

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
        assert any(data.iterdir())  # Loki lays out its dirs at startup
        assert "127.0.0.1" in docker("port", "wb-lk").stdout
        info = json.loads(docker("inspect", "wb-lk").stdout)[0]
        assert info["HostConfig"]["CpusetCpus"] == "0"  # test_loki_cpuset_applied
        used = shutil.disk_usage(tmp_path)
        if used.used / used.total >= 0.9:
            pytest.skip("host disk over 90%: Loki's WAL refuses writes")
        push_one(free_port)
        assert "hello" in query(free_port)
    finally:
        run_playbook("undeploy", vars_for(free_port, data))


def query(port: int) -> str:
    now = time.time_ns()
    url = (
        f"http://127.0.0.1:{port}/loki/api/v1/query_range?query=%7Ba%3D%22b%22%7D"
        f"&start={now - 600 * 10**9}&end={now + 60 * 10**9}"
    )
    return urllib.request.urlopen(url, timeout=10).read().decode()


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


def served_config(port: int) -> str:
    return (
        urllib.request.urlopen(f"http://127.0.0.1:{port}/config", timeout=10)
        .read()
        .decode()
    )


def test_changed_config_file_is_applied_on_redeploy(run_playbook, free_port, tmp_path):
    cfg = tmp_path / "loki.yaml"
    bundled = Path(__file__).parents[2] / "roles/loki/files/loki.yaml"
    cfg.write_text(bundled.read_text())
    vs = vars_for(free_port, tmp_path / "d")
    vs["instances"][0]["config"]["config_file"] = str(cfg)
    try:
        assert run_playbook("deploy", vs).returncode == 0
        assert ready(free_port) == 200
        assert "ingestion_rate_mb: 4" in served_config(free_port)
        cfg.write_text(
            bundled.read_text().replace("ingestion_rate_mb: 4", "ingestion_rate_mb: 5")
        )
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        assert ready(free_port) == 200
        assert "ingestion_rate_mb: 5" in served_config(free_port)
    finally:
        run_playbook("undeploy", vs)
        assert not Path("/tmp/wb-lk").exists()  # undeploy removes the config copy


def test_missing_required_config_fails_clearly(run_playbook, free_port):
    vs = {"instances": [{"name": "lk", "component": "loki", "config": {}}]}
    done = run_playbook("deploy", vs)
    assert done.returncode != 0
    assert "config.port and config.data_dir" in done.stdout


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
    vs["collect_dir"] = str(tmp_path / "out")
    done = run_playbook("collect", vs)
    assert done.returncode == 0, done.stdout + done.stderr
    assert not (tmp_path / "out").exists()
    assert not Path("/tmp/wb-lk-data.tar.gz").exists()


def test_collect_fetches_tarball_from_a_remote_host(run_playbook, free_port, tmp_path):
    data = tmp_path / "d"
    data.mkdir()
    (data / "chunk").write_text("x")
    inv = tmp_path / "inv.ini"
    inv.write_text(
        f"box ansible_connection=local ansible_python_interpreter={sys.executable}\n"
    )
    vs = vars_for(free_port, data)
    vs["collect_dir"] = str(tmp_path / "out")
    done = run_playbook("collect", vs, inventory=str(inv))
    assert done.returncode == 0, done.stdout + done.stderr
    tarball = tmp_path / "out" / "box" / "lk" / "data.tar.gz"
    with tarfile.open(tarball) as t:
        assert "./chunk" in t.getnames()
    assert not Path("/tmp/wb-lk-data.tar.gz").exists()  # remote copy removed
