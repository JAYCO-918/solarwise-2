"""A stand-in for a language-model service, on a real local socket.

It speaks the OpenAI ``/chat/completions`` protocol over HTTP, so the provider
code is exercised through an actual connection - headers, status codes,
timeouts, retries.  It is not a language model: every answer is scripted by the
test.  Nothing in this suite contacts a real provider.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

#: (status, headers, body) or a callable building one from the request body.
Scripted = tuple[int, dict[str, str], Any]


def chat(content: str) -> Scripted:
    """A normal chat-completions answer whose assistant message is ``content``."""
    return 200, {}, {"id": "stub-1", "object": "chat.completion",
                     "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}


@dataclass
class StubProvider:
    base_url: str
    #: One entry per request received: path, headers (lower-cased names) and the JSON body.
    requests: list[dict[str, Any]] = field(default_factory=list)
    #: Answers still to be served, first in first out; the last one is repeated.
    script: list[Scripted | Callable[[dict[str, Any]], Scripted]] = field(default_factory=list)
    #: Seconds to wait before answering (to provoke a client timeout).
    delay: float = 0.0

    def answer(self, *responses: Scripted | Callable[[dict[str, Any]], Scripted]) -> None:
        self.script = list(responses)

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [r["body"] for r in self.requests]


@contextmanager
def serve() -> Iterator[StubProvider]:
    state = StubProvider(base_url="")

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: Any) -> None:  # silence the default stderr log
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            raw = self.rfile.read(length)
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
            state.requests.append(
                {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
            )
            if state.delay:
                time.sleep(state.delay)
            if not state.script:
                scripted: Scripted = (500, {}, {"error": "the test scripted no answer"})
            else:
                entry = state.script[0] if len(state.script) == 1 else state.script.pop(0)
                scripted = entry(body) if callable(entry) else entry
            status, headers, payload = scripted
            data = payload if isinstance(payload, bytes) else (
                payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
            )
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):  # the client gave up (time limit)
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state.base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
