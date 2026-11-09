"""Collect tasks against a stub HTTP API, so they run where host networking cannot.

Archiving runs in a throwaway container on the target, so these need Docker.
"""

import http.server
import os
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BUSYBOX = yaml.safe_load((ROOT / "roles/common/defaults/main.yml").read_text())[
    "common_probe_image"
]

pytestmark = pytest.mark.docker


@pytest.fixture
def stub_api(free_port):
    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bytes) -> None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send(b"fluentbit_input_records_total 3\n")

        def do_POST(self):
            self._send(b'{"status":"success","data":{"name":"snap1"}}')

        def log_message(self, format, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", free_port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield free_port
    server.shutdown()


def remote_inventory(tmp_path):
    inv = tmp_path / "inv.ini"
    inv.write_text(
        f"box ansible_connection=local ansible_python_interpreter={sys.executable}\n"
    )
    return str(inv)


def test_prometheus_collect_archives_the_snapshot(run_playbook, stub_api, tmp_path):
    data = tmp_path / "d"
    (data / "snapshots" / "snap1").mkdir(parents=True)
    (data / "snapshots" / "snap1" / "meta.json").write_text("{}")
    vs = {
        "collect_dir": str(tmp_path / "out"),
        "instances": [{"name": "pr", "component": "prometheus",
                       "config": {"port": stub_api, "data_dir": str(data)}}],
    }  # fmt: skip
    done = run_playbook("collect", vs)
    assert done.returncode == 0, done.stdout + done.stderr
    with tarfile.open(tmp_path / "out" / "pr" / "prometheus-snapshot.tar.gz") as t:
        assert "./meta.json" in t.getnames()


def test_log_collector_collect_stores_metrics_and_storage(
    run_playbook, stub_api, tmp_path
):
    storage = tmp_path / "fb"
    storage.mkdir()
    (storage / "tail.db").write_text("x")
    vs = {
        "collect_dir": str(tmp_path / "out"),
        "instances": [{"name": "lc", "component": "log-collector",
                       "config": {"port": stub_api, "storage_dir": str(storage),
                                  "config_files": {}, "loki": {}}}],
    }  # fmt: skip
    for inventory, has_tar in (
        ("localhost,", False),
        (remote_inventory(tmp_path), True),
    ):
        done = run_playbook("collect", vs, inventory=inventory)
        assert done.returncode == 0, done.stdout + done.stderr
        out = tmp_path / "out" / "lc"
        assert "fluentbit_input_records_total" in (out / "metrics.txt").read_text()
        assert (out / "storage.tar.gz").exists() == has_tar


def test_remote_collect_reads_files_a_container_wrote_as_another_uid(
    run_playbook, tmp_path
):
    """Loki's data: uid 10001, a 0700 dir and a 0600 file the caller cannot read."""
    data = tmp_path / "loki"
    data.mkdir()
    data.chmod(0o777)
    volume = f"{data}:/d"

    def in_container(user: str, script: str) -> None:
        done = subprocess.run(
            ["docker", "run", "--rm", "--user", user, "-v", volume, BUSYBOX,
             "sh", "-c", script],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr

    in_container(
        "10001:10001",
        "mkdir /d/chunks && chmod 700 /d/chunks && echo x > /d/chunks/c"
        " && chmod 600 /d/chunks/c",
    )
    try:
        if sys.platform == "linux" and os.getuid() != 0:
            # The point of the test; Docker Desktop's file sharing maps
            # ownership to the Mac user, so only Linux can show it.
            assert not os.access(data / "chunks", os.R_OK)
        vs = {
            "collect_dir": str(tmp_path / "out"),
            "instances": [{"name": "lk", "component": "loki",
                           "config": {"port": 3100, "data_dir": str(data)}}],
        }  # fmt: skip
        done = run_playbook("collect", vs, inventory=remote_inventory(tmp_path))
        assert done.returncode == 0, done.stdout + done.stderr
        archive = tmp_path / "out" / "lk" / "data.tar.gz"
        assert archive.stat().st_uid == os.getuid()
        with tarfile.open(archive) as t:
            member = t.extractfile("./chunks/c")
            assert member is not None
            assert member.read() == b"x\n"
    finally:
        in_container("0:0", "rm -rf /d/chunks")


def loki_collect(run_playbook, tmp_path, data):
    vs = {
        "collect_dir": str(tmp_path / "out"),
        "instances": [{"name": "lk", "component": "loki",
                       "config": {"port": 3100, "data_dir": str(data)}}],
    }  # fmt: skip
    return run_playbook("collect", vs, inventory=remote_inventory(tmp_path))


def test_collect_fails_when_the_archive_cannot_be_completed(run_playbook, tmp_path):
    """A source tar cannot enter exits 1 with an unusable archive; that is a failure."""
    not_a_dir = tmp_path / "file"
    not_a_dir.write_text("x")
    done = loki_collect(run_playbook, tmp_path, not_a_dir)
    assert done.returncode != 0, done.stdout
    assert not (tmp_path / "out" / "lk" / "data.tar.gz").exists()


def test_collect_fails_clearly_for_a_missing_source_dir(run_playbook, tmp_path):
    missing = tmp_path / "missing"
    done = loki_collect(run_playbook, tmp_path, missing)
    assert done.returncode != 0, done.stdout
    assert "does not exist" in done.stdout
    assert not missing.exists()


def test_collect_does_not_destroy_an_instance_named_collect(run_playbook, tmp_path):
    name = "wb-lk-collect"  # the container of an instance called "lk-collect"
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
    subprocess.run(
        ["docker", "run", "-d", "--name", name, BUSYBOX, "sleep", "300"],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        data = tmp_path / "d"
        data.mkdir()
        done = loki_collect(run_playbook, tmp_path, data)
        assert done.returncode == 0, done.stdout + done.stderr
        running = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", name],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert running.stdout.strip() == "true"
    finally:
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
