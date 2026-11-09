import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "roles/loadgen/files/scripts/one-shot.js"
# sha256 of nanolab's assets/k6/one-shot.js when it was moved here verbatim.
SCRIPT_SHA256 = "a8addc6c3d4b607b1d592139d16b27c010215fdf29e1040ef5e0d52660148c51"


def docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )


def test_script_moved_verbatim():
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == SCRIPT_SHA256


def loadgen_vars(tmp_path, url, rows, duration="30s"):
    name = f"lg{uuid.uuid4().hex[:8]}"
    now = time.time()
    sched = tmp_path / "sched"
    sched.mkdir(exist_ok=True)
    (sched / "s.json").write_text(
        json.dumps(
            [
                {"originalId": f"o{i}", "phase": "campaign", "url": url,
                 "input": {"n": i}, "scheduledAt": now + i * 0.5}
                for i in range(rows)
            ]
        )
    )  # fmt: skip
    out = tmp_path / "out"
    return (
        {
            "instances": [
                {
                    "name": name,
                    "component": "loadgen",
                    "config": {
                        "script": "one-shot.js",
                        "env": {
                            "ONE_SHOT_SCHEDULE": "/sched/s.json",
                            "ONE_SHOT_VUS": str(min(2, rows)),
                            "ONE_SHOT_DURATION": duration,
                        },
                        "mounts": {str(sched): "/sched"},
                        "output_dir": str(out),
                        "user": f"{os.getuid()}:{os.getgid()}",
                    },
                }
            ]
        },
        out,
        f"wb-{name}",
    )


def wait_state(container: str, want: str, timeout=60) -> str:
    state = ""
    for _ in range(timeout):
        state = docker(
            "inspect", container, "--format", "{{.State.Status}} {{.State.ExitCode}}"
        ).stdout.strip()
        if state.startswith(want):
            return state
        time.sleep(1)
    return state


@pytest.mark.docker
def test_one_shot_script_writes_emitted_and_result_rows(
    run_playbook, tmp_path, echo, generator_rows
):
    vs, out, container = loadgen_vars(tmp_path, echo, 2)
    try:
        done = run_playbook("deploy", vs)
        assert done.returncode == 0, done.stdout + done.stderr
        assert wait_state(container, "exited").startswith("exited 0")
        rows = generator_rows(out / "generator.jsonl")
        emitted = [r for r in rows if r.get("event") == "emitted"]
        results = [r for r in rows if r.get("event") == "result"]
        # Owned by the caller (on Docker Desktop this passes either way: the
        # bind mount maps ownership; on Linux it needs the container user).
        assert (out / "generator.jsonl").stat().st_uid == os.getuid()
        assert len(emitted) == 2
        assert len(results) == 2
        assert {r["statusCode"] for r in results} == {200}
        assert {r["executionId"] for r in results} == {"e1"}
    finally:
        run_playbook("undeploy", vs)


@pytest.mark.docker
def test_exit_code_visible_after_finish(run_playbook, tmp_path, echo):
    vs, _, container = loadgen_vars(tmp_path, echo, 1)
    try:
        assert run_playbook("deploy", vs).returncode == 0
        assert wait_state(container, "exited") == "exited 0"
    finally:
        run_playbook("undeploy", vs)


@pytest.mark.docker
def test_undeploy_stops_a_running_generator(run_playbook, tmp_path, echo):
    vs, _, container = loadgen_vars(tmp_path, echo, 200, duration="5m")
    assert run_playbook("deploy", vs).returncode == 0
    assert wait_state(container, "running", 10).startswith("running")
    started = time.monotonic()
    done = run_playbook("undeploy", vs)
    assert done.returncode == 0, done.stdout + done.stderr
    assert time.monotonic() - started < 15
    assert docker("ps", "-aq", "--filter", f"name={container}").stdout.strip() == ""
