"""A stub Prometheus answering /api/v1/query from canned results."""

import json
import threading
import urllib.parse
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class StubProm:
    def __init__(self) -> None:
        self.results: dict[str, list[float]] = {}
        self.queries: list[str] = []
        self.status = "success"
        self.url = ""

    def vector(self, query: str) -> list[dict]:
        return [
            {"metric": {}, "value": [0, str(v)]} for v in self.results.get(query, [])
        ]


@pytest.fixture
def prom() -> Iterator[StubProm]:
    stub = StubProm()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            url = urllib.parse.urlsplit(self.path)
            if url.path != "/api/v1/query":
                self.send_error(404)
                return
            query = urllib.parse.parse_qs(url.query)["query"][0]
            stub.queries.append(query)
            body = {"status": stub.status, "data": {"resultType": "vector"}}
            body["data"]["result"] = stub.vector(query)
            if stub.status != "success":
                body["error"] = "bad query"
            data = json.dumps(body).encode()
            self.send_response(200 if stub.status == "success" else 400)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    stub.url = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield stub
    server.shutdown()
    server.server_close()
