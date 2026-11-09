import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError

import pytest

from workbench_supervisor.checks import Checker, validate

GIB = 1024**3


def check(prom, kind: str, **params):
    spec = validate({"kind": kind, "params": params})
    return Checker(prom.url, interval=5)(spec["kind"], spec["params"])


# scrape_up

UP = 'up{job="node",node="n1"}'


def test_scrape_up_passes_when_up(prom):
    prom.results[UP] = [1]
    assert check(prom, "scrape_up", job="node", labels={"node": "n1"}) is None
    assert prom.queries == [UP]


def test_scrape_up_fails_when_down(prom):
    prom.results[UP] = [1, 0]
    detail = check(prom, "scrape_up", job="node", labels={"node": "n1"})
    assert detail is not None
    assert UP in detail


def test_scrape_up_fails_without_series(prom):
    detail = check(prom, "scrape_up", job="node", labels={"node": "n1"})
    assert detail is not None
    assert "no series" in detail


def test_scrape_up_labels_are_optional(prom):
    prom.results['up{job="node"}'] = [1]
    assert check(prom, "scrape_up", job="node") is None


def test_scrape_up_escapes_label_values(prom):
    check(prom, "scrape_up", job='a"b')
    assert prom.queries == ['up{job="a\\"b"}']


# container_running

SEEN = 'time() - container_last_seen{name="wb-x",node="n1"}'


def test_container_running_passes_when_recently_seen(prom):
    prom.results[SEEN] = [15]  # 3 * interval
    assert check(prom, "container_running", name="wb-x", node="n1") is None


def test_container_running_fails_when_stale(prom):
    prom.results[SEEN] = [15.5]
    detail = check(prom, "container_running", name="wb-x", node="n1")
    assert detail is not None
    assert "wb-x" in detail


def test_container_running_fails_without_series(prom):
    assert check(prom, "container_running", name="wb-x", node="n1") is not None


# swap_quiet

SWAP = (
    'increase(node_vmstat_pswpin{node="n1"}[30s])'
    ' + increase(node_vmstat_pswpout{node="n1"}[30s])'
)
MEM = 'node_memory_MemAvailable_bytes{node="n1"}'


def test_swap_quiet_passes_with_defaults(prom):
    prom.results[SWAP] = [256]
    prom.results[MEM] = [8 * GIB]
    assert check(prom, "swap_quiet", node="n1") is None
    assert sorted(prom.queries) == sorted([SWAP, MEM])


def test_swap_quiet_fails_on_swapping(prom):
    prom.results[SWAP] = [257]
    prom.results[MEM] = [16 * GIB]
    detail = check(prom, "swap_quiet", node="n1")
    assert detail is not None
    assert "swap" in detail


def test_swap_quiet_fails_on_low_memory(prom):
    prom.results[SWAP] = [0]
    prom.results[MEM] = [8 * GIB - 1]
    detail = check(prom, "swap_quiet", node="n1")
    assert detail is not None
    assert "MemAvailable" in detail


def test_swap_quiet_honours_params(prom):
    swap = SWAP.replace("30s", "1m")
    prom.results[swap] = [10]
    prom.results[MEM] = [2 * GIB]
    tight = {"maxSwapPages": 5, "minAvailableBytes": GIB, "window": "1m"}
    assert check(prom, "swap_quiet", node="n1", **tight) is not None
    loose = {**tight, "maxSwapPages": 10}
    assert check(prom, "swap_quiet", node="n1", **loose) is None


def test_swap_quiet_fails_without_series(prom):
    assert check(prom, "swap_quiet", node="n1") is not None


def test_prometheus_error_raises(prom):
    prom.status = "error"
    with pytest.raises(URLError):
        check(prom, "scrape_up", job="node")


# http_ok


@pytest.fixture
def web():
    codes: list[int] = [200]

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(codes[0])
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/health", codes
    server.shutdown()
    server.server_close()


def test_http_ok_passes_on_2xx(prom, web):
    url, codes = web
    codes[0] = 204
    assert check(prom, "http_ok", url=url, timeoutSeconds=2) is None


def test_http_ok_fails_on_5xx(prom, web):
    url, codes = web
    codes[0] = 503
    detail = check(prom, "http_ok", url=url)
    assert detail is not None
    assert "503" in detail


def test_http_ok_raises_when_refused(prom):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(URLError):
        check(prom, "http_ok", url=f"http://127.0.0.1:{port}/")


# validate


def test_validate_fills_defaults():
    spec = validate({"kind": "swap_quiet", "params": {"node": "n1"}})
    assert spec == {
        "kind": "swap_quiet",
        "params": {"node": "n1", "maxSwapPages": 256,
                   "minAvailableBytes": 8 * GIB, "window": "30s"},
        "toleratedSeconds": 0,
    }  # fmt: skip
    assert validate({"kind": "http_ok", "params": {"url": "https://x/"}})["params"] == {
        "url": "https://x/",
        "timeoutSeconds": 5,
    }


@pytest.mark.parametrize(
    "spec",
    [
        None,
        [],
        {"kind": "nope", "params": {}},
        {"kind": "scrape_up"},
        {"kind": "scrape_up", "params": {}},
        {"kind": "scrape_up", "params": {"job": 1}},
        {"kind": "scrape_up", "params": {"job": "j", "labels": {"bad-name": "v"}}},
        {"kind": "scrape_up", "params": {"job": "j", "labels": {"a": 1}}},
        {"kind": "scrape_up", "params": {"job": "j", "labels": []}},
        {"kind": "scrape_up", "params": {"job": "j", "extra": 1}},
        {"kind": "scrape_up", "params": {"job": "j"}, "toleratedSeconds": -1},
        {"kind": "scrape_up", "params": {"job": "j"}, "toleratedSeconds": "5"},
        {"kind": "scrape_up", "params": {"job": "j"}, "toleratedSeconds": True},
        {"kind": "scrape_up", "params": {"job": "j"}, "other": 1},
        {"kind": "swap_quiet", "params": {"node": "n", "window": "30s) or vector(1"}},
        {"kind": "swap_quiet", "params": {"node": "n", "maxSwapPages": "1"}},
        {"kind": "http_ok", "params": {"url": "file:///etc/passwd"}},
        {"kind": "http_ok", "params": {"url": "http://x/", "timeoutSeconds": 0}},
    ],
)
def test_validate_rejects(spec):
    with pytest.raises(ValueError):  # noqa: PT011
        validate(spec)
