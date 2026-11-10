import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.kind

CLUSTER = f"wb-test-{uuid.uuid4().hex[:8]}"
NODE = f"{CLUSTER}-control-plane"
WORKER = f"{CLUSTER}-worker"
ROOT = Path(__file__).resolve().parents[2]
SUPERVISOR_IMAGE = "workbench-supervisor:review"
PROBE_IMAGE = yaml.safe_load((ROOT / "roles/common/defaults/main.yml").read_text())[
    "common_probe_image"
]


def _missing() -> list[str]:
    return [t for t in ("kind", "kubectl", "helm") if shutil.which(t) is None]


@pytest.fixture(scope="module")
def kubeconfig(tmp_path_factory):
    """Create a throwaway kind cluster; its kubeconfig stays out of ~/.kube."""
    if missing := _missing():
        pytest.skip(f"{', '.join(missing)} not available")
    path = tmp_path_factory.mktemp("kube") / "config"
    data = path.parent / "data"
    data.mkdir()
    kind_config = path.parent / "kind.yaml"
    kind_config.write_text(
        yaml.safe_dump(
            {
                "kind": "Cluster",
                "apiVersion": "kind.x-k8s.io/v1alpha4",
                "nodes": [
                    {"role": "control-plane"},
                    {
                        "role": "worker",
                        "extraMounts": [
                            {"hostPath": str(data), "containerPath": "/workbench-data"}
                        ],
                    },
                ],
            }
        )
    )
    subprocess.run(
        ["kind", "create", "cluster", "--name", CLUSTER, "--kubeconfig", str(path),
         "--wait", "120s", "--config", str(kind_config)],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
        subprocess.run(
            [
                "docker",
                "build",
                "-t",
                SUPERVISOR_IMAGE,
                "-f",
                str(ROOT / "images/supervisor/Dockerfile"),
                str(ROOT),
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["kind", "load", "docker-image", SUPERVISOR_IMAGE, "--name", CLUSTER],
            check=True,
            capture_output=True,
        )
        yield path
    finally:
        subprocess.run(["kind", "delete", "cluster", "--name", CLUSTER], check=False)


def kubectl(kubeconfig, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl", "--kubeconfig", str(kubeconfig), *args],
        capture_output=True, text=True, check=False,
    )  # fmt: skip


def releases(kubeconfig) -> list:
    out = subprocess.run(
        ["helm", "list", "-A", "-o", "json", "--kubeconfig", str(kubeconfig)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    return json.loads(out.stdout)


def test_pod_form_node_exporter_and_prometheus(run_playbook, kubeconfig, tmp_path):
    config = {"kubeconfig": str(kubeconfig)}
    host_vars = {
        "instances": [
            {
                "name": "ne",
                "component": "node-exporter",
                "form": "pod",
                "config": {**config, "node_name": NODE},
            },
            {
                "name": "supervisor",
                "component": "supervisor",
                "form": "pod",
                "config": {
                    **config,
                    "image": SUPERVISOR_IMAGE,
                    "port": 8099,
                    "prometheus_url": "http://wb-pr:9090",
                    "interval": 1,
                    "targets": {
                        "node": {
                            "kind": "scrape_up",
                            "params": {"job": "node"},
                            "graceSeconds": 0,
                        }
                    },
                },
            },
            {
                "name": "pr",
                "component": "prometheus",
                "form": "pod",
                "config": {
                    **config,
                    "port": 9090,
                    "data_dir": str(tmp_path / "unused"),
                    "scrape_interval": "1s",
                    "jobs": {"node": [{"target": "wb-ne:9100"}]},
                },
            },
        ]
    }
    try:
        done = run_playbook("deploy", host_vars)
        assert done.returncode == 0, done.stdout + done.stderr
        assert {r["name"] for r in releases(kubeconfig)} == {
            "wb-ne",
            "wb-pr",
            "wb-supervisor",
        }
        labelled = kubectl(
            kubeconfig, "get", "pod,deploy,svc,cm", "-l",
            "nanofaas.workbench/instance=pr", "-o", "name",
        )  # fmt: skip
        assert "deployment.apps/wb-pr" in labelled.stdout, labelled.stderr
        client = kubectl(
            kubeconfig,
            "run",
            "wb-client",
            f"--image={PROBE_IMAGE}",
            "--restart=Never",
            "--command",
            "--",
            "sleep",
            "600",
        )
        assert client.returncode == 0, client.stderr
        ready = kubectl(
            kubeconfig,
            "wait",
            "pod/wb-client",
            "--for=condition=Ready",
            "--timeout=120s",
        )
        assert ready.returncode == 0, ready.stderr
        ready = kubectl(
            kubeconfig,
            "exec",
            "wb-client",
            "--",
            "wget",
            "-qO-",
            "http://wb-pr:9090/-/ready",
        )
        assert ready.returncode == 0, ready.stderr
        admin = kubectl(
            kubeconfig,
            "exec",
            "wb-client",
            "--",
            "wget",
            "-qO-",
            "--post-data=",
            "http://wb-pr:9090/api/v1/admin/tsdb/snapshot",
        )
        assert admin.returncode != 0, admin.stdout
        scraped = last = ""
        for _ in range(60):
            got = kubectl(
                kubeconfig, "exec", "wb-client", "--", "wget", "-qO-",
                "http://wb-pr:9090/api/v1/targets",
            )  # fmt: skip
            last = got.stdout + got.stderr
            if '"health":"up"' in got.stdout:
                scraped = got.stdout
                break
            time.sleep(2)
        assert "wb-ne:9100" in scraped, last
        for _ in range(30):
            status = kubectl(
                kubeconfig,
                "exec",
                "wb-client",
                "--",
                "wget",
                "-qO-",
                "http://wb-supervisor:8099/status",
            )
            assert status.returncode == 0, status.stderr
            report = json.loads(status.stdout)
            if report["state"] == "healthy":
                break
            time.sleep(1)
        assert report["state"] == "healthy", report
        assert "node" in report["targets"]
    finally:
        kubectl(kubeconfig, "delete", "pod/wb-client", "--ignore-not-found")
        for _ in range(2):  # the second run is the idempotent one
            gone = run_playbook("undeploy", host_vars)
            assert gone.returncode == 0, gone.stdout + gone.stderr
    assert releases(kubeconfig) == []


def test_loadgen_uses_files_and_loopback_on_selected_worker(
    run_playbook, kubeconfig, generator_rows
):
    data = kubeconfig.parent / "data"
    out = data / "out"
    out.mkdir(mode=0o777)
    out.chmod(0o777)
    script = """from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        body = b'{"status":"success","output":7}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        print(self.headers['Idempotency-Key'], flush=True)
HTTPServer(('127.0.0.1', 18091), Handler).serve_forever()
"""
    echo = kubectl(
        kubeconfig,
        "run",
        "wb-echo",
        f"--image={SUPERVISOR_IMAGE}",
        "--restart=Never",
        "--overrides",
        json.dumps({"spec": {"nodeName": WORKER, "hostNetwork": True}}),
        "--command",
        "--",
        "python",
        "-c",
        script,
    )
    assert echo.returncode == 0, echo.stderr
    ready = kubectl(
        kubeconfig, "wait", "pod/wb-echo", "--for=condition=Ready", "--timeout=90s"
    )
    assert ready.returncode == 0, ready.stderr
    (data / "schedule.json").write_text(
        json.dumps(
            [
                {
                    "originalId": f"row-{i}",
                    "phase": "campaign",
                    "url": "http://127.0.0.1:18091/",
                    "input": {"n": i},
                    "scheduledAt": time.time() + 30 + i,
                }
                for i in range(2)
            ]
        )
    )
    config = {
        "kubeconfig": str(kubeconfig),
        "node_name": WORKER,
        "script": "one-shot.js",
        "output_dir": "/workbench-data/out",
        "mounts": {"/workbench-data": "/sched"},
        "env": {
            "ONE_SHOT_SCHEDULE": "/sched/schedule.json",
            "ONE_SHOT_VUS": "1",
            "ONE_SHOT_DURATION": "60s",
        },
    }
    vs = {
        "instances": [
            {"name": "lg", "component": "loadgen", "form": "pod", "config": config}
        ]
    }
    try:
        for _ in range(2):
            done = run_playbook("deploy", vs)
            assert done.returncode == 0, done.stdout + done.stderr
        pods = json.loads(
            kubectl(
                kubeconfig, "get", "pods", "-l", "job-name=wb-lg", "-o", "json"
            ).stdout
        )["items"]
        assert len(pods) == 1 and pods[0]["spec"]["nodeName"] == WORKER
        done = kubectl(
            kubeconfig, "wait", "job/wb-lg", "--for=condition=Complete", "--timeout=90s"
        )
        assert done.returncode == 0, done.stderr
        rows = generator_rows(out / "generator.jsonl")
        results = [r for r in rows if r["event"] == "result"]
        assert [r["originalId"] for r in results] == ["row-0", "row-1"]
        assert all(r["statusCode"] == 200 and r["outputJson"] == "7" for r in results)
        logs = kubectl(kubeconfig, "logs", "wb-echo").stdout
        assert logs.count("row-0") == logs.count("row-1") == 1
        done = run_playbook("deploy", vs)
        assert done.returncode != 0 and "already ran" in done.stdout
    finally:
        for _ in range(2):
            done = run_playbook("undeploy", vs)
            assert done.returncode == 0, done.stdout + done.stderr
        kubectl(kubeconfig, "delete", "pod/wb-echo", "--ignore-not-found")
    assert releases(kubeconfig) == []


def test_loadgen_missing_worker_directory_never_counts_as_started(
    run_playbook, kubeconfig
):
    vs = {
        "instances": [
            {
                "name": "missing",
                "component": "loadgen",
                "form": "pod",
                "config": {
                    "kubeconfig": str(kubeconfig),
                    "node_name": WORKER,
                    "script": "one-shot.js",
                    "output_dir": "/workbench-data/missing",
                },
            }
        ]
    }
    try:
        start = time.monotonic()
        done = run_playbook("deploy", vs)
        assert done.returncode != 0, done.stdout
        assert time.monotonic() - start < 300
        pods = json.loads(
            kubectl(
                kubeconfig, "get", "pods", "-l", "job-name=wb-missing", "-o", "json"
            ).stdout
        )["items"]
        assert pods and pods[0]["status"]["phase"] == "Pending"
        assert not (kubeconfig.parent / "data" / "missing").exists()
    finally:
        done = run_playbook("undeploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
    assert releases(kubeconfig) == []
