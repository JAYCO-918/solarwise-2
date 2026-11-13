# Test fixtures

Real answers of a demonstration-mode server, written by `python -m tests.frontend_fixtures` (run from `backend/`).
Do not edit them by hand: `backend/tests/test_frontend_fixtures.py` fails when they no longer match what the server
sends. Daily series are cut to their last 14 entries and run-time timestamps are replaced by a fixed one.

Everything in them is synthetic demonstration data.

The fixtures of the language-model layer (`insight_ai`, `data_review`, `ai_status_on`) are answers of a server whose
model is a **stand-in** on a local socket: it speaks the chat-completions protocol and gives scripted answers. They
show what the interface receives when a model is configured; they are not the writing of a real model.
