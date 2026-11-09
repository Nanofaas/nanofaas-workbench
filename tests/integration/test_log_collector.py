import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

FIXTURES = Path(__file__).parents[1] / "fixtures" / "fluent-bit"


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )


def test_log_collector_ships_to_loki(run_playbook, free_port, tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        fb_port = s.getsockname()[1]
    root = tmp_path / "docker"
    (root / "containers").mkdir(parents=True)
    vs = {
        "collect_dir": str(tmp_path / "out"),
        "instances": [
            {"name": "lk", "component": "loki",
             "config": {"port": free_port, "data_dir": str(tmp_path / "loki")}},
            {"name": "lc", "component": "log-collector", "cpuset": "0",
             "config": {
                 "port": fb_port,
                 "docker_root": str(root),
                 "storage_dir": str(tmp_path / "fb"),
                 "cpus": 0.5,
                 "memory_mib": 128,
                 "config_files": {
                     "fluent-bit.conf": str(FIXTURES / "fluent-bit.conf"),
                     "parsers.conf": str(FIXTURES / "parsers.conf"),
                 },
                 "loki": {"host": "127.0.0.1", "port": free_port,
                          "uri": "/loki/api/v1/push", "tls": "Off"},
                 "env": {"FB_HTTP_PORT": str(fb_port)},
             }},
        ],
    }  # fmt: skip
    try:
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        info = json.loads(docker("inspect", "wb-lc").stdout)[0]
        host = info["HostConfig"]
        assert host["NetworkMode"] == "host"
        assert host["ReadonlyRootfs"] is True
        assert host["CapDrop"] == ["ALL"]
        assert "no-new-privileges" in host["SecurityOpt"]
        assert host["NanoCpus"] == 500_000_000
        assert host["Memory"] == 128 * 1024 * 1024
        assert host["LogConfig"] == {
            "Type": "local", "Config": {"max-size": "10m", "max-file": "2"}
        }
        env = info["Config"]["Env"]
        assert {"LOKI_HOST=127.0.0.1", "LOKI_TLS=Off", "LOKI_URI=/loki/api/v1/push"} <= set(env)
        assert f"LOKI_PORT={free_port}" in env

        (root / "containers" / "app.log").write_text("hello-from-wb\n")
        used = shutil.disk_usage(tmp_path)
        shipped = False
        if used.used / used.total < 0.9:
            now = time.time_ns()
            url = (
                f"http://127.0.0.1:{free_port}/loki/api/v1/query_range"
                f"?query=%7Bjob%3D%22wbtest%22%7D&start={now - 600 * 10**9}"
                f"&end={now + 60 * 10**9}"
            )
            for _ in range(30):
                try:
                    if "hello-from-wb" in urllib.request.urlopen(url, timeout=5).read().decode():
                        shipped = True
                        break
                except OSError:
                    pass
                time.sleep(1)
            assert shipped, "line never reached Loki"

        if docker("info", "--format", "{{.OperatingSystem}}").stdout.strip() == (
            "Docker Desktop"
        ):
            pytest.skip("Docker Desktop: host network not reachable, collect needs Linux")
        done = run_playbook("collect", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        out = tmp_path / "out" / "lc"
        assert "fluentbit_input_records_total" in (out / "metrics.txt").read_text()
        if used.used / used.total >= 0.9:
            pytest.skip("host disk over 90%: Loki refuses writes; config/metrics verified")
    finally:
        run_playbook("undeploy", vs)
        assert not Path("/tmp/wb-lc").exists()
