import json
from pathlib import Path

import pytest


def deploy(tool, ansible_env, tmp_path: Path, instances: list[dict]):
    vars_file = tmp_path / "v.json"
    vars_file.write_text(json.dumps({"instances": instances}))
    return tool(
        "ansible-playbook", "-i", "localhost,", "-c", "local",
        "-e", f"workbench_vars={vars_file}", "nanofaas.workbench.deploy",
        env=ansible_env,
    )  # fmt: skip


def inst(**kw):
    return {"name": "loki", "component": "loki", **kw}


def test_valid_vars_pass(tool, ansible_env, tmp_path):
    done = deploy(
        tool,
        ansible_env,
        tmp_path,
        [inst(cpuset="2-3,6"), inst(name="p", component="prometheus", form="pod")],
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
