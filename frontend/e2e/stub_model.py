#!/usr/bin/env python3
"""A stand-in for a language-model service, for the browser checks.

It listens on a local port and speaks the OpenAI ``/chat/completions`` protocol, so the application is exercised
exactly as it is with a real provider: configuration, request, answer, checks, storage, display.  It is **not** a
language model.  Its answers are scripted: it restates what the request contains, in the structure the request asks
for.  What these checks show is that the path works and that the page says who wrote what - not how a real model
writes.

    POST /v1/chat/completions   answer according to the system prompt of the request
    POST /control               {"mode": "ok" | "fail" | "rogue" | "slow"}: how the next answers behave
    GET  /requests              how many completions were asked for

usage: stub_model.py <port>      (run with the interpreter that has the backend installed)
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from tests.ai.answers import scripted_model

STATE = {"mode": "ok", "requests": 0}

#: What the stand-in suggests for abbreviated headers the deterministic reader cannot place.
ABBREVIATIONS: dict[str, dict[str, Any]] = {
    "Prod": {"role": "QUANTITY", "metric": "actual_energy", "unit": "kWh",
             "reason": "Prod reads as the production of the plant; the values fit its capacity in kWh per day."},
    "Ref": {"role": "QUANTITY", "metric": "expected_energy", "unit": "kWh",
            "reason": "Ref reads as the reference production: it is slightly above Prod on every row."},
    "G_incl": {"role": "QUANTITY", "metric": "poa_irradiation", "unit": "kWh/m2",
               "reason": "G_incl reads as the irradiation in the inclined plane."},
    "T1": {"role": "QUANTITY", "metric": "module_temp", "unit": "degC", "reason": "The warmer of the two temperatures."},
    "T2": {"role": "QUANTITY", "metric": "ambient_temp", "unit": "degC", "reason": "The cooler of the two temperatures."},
    "Rem": {"role": "EVENTS", "reason": "Rem holds remarks such as an inverter trip."},
}
REPHRASED = (
    "The findings of the engine are restated here without any addition. The decision stays the engine's, and nothing "
    "in this text changes it. The explanation above remains the reference for every figure and every reason."
)


def chat(content: str) -> dict[str, Any]:
    return {"id": "stub", "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}


def review(body: dict[str, Any]) -> dict[str, Any]:
    packet = json.loads(body["messages"][1]["content"])
    suggestions = [
        {"column": column["name"], **ABBREVIATIONS[column["name"]]}
        for column in packet["columns"]
        if column["name"] in ABBREVIATIONS and column["proposal"]["role"] == "UNUSED"
    ]
    # One proposal a careless model could make: the server has to discard it.
    suggestions.append({"column": "Energy total", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh",
                        "reason": "A column that is not in the file."})
    # Remarks that are true of the file in front of it: the stand-in reads the statistics it was sent.
    observations = [
        {"column": column["name"],
         "text": f"Every reading is {column['minimum']:g}: an export that repeats one value should be checked at its source."}
        for column in packet["columns"]
        if column["proposal"]["metric"] == "expected_energy" and column["numeric"] > 1 and column["minimum"] == column["maximum"]
    ] or [{"column": None, "text": "The file was read without a remark on its values."}]
    return chat(json.dumps({"suggestions": suggestions, "observations": observations,
                            "missing_context": ["Which of the two temperatures is the module temperature should be confirmed on site."]}))


def rogue(body: dict[str, Any]) -> dict[str, Any]:
    """An answer that overreaches: it states soiling as a fact and names a decision of its own."""
    _, _, payload = scripted_model(body)
    answer = json.loads(payload["choices"][0]["message"]["content"])
    answer["executive_summary"] = (
        "The loss is caused by soiling: the modules are dirty. The recommendation is to clean now, and the crew can "
        "start this week."
    )
    return chat(json.dumps(answer))


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_: Any) -> None:
        pass

    def _send(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/requests":
            self._send(200, {"requests": STATE["requests"], "mode": STATE["mode"]})
        else:
            self._send(200, {"status": "ok"})

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("content-length", "0")))
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = {}
        if self.path == "/control":
            STATE["mode"] = str(body.get("mode", "ok"))
            self._send(200, {"mode": STATE["mode"]})
            return
        if not self.path.endswith("/chat/completions"):
            self._send(404, {"error": "unknown path"})
            return
        STATE["requests"] += 1
        if STATE["mode"] == "fail":
            self._send(503, {"error": "the stand-in was told to be unavailable"})
            return
        if STATE["mode"] == "slow":
            time.sleep(3.0)
        system = str(body.get("messages", [{}])[0].get("content", ""))
        if system.startswith("You are the diagnostic analyst"):
            if STATE["mode"] == "rogue":
                self._send(200, rogue(body))
            else:
                self._send(*scripted_model(body)[::2])
        elif system.startswith("You help the operator"):
            self._send(200, review(body))
        else:
            self._send(200, chat(REPHRASED))


if __name__ == "__main__":
    port = int(sys.argv[1])
    print(f"stand-in model on http://127.0.0.1:{port}/v1 (scripted answers; not a language model)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
