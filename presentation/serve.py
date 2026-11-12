#!/usr/bin/env python3
"""Shows the pitch deck in a browser, straight from the files of this folder.

    python3 presentation/serve.py            # then open http://localhost:8012/
    python3 presentation/serve.py 9000       # another port

    /                           the slides (arrow keys or click to move, N for the script, T for the clock)
    /SolarWise-DZ-pitch.pptx    the PowerPoint file
    /SolarWise-DZ-pitch.pdf     the PDF
    /SolarWise-DZ-pitch.html    the slides as one file; add ?download to save it instead of opening it
    /SPEAKER-SCRIPT.md          what to say

Standard library only: no installation.  The files are read at each request and the browser is told to ask again
every time, so after a rebuild a reload shows the new slides.  Nothing else of the folder is served.
"""

from __future__ import annotations

import sys
from email.utils import formatdate
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
DECK = "SolarWise-DZ-pitch.html"
FILES = {
    DECK: "text/html; charset=utf-8",
    "SolarWise-DZ-pitch.pdf": "application/pdf",
    "SolarWise-DZ-pitch.pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "SPEAKER-SCRIPT.md": "text/markdown; charset=utf-8",
}
DEFAULT_PORT = 8012


class Handler(BaseHTTPRequestHandler):
    server_version = "SolarWisePitch"
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._answer(with_body=True)

    def do_HEAD(self) -> None:
        self._answer(with_body=False)

    def _answer(self, *, with_body: bool) -> None:
        url = urlsplit(self.path)
        name = DECK if url.path in ("/", "/index.html") else url.path.lstrip("/")
        path = HERE / name
        if name not in FILES or not path.is_file():
            missing = name in FILES
            text = (
                (f"{name} has not been built yet: see README.md in the presentation folder.\n" if missing else "Nothing here.\n")
                + "\nAvailable:\n  /  (the slides)\n"
                + "".join(f"  /{known}\n" for known in FILES if (HERE / known).is_file())
            )
            self._send(HTTPStatus.NOT_FOUND, text.encode(), {"Content-Type": "text/plain; charset=utf-8"}, with_body)
            return

        stat = path.stat()
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
        headers = {
            "Content-Type": FILES[name],
            "ETag": etag,
            "Last-Modified": formatdate(stat.st_mtime, usegmt=True),
            # Always ask the server again: a rebuilt deck must never be hidden by a stored copy.
            "Cache-Control": "no-cache",
        }
        if "download" in parse_qs(url.query, keep_blank_values=True):
            headers["Content-Disposition"] = f'attachment; filename="{name}"'
        if self.headers.get("If-None-Match") == etag:
            self._send(HTTPStatus.NOT_MODIFIED, b"", headers, with_body=False)
            return
        self._send(HTTPStatus.OK, path.read_bytes(), headers, with_body)

    def _send(self, status: HTTPStatus, data: bytes, headers: dict[str, str], with_body: bool) -> None:
        try:
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            if status != HTTPStatus.NOT_MODIFIED:
                self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            # One request per connection: nothing to go wrong with connections that a proxy keeps open.
            self.send_header("Connection", "close")
            self.end_headers()
            if with_body and status != HTTPStatus.NOT_MODIFIED:
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # The browser went away before the answer arrived.
            self.close_connection = True


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    if not (HERE / DECK).is_file():
        print(f"{DECK} is missing from {HERE}: build it first (see README.md).", file=sys.stderr)
        return 1
    ThreadingHTTPServer.daemon_threads = True
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"pitch deck on http://localhost:{port}/ (every network interface); Ctrl+C to stop", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
