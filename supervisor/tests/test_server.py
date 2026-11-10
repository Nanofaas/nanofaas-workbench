import http.client
import json
import os
import re
import signal
import socket
import threading
import time
import urllib.request
from urllib.error import HTTPError

import pytest

from workbench_supervisor.__main__ import main
from workbench_supervisor.checks import Checker
from workbench_supervisor.server import make_server
from workbench_supervisor.state import State

SPEC = {
    "kind": "scrape_up",
    "params": {"job": "node"},
    "toleratedSeconds": 0,
    "graceSeconds": 0,
}


@pytest.fixture
def served():
    state = State()
    server = make_server(state, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield state, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def call(url: str, method: str = "GET", body: bytes | None = None):
    req = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode()
    except HTTPError as err:
        return err.code, err.read().decode()


def put(base: str, name: str, spec: object) -> int:
    return call(f"{base}/targets/{name}", "PUT", json.dumps(spec).encode())[0]


def status(base: str) -> dict:
    code, body = call(f"{base}/status")
    assert code == 200
    return json.loads(body)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_put_status_delete(served):
    _, base = served
    assert put(base, "ne", SPEC) == 204
    assert status(base)["targets"]["ne"]["kind"] == "scrape_up"
    assert call(f"{base}/targets/ne", "DELETE")[0] == 204
    assert status(base)["targets"] == {}
    assert call(f"{base}/targets/ne", "DELETE")[0] == 204


def test_query_strings_are_ignored(served):
    _, base = served
    assert put(base, "ne?x=1", SPEC) == 204
    assert call(f"{base}/status?x=1")[0] == 200
    assert "ne" in status(base)["targets"]
    assert call(f"{base}/metrics?x=1")[0] == 200
    assert call(f"{base}/targets/ne?x=1", "DELETE")[0] == 204
    assert status(base)["targets"] == {}


@pytest.mark.parametrize(
    ("path", "method", "body", "code"),
    [
        ("/targets/ne", "PUT", b"{not json", 400),
        ("/targets/ne", "PUT", b'{"kind": "nope", "params": {}}', 400),
        ("/targets/bad%20name", "PUT", json.dumps(SPEC).encode(), 404),
        ("/targets/", "PUT", json.dumps(SPEC).encode(), 404),
        ("/nope", "GET", None, 404),
        ("/status", "PUT", b"{}", 404),
        ("/status", "DELETE", None, 404),
    ],
)
def test_bad_requests(served, path, method, body, code):
    _, base = served
    assert call(base + path, method, body)[0] == code
    assert status(base)["targets"] == {}


@pytest.mark.parametrize(
    ("length", "code"), [("abc", 400), ("-1", 400), ("70000", 413)]
)
def test_bad_content_length(served, length, code):
    _, base = served
    conn = http.client.HTTPConnection(base.removeprefix("http://"), timeout=5)
    conn.putrequest("PUT", "/targets/ne")
    conn.putheader("Content-Length", length)
    conn.endheaders()
    conn.send(json.dumps(SPEC).encode())
    assert conn.getresponse().status == code
    conn.close()
    assert status(base)["targets"] == {}


def test_deeply_nested_body_is_a_bad_request(served):
    _, base = served
    assert call(f"{base}/targets/ne", "PUT", b"[" * 60_000)[0] == 400
    assert status(base)["targets"] == {}


def test_oversized_body_is_refused(served):
    _, base = served
    assert call(f"{base}/targets/ne", "PUT", b" " * 70_000)[0] == 413


def test_check_error_is_a_failing_target(served):
    state, base = served
    assert put(base, "ne", SPEC) == 204
    state.run_checks(Checker(f"http://127.0.0.1:{free_port()}", interval=1))
    target = status(base)["targets"]["ne"]
    assert target["failing"] is True
    assert "URLError" in target["detail"]
    assert "refused" in target["detail"].lower()
    assert status(base)["state"] == "fault"


def test_removed_target_never_reported(served):
    state, base = served
    entered, release = threading.Event(), threading.Event()

    def blocked(kind, params):
        entered.set()
        release.wait(5)
        return "stale failure"

    put(base, "gone", SPEC)
    put(base, "back", SPEC)
    rounds = threading.Thread(target=state.run_checks, args=(blocked,))
    rounds.start()
    assert entered.wait(5)
    assert call(f"{base}/targets/gone", "DELETE")[0] == 204
    # Removed and put again while its old check runs: the old result is stale.
    call(f"{base}/targets/back", "DELETE")
    put(base, "back", SPEC)
    release.set()
    rounds.join(5)
    report = status(base)
    assert "gone" not in report["targets"]
    assert report["targets"]["back"]["failing"] is False
    assert report["anomalies"] == []
    assert report["state"] == "healthy"
    assert "gone" not in call(f"{base}/metrics")[1]


LINE = re.compile(
    r'^(# (HELP|TYPE) \w+ .+|\w+\{(\w+="[^"\\]*"(,\w+="[^"\\]*")*)\} [01])$'
)


def test_metrics_exposition(served):
    state, base = served
    put(base, "a", SPEC)
    put(base, "b", {**SPEC, "kind": "http_ok", "params": {"url": "http://x/"}})
    state.run_checks(lambda kind, params: "down" if kind == "http_ok" else None)
    code, text = call(f"{base}/metrics")
    assert code == 200
    lines = text.strip().splitlines()
    assert all(LINE.match(line) for line in lines), lines
    assert 'workbench_supervisor_state{state="fault"} 1' in lines
    assert 'workbench_supervisor_state{state="healthy"} 0' in lines
    assert 'workbench_supervisor_target_failing{target="a",kind="scrape_up"} 0' in (
        lines
    )
    assert 'workbench_supervisor_target_failing{target="b",kind="http_ok"} 1' in lines


def test_module_serves_initial_targets():
    port = free_port()
    seen: list[dict] = []

    def poll_then_stop() -> None:
        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                report = status(base)
                if report["checkedAt"]:
                    seen.append(report)
                    break
            except OSError:
                pass
            time.sleep(0.1)
        os.kill(os.getpid(), signal.SIGTERM)

    previous = signal.getsignal(signal.SIGTERM)
    threading.Thread(target=poll_then_stop, daemon=True).start()
    try:
        with pytest.raises(SystemExit) as stopped:
            main(
                ["--port", str(port), "--interval", "0.2",
                 "--prometheus", f"http://127.0.0.1:{free_port()}",
                 "--targets", json.dumps({"ne": SPEC})]
            )  # fmt: skip
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert stopped.value.code == 0
    assert seen, "supervisor never answered with a checked status"
    assert seen[0]["targets"]["ne"]["failing"] is True
    assert seen[0]["state"] == "fault"


@pytest.mark.parametrize(
    "args",
    [
        ["--prometheus", "file:///x"],
        ["--prometheus", "http://p", "--targets", "[]"],
        ["--prometheus", "http://p", "--targets", "{not json"],
        ["--prometheus", "http://p", "--targets", '{"x": {"kind": "nope"}}'],
        ["--prometheus", "http://p", "--interval", "0"],
        ["--prometheus", "http://p", "--targets", json.dumps({"bad name": SPEC})],
    ],
)
def test_module_rejects_bad_arguments(args):
    with pytest.raises(SystemExit) as failed:
        main(args)
    assert failed.value.code == 2


@pytest.mark.parametrize("kind", [[], {}, None, False, 1])
def test_non_string_kind_returns_400_without_modifying_targets(served, kind):
    _, base = served
    assert put(base, "invalid", {"kind": kind, "params": {}}) == 400
    assert status(base)["targets"] == {}
