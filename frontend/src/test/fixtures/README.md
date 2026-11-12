# Test fixtures

Real answers of a demonstration-mode server, written by `python -m tests.frontend_fixtures` (run from `backend/`).
Do not edit them by hand: `backend/tests/test_frontend_fixtures.py` fails when they no longer match what the server
sends. Daily series are cut to their last 14 entries and run-time timestamps are replaced by a fixed one.

Everything in them is synthetic demonstration data.
