import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "chart"

pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm missing")

# component -> (values key, role); values the role would pass besides the image.
COMPONENTS = {
    "prometheus": ("prometheus", {"args": ["--x"], "files": {"prometheus.yml": "a"}}),
    "loki": ("loki", {"args": ["-x"], "files": {"loki.yaml": "a"}}),
    "log-collector": (
        "log_collector",
        {"files": {"fluent-bit.conf": "a", "parsers.conf": "b"}, "env": {"A": 1}},
    ),
    "loadgen": (
        "loadgen",
        {
            "args": ["exec k6"],
            "files": {"one-shot.js": "a"},
            "output_dir": "/tmp/out",
            "mounts": {"/b": "/y", "/a": "/x"},
            "user": "1000:1001",
        },
    ),
    "node-exporter": ("node_exporter", {"args": ["--x"], "node_name": "n"}),
    "cadvisor": ("cadvisor", {"args": ["--x"], "node_name": "n"}),
    "supervisor": ("supervisor", {"args": ["--x"]}),
}


def image(role: str) -> str:
    defaults = yaml.safe_load((ROOT / f"roles/{role}/defaults/main.yml").read_text())
    return next(v for k, v in defaults.items() if k.endswith("_image"))


def values(*components: str) -> dict:
    out: dict = {"instance": "demo"}
    for c in components:
        key, extra = COMPONENTS[c]
        out[key] = {"enabled": True, "image": image(key), **extra}
    return out


def helm(tmp_path: Path, command: str, vals: dict) -> subprocess.CompletedProcess:
    f = tmp_path / "values.json"
    f.write_text(json.dumps(vals))
    args = ["helm", command, *(["wb"] if command == "template" else []), str(CHART)]
    return subprocess.run(
        [*args, "-f", str(f)], capture_output=True, text=True, check=False
    )


def objects(out: str) -> list[dict]:
    return [d for d in yaml.safe_load_all(out) if d]


def test_chart_lints(tmp_path):
    done = helm(tmp_path, "lint", values(*COMPONENTS))
    assert done.returncode == 0, done.stdout + done.stderr


def test_nothing_renders_by_default(tmp_path):
    done = helm(tmp_path, "template", {"instance": "demo"})
    assert done.returncode == 0, done.stderr
    assert objects(done.stdout) == []


@pytest.mark.parametrize("component", COMPONENTS)
def test_every_component_templates(tmp_path, component):
    done = helm(tmp_path, "template", values(component))
    assert done.returncode == 0, done.stderr
    objs = objects(done.stdout)
    assert objs
    for o in objs:
        labels = o["metadata"]["labels"]
        assert labels["nanofaas.workbench/instance"] == "demo"
        assert labels["nanofaas.workbench/component"] == component
        assert o["metadata"]["name"] == "wb-demo"


def test_node_exporter_is_a_pinned_host_pid_pod(tmp_path):
    done = helm(tmp_path, "template", values("node-exporter"))
    (pod,) = [o for o in objects(done.stdout) if o["kind"] == "Pod"]
    assert pod["spec"]["nodeName"] == "n"
    assert pod["spec"]["hostPID"] is True


def test_resources_come_from_values(tmp_path):
    vals = values("loki")
    vals["loki"]["resources"] = {"cpu": "2", "memory": "256Mi"}
    done = helm(tmp_path, "template", vals)
    (dep,) = [o for o in objects(done.stdout) if o["kind"] == "Deployment"]
    res = dep["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert res == {
        "requests": {"cpu": "2", "memory": "256Mi"},
        "limits": {"cpu": "2", "memory": "256Mi"},
    }


def test_loadgen_is_a_run_once_job(tmp_path):
    done = helm(tmp_path, "template", values("loadgen"))
    (job,) = [o for o in objects(done.stdout) if o["kind"] == "Job"]
    spec = job["spec"]["template"]["spec"]
    assert spec["restartPolicy"] == "Never"
    assert job["spec"]["backoffLimit"] == 0
    mounts = {
        v["hostPath"]["path"]: v["name"] for v in spec["volumes"] if "hostPath" in v
    }
    ctr = {m["name"]: m["mountPath"] for m in spec["containers"][0]["volumeMounts"]}
    assert ctr[mounts["/a"]] == "/x"
    assert ctr[mounts["/b"]] == "/y"


def test_configmap_matches_container_config(tool, tmp_path):
    """The chart carries the file the container form writes, byte for byte."""
    instance = {
        "name": "pr",
        "component": "prometheus",
        "config": {
            "scrape_interval": "2s",
            "jobs": {"node": [{"target": "h:9100", "labels": {"k": "v"}}], "none": []},
        },
    }
    rendered = tmp_path / "prometheus.yml"
    template = ROOT / "roles/prometheus/templates/prometheus.yml.j2"
    done = tool(
        "ansible", "localhost", "-c", "local", "-m", "ansible.builtin.template",
        "-a", f"src={template} dest={rendered}",
        "-e", json.dumps({"instance": instance}),
        env={"ANSIBLE_HOME": str(tmp_path / "home"), "ANSIBLE_NOCOLOR": "1"},
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    vals = values("prometheus")
    vals["prometheus"]["files"] = {"prometheus.yml": rendered.read_text()}
    out = helm(tmp_path, "template", vals).stdout
    (cm,) = [o for o in objects(out) if o["kind"] == "ConfigMap"]
    assert cm["data"]["prometheus.yml"] == rendered.read_text()


def test_host_paths_are_typed_so_nothing_is_created_on_the_node(tmp_path):
    out = helm(tmp_path, "template", values("cadvisor", "log-collector", "loadgen"))
    for o in objects(out.stdout):
        spec = o.get("spec", {})
        spec = spec.get("template", {}).get("spec", spec)
        for v in spec.get("volumes", []):
            path = v.get("hostPath", {})
            if path.get("path") == "/var/run/docker.sock":
                assert path["type"] == "Socket"
            if path.get("path") in ("/var/log/pods", "/tmp/out"):
                assert path["type"] == "Directory"


@pytest.mark.parametrize("component", ["prometheus", "supervisor"])
def test_service_targets_pod_network_and_readiness(tmp_path, component):
    done = helm(tmp_path, "template", values(component))
    assert done.returncode == 0, done.stderr
    objs = objects(done.stdout)
    deployment = next(o for o in objs if o["kind"] == "Deployment")
    spec = deployment["spec"]["template"]["spec"]
    assert not spec.get("hostNetwork", False)
    container = spec["containers"][0]
    assert "host" not in container["readinessProbe"]["tcpSocket"]
    assert all("hostPort" not in p for p in container["ports"])
    service = next(o for o in objs if o["kind"] == "Service")
    assert service["spec"].get("type", "ClusterIP") == "ClusterIP"


@pytest.mark.parametrize("component", ["prometheus", "supervisor"])
def test_chart_rejects_loopback_service_bind(tmp_path, component):
    vals = values(component)
    vals[component]["bind"] = "127.0.0.1"
    done = helm(tmp_path, "template", vals)
    assert done.returncode != 0
    assert "loopback" in done.stderr
