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
