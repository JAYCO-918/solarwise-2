"""Validation of uploads: reject what is wrong, flag what is doubtful, assume nothing."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from solarwise.core.models import DeviceSpec, Metric, SoilingMethod
from solarwise.core.provenance import Provenance
from solarwise.ingestion.parser import RawTable, parse_csv
from solarwise.ingestion.schema import ChannelDeclaration, DatasetMetadata, SyntheticDeclaration
from solarwise.ingestion.validator import (
    IssueSeverity,
    ParsedDataset,
    ValidationReport,
    parse_number,
    parse_timestamp,
    validate_table,
)
from tests.builders import PLANT

NOW = datetime(2026, 7, 1, tzinfo=UTC)
ALGIERS = ZoneInfo("Africa/Algiers")
PARIS = ZoneInfo("Europe/Paris")


def measured_channels(**extra: ChannelDeclaration) -> dict[Metric, ChannelDeclaration]:
    channels = {
        Metric.ACTUAL_ENERGY: ChannelDeclaration(provenance=Provenance.MEASURED, source="revenue meter"),
        Metric.EXPECTED_ENERGY: ChannelDeclaration(provenance=Provenance.MODELLED, source="performance model"),
    }
    channels.update({Metric(k): v for k, v in extra.items()})
    return channels


def validate(
    text: str, metadata: DatasetMetadata | None = None, **kwargs: object
) -> tuple[ValidationReport, ParsedDataset | None]:
    table = parse_csv(text.encode())
    meta = metadata or DatasetMetadata(name="test", channels=measured_channels())
    return validate_table(table, meta, plant=PLANT, now=NOW, **kwargs)  # type: ignore[arg-type]


def codes(report: ValidationReport, severity: IssueSeverity | None = None) -> set[str]:
    return {i.code for i in report.issues if severity is None or i.severity is severity}


def daily(rows: list[str], header: str = "timestamp,actual_energy_kwh,expected_energy_kwh") -> str:
    return header + "\n" + "\n".join(rows) + "\n"


GOOD = daily([f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)])


# --------------------------------------------------------------------------- the happy path


def test_valid_file_is_accepted() -> None:
    report, parsed = validate(GOOD)
    assert report.accepted
    assert parsed is not None
    assert report.rows_plant == 10 and report.rows_rejected == 0 and report.values_rejected == 0
    assert report.interval_minutes == 1440
    assert report.timezone == "Africa/Algiers"
    assert str(report.first_local_day) == "2026-05-01" and str(report.last_local_day) == "2026-05-10"
    assert not codes(report, IssueSeverity.BLOCKING) and not codes(report, IssueSeverity.ERROR)
    first = parsed.observations[0]
    assert first.actual_energy_kwh == 46001.0
    # Local midnight in Algiers (UTC+1) is 23:00 UTC on the previous day.
    assert first.start_utc == datetime(2026, 4, 30, 23, 0, tzinfo=UTC)
    assert parsed.channels[Metric.ACTUAL_ENERGY].tag.label == "MEASURED"


def test_units_are_converted_to_canonical_units() -> None:
    meta = DatasetMetadata(
        name="mwh",
        channels={
            Metric.ACTUAL_ENERGY: ChannelDeclaration(column="energy", unit="MWh", provenance=Provenance.MEASURED),
            Metric.AMBIENT_TEMP: ChannelDeclaration(column="temp", unit="K", provenance=Provenance.MEASURED),
            Metric.RELATIVE_HUMIDITY: ChannelDeclaration(column="rh", unit="fraction", provenance=Provenance.MEASURED),
            Metric.GHI: ChannelDeclaration(column="ghi", unit="MJ/m2", provenance=Provenance.MEASURED),
        },
    )
    text = "timestamp,energy,temp,rh,ghi\n2026-05-01,46.5,300.15,0.25,25.2\n2026-05-02,47.0,301.15,0.30,28.8\n"
    report, parsed = validate(text, meta)
    assert report.accepted and parsed is not None
    obs = parsed.observations[0]
    assert obs.actual_energy_kwh == pytest.approx(46_500.0)
    assert obs.ambient_temp_c == pytest.approx(27.0)
    assert obs.relative_humidity_pct == pytest.approx(25.0)
    assert obs.ghi_kwh_m2 == pytest.approx(7.0)
    summary = next(c for c in report.channels if c.metric is Metric.ACTUAL_ENERGY)
    assert (summary.unit_in, summary.unit, summary.source_column) == ("MWh", "kWh", "energy")
    assert parsed.channels[Metric.ACTUAL_ENERGY].original_unit == "MWh"


def test_hourly_interval_is_inferred() -> None:
    rows = [f"2026-05-01T{h:02d}:00:00+01:00,{1000 + h},1100" for h in range(6, 18)]
    report, parsed = validate(daily(rows))
    assert report.accepted and parsed is not None
    assert parsed.interval_minutes == 60


def test_semicolon_file_with_decimal_commas_and_day_first_dates() -> None:
    text = "timestamp;actual_energy_kwh;expected_energy_kwh\n01/05/2026;46000,5;50000\n02/05/2026;46100,25;50000\n"
    report, parsed = validate(text)
    assert report.accepted and parsed is not None
    assert parsed.observations[0].actual_energy_kwh == pytest.approx(46000.5)
    assert str(report.first_local_day) == "2026-05-01"


# --------------------------------------------------------------------------- structure


def test_missing_timestamp_column_blocks() -> None:
    report, parsed = validate("date,actual_energy_kwh\n2026-05-01,1\n2026-05-02,1\n")
    assert not report.accepted and parsed is None
    assert codes(report, IssueSeverity.BLOCKING) == {"NO_TIMESTAMP_COLUMN"}
    assert "Import refused" in report.summary


def test_timestamp_column_can_be_mapped() -> None:
    meta = DatasetMetadata(name="t", timestamp_column="date", channels=measured_channels())
    report, _ = validate("date,actual_energy_kwh\n2026-05-01,1\n2026-05-02,1\n", meta)
    assert report.accepted


def test_no_recognised_data_column_blocks() -> None:
    report, _ = validate("timestamp,foo\n2026-05-01,1\n2026-05-02,1\n", DatasetMetadata(name="t"))
    assert codes(report, IssueSeverity.BLOCKING) == {"NO_DATA_COLUMNS"}
    assert "UNMAPPED_COLUMN" in codes(report, IssueSeverity.INFO)


def test_declared_column_that_is_absent_is_an_error() -> None:
    meta = DatasetMetadata(
        name="t", channels=measured_channels(soiling_ratio=ChannelDeclaration(provenance=Provenance.MEASURED))
    )
    report, _ = validate(GOOD, meta)
    assert report.accepted
    assert "DECLARED_COLUMN_MISSING" in codes(report, IssueSeverity.ERROR)


def test_unknown_time_zone_blocks() -> None:
    report, _ = validate(GOOD, DatasetMetadata(name="t", timezone="Mars/Olympus", channels=measured_channels()))
    assert codes(report, IssueSeverity.BLOCKING) == {"UNKNOWN_TIMEZONE"}


# --------------------------------------------------------------------------- units


def test_unknown_unit_blocks() -> None:
    channels = measured_channels()
    channels[Metric.ACTUAL_ENERGY] = ChannelDeclaration(unit="horsepower-hours", provenance=Provenance.MEASURED)
    report, parsed = validate(GOOD, DatasetMetadata(name="t", channels=channels))
    assert not report.accepted and parsed is None
    assert "INVALID_UNIT" in codes(report, IssueSeverity.BLOCKING)


def test_power_unit_for_an_energy_channel_blocks() -> None:
    """kW is not kWh: converting would silently produce wrong energy."""
    channels = measured_channels()
    channels[Metric.ACTUAL_ENERGY] = ChannelDeclaration(unit="kW", provenance=Provenance.MEASURED)
    report, _ = validate(GOOD, DatasetMetadata(name="t", channels=channels))
    issue = next(i for i in report.issues if i.code == "INVALID_UNIT")
    assert issue.severity is IssueSeverity.BLOCKING
    assert "unit of power" in issue.message and "energy" in issue.message


def test_energy_inconsistent_with_capacity_blocks() -> None:
    """Wh uploaded as kWh: a 10 MWp plant cannot produce 46 GWh in a day."""
    text = daily([f"2026-05-{d:02d},{46_000_000 + d},{50_000_000}" for d in range(1, 11)])
    report, parsed = validate(text)
    assert not report.accepted and parsed is None
    issue = next(i for i in report.issues if i.code == "ENERGY_EXCEEDS_CAPACITY")
    assert issue.severity is IssueSeverity.BLOCKING
    assert "unit or the plant capacity is inconsistent" in issue.message


def test_isolated_value_beyond_capacity_is_flagged_not_dropped() -> None:
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)]
    rows[4] = "2026-05-05,9000000,50000"
    report, parsed = validate(daily(rows))
    assert report.accepted and parsed is not None
    issue = next(i for i in report.issues if i.code == "ENERGY_EXCEEDS_CAPACITY")
    assert issue.severity is IssueSeverity.ERROR
    assert parsed.observations[4].actual_energy_kwh == 9_000_000.0


def test_capacity_declared_in_the_file_must_match_the_plant() -> None:
    meta = DatasetMetadata(name="t", capacity_dc_kwp=50_000.0, channels=measured_channels())
    report, _ = validate(GOOD, meta)
    assert codes(report, IssueSeverity.BLOCKING) == {"CAPACITY_MISMATCH"}


# --------------------------------------------------------------------------- values


def test_negative_energy_is_rejected_and_stays_missing() -> None:
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)]
    rows[2] = "2026-05-03,-250,50000"
    report, parsed = validate(daily(rows))
    assert report.accepted and parsed is not None
    assert "NEGATIVE_VALUE" in codes(report, IssueSeverity.ERROR)
    assert report.values_rejected == 1
    assert parsed.observations[2].actual_energy_kwh is None  # missing, not zero
    assert parsed.observations[2].expected_energy_kwh == 50000.0


def test_text_in_a_numeric_column_is_rejected() -> None:
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)]
    rows[0] = "2026-05-01,offline,50000"
    report, parsed = validate(daily(rows))
    assert parsed is not None
    assert "NON_NUMERIC" in codes(report, IssueSeverity.ERROR)
    assert parsed.observations[0].actual_energy_kwh is None


@pytest.mark.parametrize("token", ["", "NA", "n/a", "NaN", "null", "-"])
def test_missing_value_tokens_are_missing_not_errors(token: str) -> None:
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)]
    rows[5] = f"2026-05-06,{token},50000"
    report, parsed = validate(daily(rows))
    assert parsed is not None
    assert report.values_rejected == 0
    assert parsed.observations[5].actual_energy_kwh is None
    summary = next(c for c in report.channels if c.metric is Metric.ACTUAL_ENERGY)
    assert summary.missing == 1 and summary.values == 9


def test_infinite_values_are_rejected() -> None:
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)]
    rows[1] = "2026-05-02,inf,50000"
    report, parsed = validate(daily(rows))
    assert parsed is not None
    assert "NON_FINITE" in codes(report, IssueSeverity.ERROR)
    assert parsed.observations[1].actual_energy_kwh is None


def test_out_of_range_sensor_values_are_rejected() -> None:
    header = "timestamp,actual_energy_kwh,ambient_temp_c,soiling_ratio,availability_fraction"
    rows = [f"2026-05-{d:02d},46000,30,0.95,0.99" for d in range(1, 11)]
    rows[0] = "2026-05-01,46000,140,1.6,1.4"
    report, parsed = validate(daily(rows, header), DatasetMetadata(name="t"))
    assert parsed is not None
    assert report.values_rejected == 3
    first = parsed.observations[0]
    assert first.ambient_temp_c is None and first.soiling_ratio is None and first.availability_fraction is None


def test_percent_values_are_converted_to_fractions() -> None:
    meta = DatasetMetadata(
        name="t",
        channels={
            Metric.ACTUAL_ENERGY: ChannelDeclaration(provenance=Provenance.MEASURED),
            Metric.SOILING_RATIO: ChannelDeclaration(
                unit="%", provenance=Provenance.MEASURED, soiling_method=SoilingMethod.SOILING_STATION
            ),
        },
    )
    text = "timestamp,actual_energy_kwh,soiling_ratio\n2026-05-01,46000,94.5\n2026-05-02,46000,94.0\n"
    _, parsed = validate(text, meta)
    assert parsed is not None
    assert parsed.observations[0].soiling_ratio == pytest.approx(0.945)


def test_all_zero_production_is_flagged() -> None:
    report, _ = validate(daily([f"2026-05-{d:02d},0,50000" for d in range(1, 11)]))
    assert "ALL_ZERO_PRODUCTION" in codes(report, IssueSeverity.WARNING)


# --------------------------------------------------------------------------- timestamps


def test_unparseable_timestamps_reject_the_row() -> None:
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)]
    rows[3] = "yesterday,46000,50000"
    report, parsed = validate(daily(rows))
    assert parsed is not None
    assert report.rows_rejected == 1 and report.rows_plant == 9
    issue = next(i for i in report.issues if i.code == "INVALID_TIMESTAMP")
    assert "row 5" in issue.examples[0]
    assert "TIME_GAPS" in codes(report)  # the rejected day is a gap, not a zero
    assert report.missing_intervals == 1


def test_numeric_epoch_timestamps_are_not_guessed() -> None:
    moment, problem = parse_timestamp(1_780_000_000, ALGIERS)
    assert moment is None and problem is not None and "epoch" in problem


def test_timestamp_with_offset_is_converted_to_utc() -> None:
    moment, problem = parse_timestamp("2026-05-01T13:00:00+01:00", ALGIERS)
    assert problem is None
    assert moment == datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    moment, _ = parse_timestamp("2026-05-01T12:00:00Z", ALGIERS)
    assert moment == datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def test_naive_timestamp_is_read_in_the_declared_zone() -> None:
    moment, problem = parse_timestamp("2026-05-01 13:00", ALGIERS)
    assert problem is None
    assert moment == datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def test_local_time_inside_a_daylight_saving_gap_is_rejected() -> None:
    moment, problem = parse_timestamp("2026-03-29 02:30", PARIS)  # clocks jump from 02:00 to 03:00
    assert moment is None
    assert problem is not None and "does not exist" in problem


def test_ambiguous_local_time_is_flagged() -> None:
    moment, problem = parse_timestamp("2026-10-25 02:30", PARIS)  # occurs twice
    assert moment is not None
    assert problem == "AMBIGUOUS"


def test_daily_rows_must_start_at_local_midnight() -> None:
    rows = [f"2026-05-{d:02d}T00:00:00,{46000 + d},{50000}" for d in range(1, 11)]
    rows[6] = "2026-05-07T06:00:00,46000,50000"
    report, parsed = validate(daily(rows))
    assert parsed is not None
    assert "MISALIGNED_TIMESTAMP" in codes(report, IssueSeverity.ERROR)
    assert report.rows_plant == 9


def test_daily_data_in_utc_for_a_plant_in_another_zone_is_caught() -> None:
    """UTC midnights are 01:00 in Algiers: the rows do not describe the plant's local days."""
    rows = [f"2026-05-{d:02d}T00:00:00Z,{46000 + d},{50000}" for d in range(1, 11)]
    report, parsed = validate(daily(rows))
    assert not report.accepted and parsed is None
    assert "MISALIGNED_TIMESTAMP" in codes(report)
    assert "NO_USABLE_DATA" in codes(report, IssueSeverity.BLOCKING)


def test_unsupported_interval_blocks() -> None:
    rows = [f"2026-05-01T{h:02d}:{m:02d}:00,100,110" for h in range(8, 12) for m in (0, 20, 40)]
    report, _ = validate(daily(rows))
    assert codes(report, IssueSeverity.BLOCKING) == {"UNSUPPORTED_INTERVAL"}


def test_declared_interval_must_match_the_data() -> None:
    meta = DatasetMetadata(name="t", interval_minutes=60, channels=measured_channels())
    report, _ = validate(GOOD, meta)
    assert codes(report, IssueSeverity.BLOCKING) == {"INTERVAL_MISMATCH"}


def test_single_row_needs_a_declared_interval() -> None:
    one = daily(["2026-05-01,46000,50000"])
    report, _ = validate(one)
    assert codes(report, IssueSeverity.BLOCKING) == {"INTERVAL_UNKNOWN"}
    report, parsed = validate(one, DatasetMetadata(name="t", interval_minutes=1440, channels=measured_channels()))
    assert report.accepted and parsed is not None


def test_future_timestamps_are_flagged() -> None:
    report, _ = validate(daily([f"2027-05-{d:02d},{46000 + d},{50000}" for d in range(1, 6)]))
    assert "FUTURE_TIMESTAMP" in codes(report, IssueSeverity.WARNING)


def test_gaps_are_counted_and_never_filled() -> None:
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in (1, 2, 3, 7, 8, 9, 10)]
    report, parsed = validate(daily(rows))
    assert parsed is not None
    assert report.missing_intervals == 3
    assert len(parsed.observations) == 7


# --------------------------------------------------------------------------- duplicates


def test_identical_duplicates_are_collapsed() -> None:
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)]
    rows.append(rows[4])
    report, parsed = validate(daily(rows))
    assert parsed is not None
    assert "DUPLICATE_ROWS" in codes(report, IssueSeverity.WARNING)
    assert len(parsed.observations) == 10


def test_conflicting_duplicates_are_all_rejected() -> None:
    """Two different values for the same day: choosing one would be a guess."""
    rows = [f"2026-05-{d:02d},{46000 + d},{50000}" for d in range(1, 11)]
    rows.append("2026-05-05,39000,50000")
    report, parsed = validate(daily(rows))
    assert parsed is not None
    assert "CONFLICTING_DUPLICATES" in codes(report, IssueSeverity.ERROR)
    assert len(parsed.observations) == 9
    assert all(str(o.start_utc.astimezone(ALGIERS).date()) != "2026-05-05" for o in parsed.observations)


# --------------------------------------------------------------------------- provenance


@pytest.mark.safety
def test_undeclared_provenance_is_recorded_as_unknown() -> None:
    report, parsed = validate(GOOD, DatasetMetadata(name="t"))
    assert report.accepted and parsed is not None
    assert "PROVENANCE_NOT_DECLARED" in codes(report, IssueSeverity.WARNING)
    assert parsed.channels[Metric.ACTUAL_ENERGY].tag.provenance is Provenance.UNKNOWN
    summary = next(c for c in report.channels if c.metric is Metric.ACTUAL_ENERGY)
    assert summary.provenance == "UNKNOWN"


@pytest.mark.safety
def test_synthetic_channels_require_a_generator_record() -> None:
    with pytest.raises(ValidationError, match="synthetic"):
        DatasetMetadata(
            name="t", channels={Metric.ACTUAL_ENERGY: ChannelDeclaration(provenance=Provenance.SYNTHETIC)}
        )


@pytest.mark.safety
def test_only_synthetic_channels_may_emulate_another_class() -> None:
    with pytest.raises(ValidationError, match="emulates"):
        ChannelDeclaration(provenance=Provenance.MODELLED, emulates=Provenance.MEASURED)


@pytest.mark.safety
def test_synthetic_dataset_is_reported_as_such() -> None:
    meta = DatasetMetadata(
        name="t",
        channels={
            Metric.ACTUAL_ENERGY: ChannelDeclaration(provenance=Provenance.SYNTHETIC, emulates=Provenance.MEASURED),
            Metric.EXPECTED_ENERGY: ChannelDeclaration(provenance=Provenance.SYNTHETIC, emulates=Provenance.MODELLED),
        },
        synthetic=SyntheticDeclaration(generator="test", generator_version="1", seed=1, statement="Artificial data."),
    )
    report, parsed = validate(GOOD, meta)
    assert report.is_synthetic and parsed is not None
    assert "SYNTHETIC_DATASET" in codes(report, IssueSeverity.INFO)
    assert parsed.channels[Metric.ACTUAL_ENERGY].tag.label == "SYNTHETIC (emulates MEASURED)"


def test_unknown_metadata_fields_are_refused() -> None:
    with pytest.raises(ValidationError):
        DatasetMetadata.model_validate({"name": "t", "provenance": "MEASURED"})
    with pytest.raises(ValidationError):
        DatasetMetadata.model_validate({"name": "t", "channels": {"not_a_metric": {}}})


def test_missing_declarations_are_pointed_out() -> None:
    header = "timestamp,actual_energy_kwh,expected_energy_kwh,soiling_ratio"
    rows = [f"2026-05-{d:02d},46000,50000,0.93" for d in range(1, 11)]
    meta = DatasetMetadata(
        name="t", channels=measured_channels(soiling_ratio=ChannelDeclaration(provenance=Provenance.MEASURED))
    )
    report, _ = validate(daily(rows, header), meta)
    assert {"BASELINE_NOT_DESCRIBED", "SOILING_METHOD_NOT_DECLARED"} <= codes(report, IssueSeverity.WARNING)
    assert {"UNCERTAINTY_NOT_DECLARED", "METERING_BOUNDARY_NOT_DECLARED"} <= codes(report, IssueSeverity.INFO)


# --------------------------------------------------------------------------- devices


DEVICE_FILE = (
    "timestamp,device_code,actual_energy_kwh\n"
    "2026-05-01,,46000\n2026-05-02,,46100\n"
    "2026-05-01,INV-1,23000\n2026-05-02,INV-1,23050\n"
    "2026-05-01,INV-2,23000\n2026-05-02,INV-2,23050\n"
    "2026-05-01,INV-9,1\n"
)


def test_device_rows_are_separated_from_plant_rows() -> None:
    known = {
        "INV-1": DeviceSpec(code="INV-1", capacity_kwp=5000.0),
        "INV-2": DeviceSpec(code="INV-2", capacity_kwp=5000.0),
    }
    meta = DatasetMetadata(name="t", channels=measured_channels())
    report, parsed = validate(DEVICE_FILE, meta, known_devices=known)
    assert parsed is not None
    assert report.rows_plant == 2 and report.rows_device == 4
    assert set(parsed.device_observations) == {"INV-1", "INV-2"}
    assert parsed.device_observations["INV-1"][0].actual_energy_kwh == 23000.0
    assert report.devices == ["INV-1", "INV-2"]
    issue = next(i for i in report.issues if i.code == "UNKNOWN_DEVICE")
    assert issue.severity is IssueSeverity.WARNING and "INV-9" in issue.examples[0]
    assert parsed.device_tag is not None and parsed.device_tag.label == "MEASURED"


# --------------------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("raw", "decimal_comma", "expected"),
    [("12.5", False, 12.5), ("12,5", True, 12.5), (7, False, 7.0), (" 3e3 ", False, 3000.0)],
)
def test_parse_number(raw: object, decimal_comma: bool, expected: float) -> None:
    assert parse_number(raw, decimal_comma) == (expected, None)


def test_parse_number_problems() -> None:
    assert parse_number(None, False) == (None, None)
    assert parse_number("abc", False) == (None, "not a number")
    assert parse_number(True, False) == (None, "boolean is not a number")
    assert parse_number("12,5", False) == (None, "not a number")  # a comma is not guessed to be a decimal sign
    assert parse_number(float("inf"), False) == (None, "non-finite value")


def test_json_records_are_validated_like_csv() -> None:
    table = RawTable(
        columns=["timestamp", "actual_energy_kwh"],
        rows=[
            {"timestamp": "2026-05-01", "actual_energy_kwh": 46000},
            {"timestamp": "2026-05-02", "actual_energy_kwh": None},
            {"timestamp": "2026-05-03", "actual_energy_kwh": True},
        ],
        file_format="JSON",
    )
    report, parsed = validate_table(
        table, DatasetMetadata(name="t", channels=measured_channels()), plant=PLANT, now=NOW
    )
    assert parsed is not None
    values = [o.actual_energy_kwh for o in parsed.observations]
    assert values == [46000.0, None, None]
    assert report.values_rejected == 1  # the boolean; null is simply missing
