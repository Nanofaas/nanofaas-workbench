"""The pod branch of the roles, against a stub helm and a non-local target."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "chart"


@pytest.fixture
def stub_helm(tmp_path):
    """Put a helm on PATH that records the values and the chart it was given."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "helm"
    script.write_text(
        f"""#!/bin/sh
case "$1" in
  version) echo 'version.BuildInfo{{Version:"v3.16.4"}}';;
  list) echo '[]';;
  upgrade)
    for a in "$@"; do
      case "$a" in
        -f=*) cp "${{a#-f=}}" {tmp_path}/values.yaml;;
        /*) [ -f "$a/Chart.yaml" ] && echo "$a" > {tmp_path}/chart.log;;
      esac
    done
    echo '{{"info":{{"status":"deployed"}}}}';;
  *) echo '{{}}';;
esac
"""
    )
    script.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}, tmp_path


@pytest.fixture
def remote(tmp_path):
    inv = tmp_path / "inv.ini"
    inv.write_text(
        f"box ansible_connection=local ansible_python_interpreter={sys.executable}\n"
    )
    return str(inv)


def lc_vars(name: str, **config) -> dict:
    fixtures = ROOT / "tests/fixtures/fluent-bit"
    return {
        "collect_dir": "/tmp/unused",
        "instances": [
            {
                "name": name,
                "component": "log-collector",
                "form": "pod",
                "config": {
                    "port": 2020,
                    "storage_dir": f"/tmp/{name}-storage",
                    "config_files": {
                        "fluent-bit.conf": str(fixtures / "fluent-bit.conf"),
                        "parsers.conf": str(fixtures / "parsers.conf"),
                    },
                    "loki": {"host": "127.0.0.1", "port": 3100},
                    **config,
                },
            }
        ],
    }


def test_log_collector_pod_without_limits_on_a_remote_target(
    run_playbook, stub_helm, remote
):
    env, tmp = stub_helm
    vs = lc_vars("lcpod")
    try:
        done = run_playbook("deploy", vs, inventory=remote, **env)
        assert done.returncode == 0, done.stdout + done.stderr
        # helm got a chart that exists on the target, not the controller's path
        assert (tmp / "chart.log").read_text().strip() == "/tmp/wb-lcpod/chart"
        values = yaml.safe_load((tmp / "values.yaml").read_text())
        assert values["log_collector"]["resources"] == {}
        assert "Omit" not in json.dumps(values)
        rendered = subprocess.run(
            ["helm", "template", "wb", str(CHART), "-f", str(tmp / "values.yaml")],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        assert rendered.returncode == 0, rendered.stderr
    finally:
        gone = run_playbook("undeploy", vs, inventory=remote, **env)
    assert gone.returncode == 0, gone.stdout + gone.stderr
    assert not Path("/tmp/wb-lcpod").exists()


def test_log_collector_pod_limits_become_resources(run_playbook, stub_helm, remote):
    env, tmp = stub_helm
    vs = lc_vars("lcres", cpus=0.5, memory_mib=128)
    try:
        done = run_playbook("deploy", vs, inventory=remote, **env)
        assert done.returncode == 0, done.stdout + done.stderr
        values = yaml.safe_load((tmp / "values.yaml").read_text())
        assert values["log_collector"]["resources"] == {"cpu": "0.5", "memory": "128Mi"}
    finally:
        run_playbook("undeploy", vs, inventory=remote, **env)


def test_collect_on_a_pod_is_refused(run_playbook):
    done = run_playbook("collect", lc_vars("lcc"))
    assert done.returncode != 0
    assert "collect is not implemented for form: pod" in done.stdout + done.stderr


@pytest.mark.parametrize("component", ["node-exporter", "cadvisor"])
def test_pod_form_needs_a_node_name(run_playbook, component):
    vs = {
        "instances": [
            {"name": "x", "component": component, "form": "pod", "config": {}}
        ]
    }
    done = run_playbook("deploy", vs)
    assert done.returncode != 0
    assert "needs config.node_name" in done.stdout + done.stderr
