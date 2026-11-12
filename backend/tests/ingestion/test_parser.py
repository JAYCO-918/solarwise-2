"""Reading CSV and JSON uploads into raw rows."""

from __future__ import annotations

import json

import pytest

from solarwise.ingestion.parser import MAX_FILE_BYTES, ParseError, parse_csv, parse_json, parse_upload


def test_comma_separated_csv() -> None:
    table = parse_csv(b"timestamp,actual_energy_kwh\n2026-05-01,1000.5\n2026-05-02,990\n")
    assert table.columns == ["timestamp", "actual_energy_kwh"]
    assert table.rows[0] == {"timestamp": "2026-05-01", "actual_energy_kwh": "1000.5"}
    assert len(table.rows) == 2
    assert not table.decimal_comma
    assert table.file_format == "CSV"


def test_semicolon_csv_uses_decimal_comma() -> None:
    table = parse_csv(b"timestamp;actual_energy_kwh\n01/05/2026;1000,5\n")
    assert table.decimal_comma
    assert table.rows[0]["actual_energy_kwh"] == "1000,5"


def test_tab_separated_csv() -> None:
    table = parse_csv(b"timestamp\tactual_energy_kwh\n2026-05-01\t12\n")
    assert table.columns == ["timestamp", "actual_energy_kwh"]


def test_byte_order_mark_and_blank_lines_are_ignored() -> None:
    table = parse_csv("\ufefftimestamp,actual_energy_kwh\n\n2026-05-01,12\n\n".encode())
    assert table.columns[0] == "timestamp"
    assert len(table.rows) == 1


def test_quoted_cells() -> None:
    table = parse_csv(b'timestamp,note\n2026-05-01,"dust, then rain"\n')
    assert table.rows[0]["note"] == "dust, then rain"


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"   \n  ", "empty"),
        (b"PK\x03\x04\x00\x00binary", "binary"),
        (b"timestamp\n2026-05-01\n", "no delimiter"),
        (b"timestamp,energy,energy\n2026-05-01,1,2\n", "duplicate column"),
        (b"timestamp,,energy\n2026-05-01,1,2\n", "empty column name"),
        (b"timestamp,energy\n2026-05-01,1,2\n", "line 2: 3 cells"),
        (b"timestamp,energy\n", "no data rows"),
    ],
)
def test_malformed_csv_is_refused(data: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_csv(data)


def test_oversized_file_is_refused() -> None:
    with pytest.raises(ParseError, match="MB limit"):
        parse_csv(b"a,b\n" + b"1,2\n" * (MAX_FILE_BYTES // 4 + 1))


def test_json_with_metadata_envelope() -> None:
    payload = {"metadata": {"name": "x"}, "records": [{"timestamp": "2026-05-01", "actual_energy_kwh": 12.5}]}
    table = parse_json(json.dumps(payload).encode())
    assert table.embedded_metadata == {"name": "x"}
    assert table.rows[0]["actual_energy_kwh"] == 12.5
    assert table.file_format == "JSON"


def test_json_bare_list_and_union_of_keys() -> None:
    table = parse_json(b'[{"timestamp": "2026-05-01", "a": 1}, {"timestamp": "2026-05-02", "b": null}]')
    assert table.columns == ["timestamp", "a", "b"]
    assert table.embedded_metadata is None


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"{not json", "invalid JSON"),
        (b"{}", "non-empty list"),
        (b"[]", "non-empty list"),
        (b'{"records": [1, 2]}', "not an object"),
        (b'{"records": [{"a": {"nested": 1}}]}', "must be a scalar"),
        (b'{"metadata": 5, "records": [{"a": 1}]}', "'metadata' must be an object"),
    ],
)
def test_malformed_json_is_refused(data: bytes, message: str) -> None:
    with pytest.raises(ParseError, match=message):
        parse_json(data)


def test_dispatch_on_file_name_and_content() -> None:
    csv_bytes = b"timestamp,actual_energy_kwh\n2026-05-01,12\n"
    json_bytes = b'[{"timestamp": "2026-05-01", "actual_energy_kwh": 12}]'
    assert parse_upload(csv_bytes, "data.csv").file_format == "CSV"
    assert parse_upload(json_bytes, "data.json").file_format == "JSON"
    assert parse_upload(json_bytes, "upload", "application/json").file_format == "JSON"
    assert parse_upload(json_bytes, "data.bin").file_format == "JSON"  # recognised from the content
    assert parse_upload(csv_bytes, None).file_format == "CSV"


def test_unsupported_file_type_is_refused() -> None:
    with pytest.raises(ParseError, match="unsupported"):
        parse_upload(b"timestamp,actual_energy_kwh\n2026-05-01,12\n", "data.xlsx")
