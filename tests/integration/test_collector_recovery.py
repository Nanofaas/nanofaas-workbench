"""Collection attempts raw recovery even when the metrics endpoint has failed."""

import hashlib
import json
import subprocess
import sys
import tarfile
import uuid

import pytest

pytestmark = pytest.mark.docker
IMAGE = (
    "busybox@sha256:a7dbc319b1438115a207e11930dc4bb3e643dcb3ec0bdd694bb36cd8fad289ec"
)


@pytest.mark.parametrize(
    ("mode", "running"), [("snapshot", False), ("final", False), ("final", True)]
)
def test_dead_metrics_do_not_prevent_recovering_buffers(
    run_playbook, tmp_path, mode, running
):
    name = "recover-" + uuid.uuid4().hex[:8]
    source = tmp_path / "buffers"
    source.mkdir()
    (source / "chunk").write_text("unshipped evidence")
    subprocess.run(["docker", "pull", IMAGE], check=True, capture_output=True)
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            f"wb-{name}",
            "--label",
            f"nanofaas.workbench/instance={name}",
            IMAGE,
            "sh",
            "-c",
            "trap 'echo shutdown-evidence; exit' TERM; echo collector-evidence; "
            "while :; do sleep 1 & wait $!; done",
        ],
        check=True,
        capture_output=True,
    )
    if not running:
        subprocess.run(
            ["docker", "stop", "-t", "1", f"wb-{name}"], check=True, capture_output=True
        )
    inventory = tmp_path / "inventory.ini"
    inventory.write_text(
        f"edge ansible_connection=local ansible_python_interpreter={sys.executable}\n"
    )
    variables = {
        "collect_dir": str(tmp_path / "out"),
        "instances": [
            {
                "name": name,
                "component": "log-collector",
                "config": {
                    "port": 9,
                    "storage_dir": str(source),
                    "collect_mode": mode,
                },
            }
        ],
    }
    try:
        done = run_playbook("collect", variables, inventory=str(inventory))
        assert done.returncode != 0  # Unavailable metrics remain a visible failure.
        directory = tmp_path / "out/edge" / name
        archive = directory / "storage.tar.gz"
        assert archive.is_file(), done.stdout + done.stderr
        with tarfile.open(archive) as saved:
            chunk = saved.extractfile("./chunk")
            assert chunk is not None and chunk.read() == b"unshipped evidence"
        assert (
            archive.with_name("storage.tar.gz.sha256").read_text().strip()
            == hashlib.sha256(archive.read_bytes()).hexdigest()
        )
        receipt = json.loads((directory / "collection.json").read_text())
        assert (
            receipt["archiveSha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
        )
        assert receipt["metricsAvailable"] is False
        assert (source / "chunk").read_text() == "unshipped evidence"
        if mode == "final":
            assert receipt["quiesced"] is True
            state = json.loads(
                subprocess.check_output(["docker", "inspect", f"wb-{name}"], text=True)
            )[0]
            assert state["State"]["Running"] is False
            assert "collector-evidence" in (directory / "container.log").read_text()
            assert "shutdown-evidence" in (directory / "container.log").read_text()
    finally:
        subprocess.run(["docker", "rm", "-f", f"wb-{name}"], capture_output=True)


def test_missing_source_is_never_created_by_collection(run_playbook, tmp_path):
    source = tmp_path / "missing"
    done = run_playbook(
        "collect",
        {
            "collect_dir": str(tmp_path / "out"),
            "instances": [
                {
                    "name": "missing-recovery",
                    "component": "log-collector",
                    "config": {
                        "port": 9,
                        "storage_dir": str(source),
                        "collect_mode": "final",
                    },
                }
            ],
        },
    )
    assert done.returncode != 0
    assert not source.exists()
    receipt = json.loads(
        (tmp_path / "out/localhost/missing-recovery/collection.json").read_text()
    )
    assert receipt["archiveSha256"] is None


def test_final_collection_does_not_stop_an_unrelated_container(run_playbook, tmp_path):
    name = "unowned-" + uuid.uuid4().hex[:8]
    subprocess.run(
        ["docker", "run", "-d", "--name", f"wb-{name}", IMAGE, "sleep", "300"],
        check=True,
        capture_output=True,
    )
    try:
        done = run_playbook(
            "collect",
            {
                "collect_dir": str(tmp_path / "out"),
                "instances": [
                    {
                        "name": name,
                        "component": "log-collector",
                        "config": {
                            "port": 9,
                            "storage_dir": str(tmp_path / "storage"),
                            "collect_mode": "final",
                        },
                    }
                ],
            },
        )
        assert done.returncode != 0
        assert "unrelated collector" in done.stdout
        info = json.loads(
            subprocess.check_output(["docker", "inspect", f"wb-{name}"], text=True)
        )[0]
        assert info["State"]["Running"] is True
        receipt = json.loads(
            (tmp_path / "out/localhost" / name / "collection.json").read_text()
        )
        assert receipt["quiesced"] is False and receipt["archiveSha256"] is None
    finally:
        subprocess.run(["docker", "rm", "-f", f"wb-{name}"], capture_output=True)
