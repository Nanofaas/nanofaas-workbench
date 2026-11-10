"""Every container-form component, deployed, collected and undeployed in one run."""

import json
import socket
import subprocess
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.docker

ROOT = Path(__file__).parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "fluent-bit"
IMAGE = "ghcr.io/nanofaas/workbench-supervisor:test"
LABEL = "nanofaas.workbench/instance"


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


def poll(fn, seconds: int, what: str):
    got = None
    for _ in range(seconds):
        got = fn()
        if got:
            return got
        time.sleep(1)
    pytest.fail(f"never {what}: {got}")


def test_one_shot_shape(run_playbook, host_get, echo, generator_rows, tmp_path):
    done = docker(
        "build", "-t", IMAGE, "-f", str(ROOT / "images/supervisor/Dockerfile"),
        str(ROOT),
    )  # fmt: skip
    assert done.returncode == 0, done.stderr

    uid = uuid.uuid4().hex[:6]
    n = {c: f"{c}{uid}" for c in ("ne", "cad", "lk", "lc", "pr", "sv", "lg")}
    ne_p, cad_p, lk_p, lc_p, pr_p, sv_p = ports(6)
    root = tmp_path / "docker"
    (root / "containers").mkdir(parents=True)
    now = time.time()
    sched = tmp_path / "sched"
    sched.mkdir()
    (sched / "s.json").write_text(
        json.dumps(
            [
                {"originalId": f"o{i}", "phase": "campaign", "url": echo,
                 "input": {"n": i}, "scheduledAt": now + i * 0.5}
                for i in range(3)
            ]
        )
    )  # fmt: skip
    out = tmp_path / "lg-out"
    node = {"labels": {"node": "n1"}}
    vs = {
        "collect_dir": str(tmp_path / "collected"),
        "instances": [
            {"name": n["ne"], "component": "node-exporter",
             "config": {"port": ne_p}},
            {"name": n["cad"], "component": "cadvisor",
             "config": {"port": cad_p}},
            {"name": n["lk"], "component": "loki",
             "config": {"port": lk_p, "data_dir": str(tmp_path / "loki")}},
            {"name": n["lc"], "component": "log-collector",
             "config": {
                 "port": lc_p,
                 "docker_root": str(root),
                 "storage_dir": str(tmp_path / "fb"),
                 "config_files": {
                     "fluent-bit.conf": str(FIXTURES / "fluent-bit.conf"),
                     "parsers.conf": str(FIXTURES / "parsers.conf"),
                 },
                 "loki": {"host": "127.0.0.1", "port": lk_p,
                          "uri": "/loki/api/v1/push", "tls": "Off"},
                 "env": {"FB_HTTP_PORT": str(lc_p)},
             }},
            {"name": n["pr"], "component": "prometheus",
             "config": {
                 "port": pr_p,
                 "data_dir": str(tmp_path / "prom"),
                 "scrape_interval": "1s",
                 "jobs": {
                     "node": [{"target": f"127.0.0.1:{ne_p}", **node}],
                     "cadvisor": [{"target": f"127.0.0.1:{cad_p}", **node}],
                 },
             }},
            {"name": n["sv"], "component": "supervisor",
             "config": {
                 "image": IMAGE,
                 "port": sv_p,
                 "prometheus_url": f"http://127.0.0.1:{pr_p}",
                 "interval": 1,
                 "targets": {
                     "node": {"kind": "scrape_up", "toleratedSeconds": 60,
                              "params": {"job": "node", "labels": node["labels"]}},
                     "ne": {"kind": "container_running", "toleratedSeconds": 60,
                             "params": {"name": f"wb-{n['ne']}", "node": "n1"}},
                 },
             }},
            {"name": n["lg"], "component": "loadgen",
             "config": {
                 "script": "one-shot.js",
                 "env": {"ONE_SHOT_SCHEDULE": "/sched/s.json",
                         "ONE_SHOT_VUS": "2", "ONE_SHOT_DURATION": "30s"},
                 "mounts": {str(sched): "/sched"},
                 "output_dir": str(out),
             }},
        ],
    }  # fmt: skip

    def query(q: str) -> list:
        url = f"http://127.0.0.1:{pr_p}/api/v1/query?query={q}"
        return json.loads(host_get(url) or "{}").get("data", {}).get("result", [])

    def supervisor_healthy() -> bool:
        report = json.loads(host_get(f"http://127.0.0.1:{sv_p}/status") or "{}")
        return report.get("state") == "healthy" and report.get("checkedAt")

    def leftovers() -> list[str]:
        return [
            c for c in docker(
                "ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.Names}}"
            ).stdout.split()
            if c in {f"wb-{v}" for v in n.values()}
        ]  # fmt: skip

    try:
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        poll(supervisor_healthy, 60, "healthy")
        poll(lambda: query("node_cpu_seconds_total"), 60, "node_cpu_seconds_total")
        poll(
            lambda: query("container_cpu_usage_seconds_total"),
            60,
            "container_cpu_usage_seconds_total",
        )
        poll(
            lambda: docker("inspect", f"wb-{n['lg']}", "--format",
                           "{{.State.Status}}").stdout.strip() == "exited",
            60, "loadgen exit",
        )  # fmt: skip
        rows = generator_rows(out / "generator.jsonl")
        results = [r for r in rows if r["event"] == "result"]
        assert len(results) == 3

        if docker("info", "--format", "{{.OperatingSystem}}").stdout.strip() == (
            "Docker Desktop"
        ):
            collected = False  # host network unreachable from the controller
        else:
            done = run_playbook("collect", vs)
            assert done.returncode == 0, done.stdout + done.stderr
            got = tmp_path / "collected" / "localhost"
            assert (
                "fluentbit_input_records_total"
                in (got / n["lc"] / "metrics.txt").read_text()
            )
            assert (got / n["pr"] / "prometheus-snapshot.tar.gz").is_file()
            collected = True
    finally:
        done = run_playbook("undeploy", vs)
    assert done.returncode == 0, done.stdout + done.stderr
    assert leftovers() == []
    if not collected:
        pytest.skip("Docker Desktop: host network not reachable, collect needs Linux")
