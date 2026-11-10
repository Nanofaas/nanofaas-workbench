"""Collect collisions across inventory aliases and separate invocations."""

import hashlib
import sys
import tarfile

import pytest

pytestmark = pytest.mark.docker


@pytest.mark.parametrize("separate", [False, True])
def test_same_instance_on_two_hosts_keeps_both_archives(
    run_playbook, tmp_path, separate
):
    for host in ("host-a", "host-b"):
        data = tmp_path / host
        data.mkdir()
        (data / "chunk").write_text(host)
    vs = {
        "collect_dir": str(tmp_path / "out"),
        "instances": [
            {
                "name": "lk",
                "component": "loki",
                "config": {
                    "data_dir": str(tmp_path / "{{ inventory_hostname }}"),
                    "port": 3100,
                },
            }
        ],
    }
    first_digest = None
    groups = [("host-a",), ("host-b",)] if separate else [("host-a", "host-b")]
    for hosts in groups:
        inventory = tmp_path / "inventory.ini"
        inventory.write_text(
            "\n".join(
                f"{h} ansible_connection=local "
                f"ansible_python_interpreter={sys.executable}"
                for h in hosts
            )
        )
        # These aliases share a test Docker daemon; real hosts have separate daemons.
        done = run_playbook("collect", vs, inventory=str(inventory), ANSIBLE_FORKS="1")
        assert done.returncode == 0, done.stdout + done.stderr
        path = tmp_path / "out" / "host-a" / "lk" / "data.tar.gz"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if first_digest is not None:
            assert digest == first_digest
        first_digest = digest
    for host in ("host-a", "host-b"):
        with tarfile.open(tmp_path / "out" / host / "lk" / "data.tar.gz") as archive:
            chunk = archive.extractfile("./chunk")
            assert chunk is not None
            assert chunk.read().decode() == host


def test_collect_rejects_host_path_traversal(run_playbook, tmp_path):
    inventory = tmp_path / "inventory.ini"
    inventory.write_text("../escape ansible_connection=local\n")
    done = run_playbook(
        "collect",
        {"collect_dir": str(tmp_path / "out"), "instances": []},
        inventory=str(inventory),
    )
    assert done.returncode != 0
    assert "inventory_hostname" in done.stdout
    assert not (tmp_path / "escape").exists()
