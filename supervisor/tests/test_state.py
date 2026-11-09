from workbench_supervisor.state import State

SPEC = {"kind": "http_ok", "params": {"url": "http://x/"}, "toleratedSeconds": 10}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def failing(detail: str = "down"):
    return lambda kind, params: detail


def passing(kind, params):
    return None


def test_new_target_is_healthy():
    state = State(Clock(), Clock())
    state.put("t", SPEC)
    status = state.status()
    assert status["state"] == "healthy"
    assert status["targets"]["t"] == {
        "kind": "http_ok", "failing": False, "since": None, "detail": None,
    }  # fmt: skip
    assert status["anomalies"] == []
    assert status["checkedAt"] is None


def test_tolerance_degrades_then_faults():
    clock = Clock()
    state = State(clock, clock)
    state.put("t", SPEC)
    state.run_checks(failing())
    clock.now += 3
    state.run_checks(failing())
    status = state.status()
    assert status["state"] == "degraded"
    assert status["targets"]["t"]["failing"] is True
    assert status["targets"]["t"]["detail"] == "down"
    assert status["anomalies"][0]["target"] == "t"
    assert status["anomalies"][0]["kind"] == "http_ok"
    assert status["checkedAt"] is not None
    clock.now += 8
    state.run_checks(failing())
    assert state.status()["state"] == "fault"


def test_tolerance_is_measured_at_status_time_too():
    clock = Clock()
    state = State(clock, clock)
    state.put("t", SPEC)
    state.run_checks(failing())
    clock.now += 11
    assert state.status()["state"] == "fault"


def test_zero_tolerance_faults_at_once():
    state = State(Clock(), Clock())
    state.put("t", {**SPEC, "toleratedSeconds": 0})
    state.run_checks(failing())
    assert state.status()["state"] == "fault"


def test_recovery_within_tolerance_is_healthy():
    clock = Clock()
    state = State(clock, clock)
    state.put("t", SPEC)
    state.run_checks(failing())
    clock.now += 5
    state.run_checks(passing)
    clock.now += 20
    assert state.status()["state"] == "healthy"


def test_fault_is_sticky_until_removed():
    clock = Clock()
    state = State(clock, clock)
    state.put("t", SPEC)
    state.run_checks(failing("boom"))
    clock.now += 11
    state.run_checks(failing("boom"))
    state.run_checks(passing)
    status = state.status()
    assert status["state"] == "fault"
    assert status["targets"]["t"]["failing"] is False
    # The fault stays listed with what caused it.
    assert status["anomalies"] == [
        {"target": "t", "kind": "http_ok", "detail": "boom",
         "since": status["anomalies"][0]["since"]},
    ]  # fmt: skip
    assert status["anomalies"][0]["since"] is not None
    # Re-putting the same spec (a client retry) keeps the fault.
    state.put("t", SPEC)
    assert state.status()["state"] == "fault"
    state.remove("t")
    state.put("t", SPEC)
    assert state.status()["state"] == "healthy"


def test_changed_spec_starts_over():
    clock = Clock()
    state = State(clock, clock)
    state.put("t", {**SPEC, "toleratedSeconds": 0})
    state.run_checks(failing())
    assert state.status()["state"] == "fault"
    state.put("t", SPEC)
    assert state.status()["state"] == "healthy"


def test_check_exception_marks_failing():
    def broken(kind, params):
        raise OSError("refused")

    state = State(Clock(), Clock())
    state.put("t", SPEC)
    state.run_checks(broken)
    target = state.status()["targets"]["t"]
    assert target["failing"] is True
    assert target["detail"] == "OSError: refused"


def test_remove_absent_is_fine():
    State(Clock(), Clock()).remove("nope")


def test_wall_clock_steps_do_not_change_tolerance():
    wall, mono = Clock(), Clock()
    state = State(wall, mono)
    state.put("t", SPEC)
    state.run_checks(failing())
    wall.now += 3600  # e.g. chronyc makestep
    mono.now += 3
    state.run_checks(failing())
    status = state.status()
    assert status["state"] == "degraded"
    assert status["targets"]["t"]["since"] == "1970-01-01T00:16:40.000+00:00"
    wall.now -= 7200
    mono.now += 8
    assert state.status()["state"] == "fault"
