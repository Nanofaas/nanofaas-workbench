"""Run the supervisor: `python -m workbench_supervisor --prometheus URL`."""

import argparse
import json
import signal
import sys
import threading
import urllib.parse

from workbench_supervisor.checks import Checker, validate
from workbench_supervisor.server import make_server
from workbench_supervisor.state import State


def main(argv: list[str] | None = None) -> None:
    """Serve the API and check every target each interval until SIGTERM."""
    parser = argparse.ArgumentParser(prog="workbench_supervisor")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--prometheus", required=True)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--targets", default="{}", help="JSON {name: target}")
    args = parser.parse_args(argv)
    if urllib.parse.urlsplit(args.prometheus).scheme not in ("http", "https"):
        parser.error("--prometheus must be an http(s) URL")
    if args.interval <= 0:
        parser.error("--interval must be positive")
    state = State()
    try:
        targets = json.loads(args.targets)
        if not isinstance(targets, dict):
            raise ValueError("--targets is a JSON object")
        for name, spec in targets.items():
            state.put(name, validate(spec))
    except ValueError as err:
        parser.error(f"--targets: {err}")

    checker = Checker(args.prometheus, args.interval)
    stop = threading.Event()

    def rounds() -> None:
        while True:
            state.run_checks(checker)
            if stop.wait(args.interval):
                return

    server = make_server(state, args.bind, args.port)
    # PID 1 in a container ignores SIGTERM without a handler.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    threading.Thread(target=rounds, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        stop.set()
        server.server_close()


if __name__ == "__main__":
    main()
