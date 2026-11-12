"""A reverse proxy that does to the ``Authorization`` header what some gateways do: removes it, or replaces it.

usage: header_proxy.py <listen port> <upstream port> strip|replace
"""

import http.client
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT, UPSTREAM_PORT, MODE = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() != "authorization"}
        if MODE == "replace":
            headers["Authorization"] = "Bearer credential-of-the-gateway"
        upstream = http.client.HTTPConnection("127.0.0.1", UPSTREAM_PORT, timeout=60)
        upstream.request(self.command, self.path, body=body, headers=headers)
        response = upstream.getresponse()
        data = response.read()
        upstream.close()
        try:
            self.send_response(response.status)
            for key, value in response.getheaders():
                if key.lower() not in HOP and key.lower() != "content-length":
                    self.send_header(key, value)
            self.send_header("Content-Length", response.getheader("Content-Length") if self.command == "HEAD" else str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # The browser left the page before the answer arrived: nothing to deliver.
            self.close_connection = True

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _forward

    def log_message(self, *args: object) -> None:
        pass


if MODE not in {"strip", "replace"}:
    sys.exit("mode must be strip or replace")
ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
