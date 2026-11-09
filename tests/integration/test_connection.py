import re
import subprocess

import pytest

pytestmark = pytest.mark.docker


def test_loopback_address_uses_local_connection(run_playbook):
    """No -c local and a broken ssh: 127.0.0.1 must still run in place."""
    host_vars = {"instances": [{"name": "ne", "component": "node-exporter"}]}
    done = run_playbook(
        "undeploy", host_vars, inventory="127.0.0.1,",
        ANSIBLE_SSH_EXECUTABLE="/usr/bin/false",
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr


def test_inventory_interpreter_survives_on_a_remote_alias(run_playbook, tmp_path):
    """A non-local host keeps what its inventory sets."""
    inv = tmp_path / "inv.ini"
    inv.write_text(
        "box ansible_connection=local ansible_python_interpreter=/nonexistent/py\n"
    )
    host_vars = {"instances": [{"name": "ne", "component": "node-exporter"}]}
    done = run_playbook("undeploy", host_vars, inventory=str(inv))
    # The bogus interpreter is used, not replaced by the playbook interpreter.
    assert done.returncode != 0
    assert "/nonexistent/py" in done.stdout + done.stderr


def test_undeploy_runs_instances_in_reverse_order(run_playbook):
    names = ["order-a", "order-b"]
    for n in names:
        subprocess.run(
            ["docker", "run", "-d", "--name", f"wb-{n}", "--label",
             f"nanofaas.workbench/instance={n}", "busybox", "sleep", "300"],
            capture_output=True, check=True,
        )  # fmt: skip
    host_vars = {
        "instances": [{"name": n, "component": "node-exporter"} for n in names]
    }
    try:
        done = run_playbook("undeploy", host_vars)
        assert done.returncode == 0, done.stdout + done.stderr
        included = re.findall(r"included: .*\(item=([\w-]+)\)", done.stdout)
        assert included == list(reversed(names))
    finally:
        subprocess.run(["docker", "rm", "-f", *[f"wb-{n}" for n in names]], check=False)
