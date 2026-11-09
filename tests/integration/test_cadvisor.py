import json
import subprocess
import time
import urllib.request

import pytest

pytestmark = pytest.mark.docker


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )


def vars_for(port: int) -> dict:
    return {
        "instances": [
            {"name": "cad", "component": "cadvisor", "config": {"port": port}}
        ]
    }


def test_cadvisor_reports_labelled_containers(run_playbook, free_port):
    docker("rm", "-f", "probe")
    docker("run", "-d", "--name", "probe", "--label", "role=probe", "busybox",
           "sleep", "300")  # fmt: skip
    try:
        done = run_playbook("deploy", vars_for(free_port))
        assert done.returncode == 0, done.stdout + done.stderr
        info = json.loads(docker("inspect", "wb-cad").stdout)[0]
        assert info["HostConfig"]["PidMode"] == ""
        assert info["HostConfig"]["NetworkMode"] != "host"
        assert "127.0.0.1" in docker("port", "wb-cad").stdout
        url = f"http://127.0.0.1:{free_port}/metrics"
        series = ""
        for _ in range(40):
            try:
                body = urllib.request.urlopen(url, timeout=3).read().decode()
            except OSError:
                body = ""
            series = next(
                (
                    ln for ln in body.splitlines()
                    if ln.startswith("container_last_seen{")
                    and 'container_label_role="probe"' in ln
                ),
                "",
            )  # fmt: skip
            if series:
                break
            time.sleep(1)
        assert 'name="probe"' in series, series
    finally:
        docker("rm", "-f", "probe")
        run_playbook("undeploy", vars_for(free_port))
