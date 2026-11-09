import json
from pathlib import Path

import pytest


def deploy(tool, ansible_env, tmp_path: Path, instances: list[dict], playbook="deploy"):
    vars_file = tmp_path / "v.json"
    vars_file.write_text(json.dumps({"instances": instances}))
    return tool(
        "ansible-playbook", "-i", "localhost,",
        "-e", f"workbench_vars={vars_file}", f"nanofaas.workbench.{playbook}",
        env=ansible_env,
    )  # fmt: skip


def inst(**kw):
    return {"name": "loki", "component": "loki", **kw}


def test_valid_vars_pass(tool, ansible_env, tmp_path):
    done = deploy(
        tool,
        ansible_env,
        tmp_path,
        [
            inst(name="a", component="node-exporter", cpuset="2-3,6"),
            inst(name="b", component="node-exporter", form="pod"),
        ],
        playbook="collect",  # roles run, but collect has nothing to touch
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_duplicate_instance_names_rejected(tool, ansible_env, tmp_path):
    done = deploy(tool, ansible_env, tmp_path, [inst(), inst()])
    assert done.returncode != 0
    assert "invalid instance loki" in done.stdout


def test_unknown_component_rejected(tool, ansible_env, tmp_path):
    done = deploy(tool, ansible_env, tmp_path, [inst(name="x", component="redis")])
    assert done.returncode != 0
    assert "invalid instance x" in done.stdout


@pytest.mark.parametrize("cpuset", ["2-", "a", "1,,2", ""])
def test_bad_cpuset_rejected(tool, ansible_env, tmp_path, cpuset):
    done = deploy(tool, ansible_env, tmp_path, [inst(cpuset=cpuset)])
    assert done.returncode != 0
    assert "invalid instance loki" in done.stdout


@pytest.mark.parametrize("name", ["loki\n", "Loki", "lo_ki"])
def test_bad_name_rejected(tool, ansible_env, tmp_path, name):
    done = deploy(tool, ansible_env, tmp_path, [inst(name=name)])
    assert done.returncode != 0
    assert "invalid instance" in done.stdout


def test_bad_form_rejected(tool, ansible_env, tmp_path):
    done = deploy(tool, ansible_env, tmp_path, [inst(form="vm")])
    assert done.returncode != 0
    assert "invalid instance loki" in done.stdout


def test_cpuset_trailing_newline_rejected(tool, ansible_env, tmp_path):
    done = deploy(tool, ansible_env, tmp_path, [inst(cpuset="2-3\n")])
    assert done.returncode != 0
    assert "invalid instance loki" in done.stdout


@pytest.mark.parametrize(
    "body", ["{}", '{"instances": {"a": 1}}', '{"instances": "x"}']
)
def test_missing_instances_list_rejected(tool, ansible_env, tmp_path, body):
    vars_file = tmp_path / "v.json"
    vars_file.write_text(body)
    done = tool(
        "ansible-playbook", "-i", "localhost,",
        "-e", f"workbench_vars={vars_file}", "nanofaas.workbench.deploy",
        env=ansible_env,
    )  # fmt: skip
    assert done.returncode != 0
    assert f"{vars_file}" in done.stdout
    assert "instances" in done.stdout


@pytest.mark.parametrize("collect_dir", ["out", "./out", "", 3])
def test_relative_collect_dir_rejected(tool, ansible_env, tmp_path, collect_dir):
    vars_file = tmp_path / "v.json"
    vars_file.write_text(json.dumps({"instances": [], "collect_dir": collect_dir}))
    done = tool(
        "ansible-playbook", "-i", "localhost,",
        "-e", f"workbench_vars={vars_file}", "nanofaas.workbench.collect",
        env=ansible_env,
    )  # fmt: skip
    assert done.returncode != 0
    assert "collect_dir must be an absolute path" in done.stdout


def test_absolute_collect_dir_passes(tool, ansible_env, tmp_path):
    vars_file = tmp_path / "v.json"
    vars_file.write_text(json.dumps({"instances": [], "collect_dir": "/abs/out"}))
    done = tool(
        "ansible-playbook", "-i", "localhost,",
        "-e", f"workbench_vars={vars_file}", "nanofaas.workbench.collect",
        env=ansible_env,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
