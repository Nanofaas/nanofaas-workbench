"""Targets and their health.

A target failing inside its grace (graceSeconds from its put) is only degraded;
its tolerance counts from the later of the failure's start and the grace's end.

Checks run outside the lock. Each put gives the target a new generation, and a
check result is applied only to the generation it was started for, so a target
removed (or replaced) while its check runs is never reported again.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

Check = Callable[[str, dict[str, Any]], str | None]


def iso(t: float | None) -> str | None:
    """Format a POSIX time as ISO 8601 UTC."""
    if t is None:
        return None
    return datetime.fromtimestamp(t, UTC).isoformat(timespec="milliseconds")


@dataclass
class _Target:
    spec: dict[str, Any]
    gen: int
    created: float  # put at, monotonic: the grace starts here
    since: float | None = None  # failing since, wall clock (reported)
    started: float = 0.0  # failing since, monotonic (measured)
    detail: str | None = None
    fault: tuple[float, str | None] | None = None  # sticky: (since, detail)


class State:
    """The targets, their failures and the overall state."""

    def __init__(
        self,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Keep no targets; `clock` stamps times, `monotonic` measures them."""
        self._clock = clock
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._targets: dict[str, _Target] = {}
        self._gen = 0
        self._checked_at: float | None = None

    def put(self, name: str, spec: dict[str, Any]) -> None:
        """Add or replace a target; the same spec again keeps its state."""
        with self._lock:
            old = self._targets.get(name)
            if old is not None and old.spec == spec:
                return
            self._gen += 1
            self._targets[name] = _Target(spec, self._gen, self._monotonic())

    def remove(self, name: str) -> None:
        """Forget a target, if present."""
        with self._lock:
            self._targets.pop(name, None)

    def run_checks(self, check: Check) -> None:
        """Check every target once and record the results."""
        with self._lock:
            todo = [(n, t.gen, t.spec) for n, t in self._targets.items()]
        # ponytail: one target at a time; a slow http_ok delays the round.
        # Use a thread pool if rounds outgrow the interval.
        for name, gen, spec in todo:
            try:
                detail = check(spec["kind"], spec["params"])
            except Exception as err:  # any failure to check is a failing target
                detail = f"{type(err).__name__}: {err}"
            self._apply(name, gen, detail)
        with self._lock:
            self._checked_at = self._clock()

    def _apply(self, name: str, gen: int, detail: str | None) -> None:
        with self._lock:
            target = self._targets.get(name)
            if target is None or target.gen != gen:
                return  # removed or replaced while its check ran
            if detail is None:
                target.since = target.detail = None
                return
            if target.since is None:
                target.since = self._clock()
                target.started = self._monotonic()
            target.detail = detail
            self._settle(target)

    def _settle(self, target: _Target) -> None:
        """Turn a failure that outlasted its tolerance into a fault (lock held)."""
        if target.since is None or target.fault is not None:
            return
        grace_end = target.created + target.spec["graceSeconds"]
        now = self._monotonic()
        if now < grace_end:
            return
        if now - max(target.started, grace_end) >= target.spec["toleratedSeconds"]:
            target.fault = (target.since, target.detail)

    def status(self) -> dict[str, Any]:
        """Return the GET /status document."""
        with self._lock:
            targets: dict[str, Any] = {}
            anomalies: list[dict[str, Any]] = []
            for name, t in self._targets.items():
                self._settle(t)
                kind = t.spec["kind"]
                targets[name] = {
                    "kind": kind,
                    "failing": t.since is not None,
                    "since": iso(t.since),
                    "detail": t.detail,
                }
                anomaly = (t.since, t.detail) if t.since is not None else t.fault
                if anomaly is not None:
                    anomalies.append(
                        {"target": name, "kind": kind,
                         "detail": anomaly[1], "since": iso(anomaly[0])}
                    )  # fmt: skip
            faulted = any(t.fault for t in self._targets.values())
            return {
                "state": "fault" if faulted else "degraded" if anomalies else "healthy",
                "targets": targets,
                "anomalies": anomalies,
                "checkedAt": iso(self._checked_at),
            }
