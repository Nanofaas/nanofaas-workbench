import json
import shutil
import subprocess
import time
import uuid

import pytest

pytestmark = pytest.mark.kind

CLUSTER = f"wb-test-{uuid.uuid4().hex[:8]}"
NODE = f"{CLUSTER}-control-plane"


def _missing() -> list[str]:
    return [t for t in ("kind", "kubectl", "helm") if shutil.which(t) is None]


@pytest.fixture(scope="module")
def kubeconfig(tmp_path_factory):
    """Create a throwaway kind cluster; its kubeconfig stays out of ~/.kube."""
    if missing := _missing():
        pytest.skip(f"{', '.join(missing)} not available")
    path = tmp_path_factory.mktemp("kube") / "config"
    subprocess.run(
        ["kind", "create", "cluster", "--name", CLUSTER, "--kubeconfig", str(path),
         "--wait", "120s"],
        check=True, capture_output=True,
    )  # fmt: skip
    try:
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
        assert {r["name"] for r in releases(kubeconfig)} == {"wb-ne", "wb-pr"}
        labelled = kubectl(
            kubeconfig, "get", "pod,deploy,svc,cm", "-l",
            "nanofaas.workbench/instance=pr", "-o", "name",
        )  # fmt: skip
        assert "deployment.apps/wb-pr" in labelled.stdout, labelled.stderr
        scraped = last = ""
        for _ in range(60):
            got = kubectl(
                kubeconfig, "exec", "deploy/wb-pr", "--", "wget", "-qO-",
                "http://127.0.0.1:9090/api/v1/targets",
            )  # fmt: skip
            last = got.stdout + got.stderr
            if '"health":"up"' in got.stdout:
                scraped = got.stdout
                break
            time.sleep(2)
        assert "wb-ne:9100" in scraped, last
    finally:
        for _ in range(2):  # the second run is the idempotent one
            gone = run_playbook("undeploy", host_vars)
            assert gone.returncode == 0, gone.stdout + gone.stderr
    assert releases(kubeconfig) == []
