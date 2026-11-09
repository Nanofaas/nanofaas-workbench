import json
import subprocess
import time
import urllib.request

import pytest

pytestmark = pytest.mark.docker

LABEL = "nanofaas.workbench/instance"


def vars_for(port: int, name: str = "ne", **kw) -> dict:
    return {
        "instances": [
            {
                "name": name,
                "component": "node-exporter",
                "config": {"port": port},
                **kw,
            }
        ]
    }


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )


def names(*filters: str) -> list[str]:
    args = [x for f in filters for x in ("--filter", f)]
    return docker("ps", "-a", *args, "--format", "{{.Names}}").stdout.split()


def test_node_exporter_serves_metrics(run_playbook, free_port):
    try:
        done = run_playbook("deploy", vars_for(free_port, cpuset="0"))
        assert done.returncode == 0, done.stdout + done.stderr
        url = f"http://127.0.0.1:{free_port}/metrics"
        body = ""
        for _ in range(20):
            try:
                body = urllib.request.urlopen(url, timeout=3).read().decode()
                break
            except OSError:
                time.sleep(0.5)
        assert "node_cpu_seconds_total" in body
        info = json.loads(docker("inspect", "wb-ne").stdout)[0]
        assert info["Config"]["Labels"][LABEL] == "ne"
        assert (
            info["Config"]["Labels"]["nanofaas.workbench/component"] == "node-exporter"
        )
        assert info["HostConfig"]["CpusetCpus"] == "0"
        assert info["HostConfig"]["PidMode"] == ""
        assert info["HostConfig"]["NetworkMode"] != "host"
    finally:
        run_playbook("undeploy", vars_for(free_port))


def test_undeploy_removes_only_labelled_instance(run_playbook, free_port):
    other = "wb-test-unrelated"
    docker("run", "-d", "--name", other, "busybox", "sleep", "300")
    # The instance is started by hand: undeploy is checked on any engine.
    docker(
        "run", "-d", "--name", "wb-ne", "--label", f"{LABEL}=ne",
        "busybox", "sleep", "300",
    )  # fmt: skip
    try:
        assert names(f"label={LABEL}=ne") == ["wb-ne"]
        done = run_playbook("undeploy", vars_for(free_port))
        assert done.returncode == 0, done.stdout + done.stderr
        assert names(f"label={LABEL}=ne") == []
        assert names(f"name={other}") == [other]
    finally:
        docker("rm", "-f", other)
        run_playbook("undeploy", vars_for(free_port))


def test_undeploy_missing_instance_succeeds(run_playbook, free_port):
    done = run_playbook("undeploy", vars_for(free_port, name="never-deployed"))
    assert done.returncode == 0, done.stdout + done.stderr


def test_pod_form_fails_clearly(run_playbook, free_port):
    done = run_playbook("deploy", vars_for(free_port, form="pod"))
    assert done.returncode != 0
    assert "pod form" in done.stdout
