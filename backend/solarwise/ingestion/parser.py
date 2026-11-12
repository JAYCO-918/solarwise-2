"""Reading uploaded files into raw rows.

Only the *shape* of the file is handled here (encoding, delimiter, JSON
envelope, size limits).  Meaning - timestamps, units, ranges - is the
validator's job.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any

#: Hard limits protecting the service from oversized uploads.
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ROWS = 400_000
MAX_COLUMNS = 200


class ParseError(ValueError):
    """The file cannot be read as a table at all."""


@dataclass
class RawTable:
    columns: list[str]
    #: One mapping per data row: column name -> raw cell (string for CSV, any JSON scalar for JSON).
    rows: list[dict[str, Any]]
    #: Decimal comma detected (semicolon-delimited CSV).
    decimal_comma: bool = False
    #: Metadata embedded in a JSON upload, if any.
    embedded_metadata: dict[str, Any] | None = None
    file_format: str = "CSV"


def _decode(data: bytes) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise ParseError(f"the file exceeds the {MAX_FILE_BYTES // (1024 * 1024)} MB limit")
    if not data.strip():
        raise ParseError("the file is empty")
    if b"\x00" in data[:4096]:
        raise ParseError("the file looks binary; upload CSV or JSON text")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError as exc:  # pragma: no cover - cp1252 decodes nearly anything
            raise ParseError("the file is not valid UTF-8 text") from exc


def parse_csv(data: bytes) -> RawTable:
    """Parse delimited text.  Delimiter (comma, semicolon, tab) is detected from the header."""
    text = _decode(data)
    first_line = text.split("\n", 1)[0]
    counts = {d: first_line.count(d) for d in (",", ";", "\t")}
    delimiter = max(counts, key=lambda d: counts[d])
    if counts[delimiter] == 0:
        raise ParseError("no delimiter found in the header line: expected comma, semicolon or tab separated columns")
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration as exc:  # pragma: no cover - guarded by the emptiness check
        raise ParseError("the file is empty") from exc
    columns = [c.strip() for c in header]
    if len(columns) > MAX_COLUMNS:
        raise ParseError(f"more than {MAX_COLUMNS} columns")
    if any(not c for c in columns):
        raise ParseError("the header contains an empty column name")
    if len(set(columns)) != len(columns):
        duplicated = sorted({c for c in columns if columns.count(c) > 1})
        raise ParseError(f"duplicate column name(s) in the header: {', '.join(duplicated)}")
    rows: list[dict[str, Any]] = []
    for line_number, cells in enumerate(reader, start=2):
        if not cells or all(not c.strip() for c in cells):
            continue
        if len(cells) != len(columns):
            raise ParseError(f"line {line_number}: {len(cells)} cells, but the header has {len(columns)} columns")
        if len(rows) >= MAX_ROWS:
            raise ParseError(f"more than {MAX_ROWS:,} data rows; split the file")
        rows.append(dict(zip(columns, (c.strip() for c in cells), strict=True)))
    if not rows:
        raise ParseError("the file has a header but no data rows")
    return RawTable(columns=columns, rows=rows, decimal_comma=(delimiter == ";"), file_format="CSV")


def parse_json(data: bytes) -> RawTable:
    """Parse a JSON upload: ``{"metadata": {...}, "records": [{...}, ...]}`` or a bare list of records."""
    text = _decode(data)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ParseError(f"invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})") from exc
    metadata: dict[str, Any] | None = None
    if isinstance(payload, dict):
        records = payload.get("records")
        raw_meta = payload.get("metadata")
        if raw_meta is not None and not isinstance(raw_meta, dict):
            raise ParseError("'metadata' must be an object")
        metadata = raw_meta
    else:
        records = payload
    if not isinstance(records, list) or not records:
        raise ParseError("expected a non-empty list of records (top-level list, or under the key 'records')")
    if len(records) > MAX_ROWS:
        raise ParseError(f"more than {MAX_ROWS:,} records; split the file")
    columns: list[str] = []
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ParseError(f"record {index} is not an object")
        for key, value in record.items():
            if isinstance(value, dict | list):
                raise ParseError(f"record {index}: value of '{key}' must be a scalar")
            if key not in seen:
                seen.add(key)
                columns.append(key)
        rows.append(record)
    if len(columns) > MAX_COLUMNS:
        raise ParseError(f"more than {MAX_COLUMNS} distinct keys")
    return RawTable(columns=columns, rows=rows, embedded_metadata=metadata, file_format="JSON")


def parse_upload(data: bytes, filename: str | None, content_type: str | None = None) -> RawTable:
    """Dispatch on the file extension (falling back to the content)."""
    name = (filename or "").lower()
    if name.endswith(".json") or (content_type or "").startswith("application/json"):
        return parse_json(data)
    if name.endswith((".csv", ".txt", ".tsv")) or not name:
        return parse_csv(data)
    stripped = data.lstrip()[:1]
    if stripped in (b"{", b"["):
        return parse_json(data)
    raise ParseError("unsupported file type: upload a .csv or .json file")
