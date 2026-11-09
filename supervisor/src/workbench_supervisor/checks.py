"""Target specs and the checks behind each kind."""

import json
import re
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError

GIB = 1024**3
LABEL_NAME = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*\Z")
DURATION = re.compile(r"[0-9]+(ms|s|m|h|d|w|y)\Z")

# kind -> {param: (type, default)}; a default of None means required.
PARAMS: dict[str, dict[str, tuple[type, Any]]] = {
    "scrape_up": {"job": (str, None), "labels": (dict, {})},
    "container_running": {"name": (str, None), "node": (str, None)},
    "swap_quiet": {
        "node": (str, None),
        "maxSwapPages": (int, 256),
        "minAvailableBytes": (int, 8 * GIB),
        "window": (str, "30s"),
    },
    "http_ok": {"url": (str, None), "timeoutSeconds": (float, 5)},
}


def _number(value: object, kind: type) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int if kind is int else (int, float))


def _http(url: object) -> bool:
    return isinstance(url, str) and urllib.parse.urlsplit(url).scheme in (
        "http",
        "https",
    )


def validate(spec: object) -> dict[str, Any]:
    """Return a target spec with defaults filled in; raise ValueError if invalid."""
    if not isinstance(spec, dict) or not set(spec) <= {
        "kind",
        "params",
        "toleratedSeconds",
    }:
        raise ValueError("a target is {kind, params, toleratedSeconds}")
    kind = spec.get("kind")
    if kind not in PARAMS:
        raise ValueError(f"kind must be one of {sorted(PARAMS)}")
    given = spec.get("params")
    if not isinstance(given, dict) or not set(given) <= set(PARAMS[kind]):
        raise ValueError(f"{kind} params are {sorted(PARAMS[kind])}")
    params: dict[str, Any] = {}
    for name, (typ, default) in PARAMS[kind].items():
        value = given.get(name, default)
        ok = _number(value, typ) if typ in (int, float) else isinstance(value, typ)
        if value is None or not ok:
            raise ValueError(f"{kind}: {name} must be a {typ.__name__}")
        params[name] = value
    labels = params.get("labels", {})
    if not all(LABEL_NAME.match(k) and isinstance(v, str) for k, v in labels.items()):
        raise ValueError("labels map label names to strings")
    if kind == "swap_quiet" and not DURATION.match(params["window"]):
        raise ValueError("window is a Prometheus duration such as 30s")
    if kind == "http_ok" and not (
        _http(params["url"]) and params["timeoutSeconds"] > 0
    ):
        raise ValueError("http_ok needs an http(s) url and a positive timeout")
    tolerated = spec.get("toleratedSeconds", 0)
    if not _number(tolerated, float) or tolerated < 0:
        raise ValueError("toleratedSeconds is a non-negative number")
    return {"kind": kind, "params": params, "toleratedSeconds": tolerated}


def _selector(metric: str, labels: dict[str, str]) -> str:
    # A JSON string is a valid PromQL string literal.
    inner = ",".join(f"{k}={json.dumps(v)}" for k, v in labels.items())
    return f"{metric}{{{inner}}}"


class Checker:
    """Run a target's check: None when it passes, else what failed.

    Errors reaching Prometheus or the URL raise; the caller records them.
    """

    def __init__(
        self,
        prometheus: str,
        interval: float,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        """Query `prometheus`; `opener` is urllib's `open` unless injected."""
        self.prometheus = prometheus.rstrip("/")
        self.interval = interval
        self.open = opener or urllib.request.build_opener().open

    def __call__(self, kind: str, params: dict[str, Any]) -> str | None:
        """Check one target."""
        return getattr(self, kind)(params)

    def query(self, promql: str) -> list[float]:
        """Return the values of an instant vector query."""
        url = f"{self.prometheus}/api/v1/query?" + urllib.parse.urlencode(
            {"query": promql}
        )
        with self.open(url, timeout=max(self.interval, 1)) as resp:
            body = json.load(resp)
        if body.get("status") != "success":
            raise URLError(f"prometheus: {body.get('error')}")
        return [float(r["value"][1]) for r in body["data"]["result"]]

    def scrape_up(self, p: dict[str, Any]) -> str | None:
        """Fail unless every matching `up` series is 1."""
        promql = _selector("up", {"job": p["job"], **p["labels"]})
        values = self.query(promql)
        if not values:
            return f"no series for {promql}"
        if any(v != 1 for v in values):
            return f"{promql} = {values}"
        return None

    def container_running(self, p: dict[str, Any]) -> str | None:
        """Fail unless cAdvisor saw the container within 3 intervals."""
        name, node = p["name"], p["node"]
        promql = "time() - " + _selector(
            "container_last_seen", {"name": name, "node": node}
        )
        values = self.query(promql)
        if not values:
            return f"container {name} on {node}: never seen"
        if min(values) > 3 * self.interval:
            return f"container {name} on {node}: last seen {min(values):.0f}s ago"
        return None

    def swap_quiet(self, p: dict[str, Any]) -> str | None:
        """Fail on swapping or low available memory."""
        node, window = p["node"], p["window"]
        sel = {"node": node}
        swapped = self.query(
            f"increase({_selector('node_vmstat_pswpin', sel)}[{window}])"
            f" + increase({_selector('node_vmstat_pswpout', sel)}[{window}])"
        )
        available = self.query(_selector("node_memory_MemAvailable_bytes", sel))
        if not swapped or not available:
            return f"no swap or memory series for node {node}"
        if max(swapped) > p["maxSwapPages"]:
            return f"{node}: {max(swapped):.0f} swap pages in {window}"
        if min(available) < p["minAvailableBytes"]:
            return f"{node}: MemAvailable {min(available):.0f} bytes"
        return None

    def http_ok(self, p: dict[str, Any]) -> str | None:
        """Fail unless GET url returns 2xx."""
        url = p["url"]
        try:
            with self.open(url, timeout=p["timeoutSeconds"]) as resp:
                code = resp.status
        except HTTPError as err:
            code = err.code
        return None if 200 <= code < 300 else f"GET {url}: HTTP {code}"
