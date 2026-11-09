"""Collect tasks against a stub HTTP API, so they run where host networking cannot."""

import http.server
import sys
import tarfile
import threading

import pytest


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
