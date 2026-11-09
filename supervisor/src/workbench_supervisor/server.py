"""The HTTP API: PUT/DELETE /targets/<name>, GET /status and /metrics."""

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from workbench_supervisor.checks import validate
from workbench_supervisor.state import State

NAME = re.compile(r"[A-Za-z0-9_.-]{1,128}\Z")
TARGET = re.compile(r"/targets/([^/]*)\Z")
MAX_BODY = 64 * 1024
STATES = ("healthy", "degraded", "fault")


def metrics(status: dict[str, Any]) -> str:
    """Render the status as Prometheus text exposition."""
    # Target names and kinds are validated: no label value needs escaping.
    lines = [
        "# HELP workbench_supervisor_state 1 for the current overall state.",
        "# TYPE workbench_supervisor_state gauge",
        *(
            f'workbench_supervisor_state{{state="{s}"}} {int(s == status["state"])}'
            for s in STATES
        ),
        "# HELP workbench_supervisor_target_failing 1 while the target's check fails.",
        "# TYPE workbench_supervisor_target_failing gauge",
        *(
            f'workbench_supervisor_target_failing{{target="{name}",kind="{t["kind"]}"}}'
            f" {int(t['failing'])}"
            for name, t in status["targets"].items()
        ),
    ]
    return "\n".join(lines) + "\n"


def make_server(state: State, bind: str, port: int) -> ThreadingHTTPServer:
    """Return a server (not yet serving) for `state` on bind:port."""

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: str = "", ctype: str = "") -> None:
            data = body.encode()
            self.send_response(code)
            if ctype:
                self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _name(self) -> str | None:
            match = TARGET.match(self.path)
            return match.group(1) if match and NAME.match(match.group(1)) else None

        def do_GET(self) -> None:
            if self.path == "/status":
                self._send(200, json.dumps(state.status()), "application/json")
            elif self.path == "/metrics":
                self._send(200, metrics(state.status()), "text/plain; version=0.0.4")
            else:
                self._send(404)

        def do_PUT(self) -> None:
            name = self._name()
            if name is None:
                self._send(404)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                # The body is not read: drop the connection after answering.
                self.close_connection = True
                self._send(413 if length > MAX_BODY else 400)
                return
            try:
                spec = validate(json.loads(self.rfile.read(length)))
            # JSONDecodeError is a ValueError; deep nesting is a RecursionError.
            except (ValueError, RecursionError) as err:
                self._send(400, f"{err}\n", "text/plain")
                return
            state.put(name, spec)
            self._send(204)

        def do_DELETE(self) -> None:
            name = self._name()
            if name is None:
                self._send(404)
                return
            state.remove(name)
            self._send(204)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # GET /status every few seconds would flood the log

    return ThreadingHTTPServer((bind, port), Handler)
