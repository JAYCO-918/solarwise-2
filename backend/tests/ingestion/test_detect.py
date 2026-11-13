"""Reading a file before anything is declared: what is proposed, what is flagged, and what is left alone."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from solarwise.core.models import METRIC_SPECS, PLANT_LEVEL_METRICS, Metric, PlantSpec
from solarwise.core.units import dimension_of
from solarwise.ingestion import templates
from solarwise.ingestion.detect import (
    ColumnRole,
    Confidence,
    UploadPreview,
    accepted_units,
    describe_header,
    preview_table,
    split_header,
)
from solarwise.ingestion.parser import ParseError, RawTable, parse_csv, parse_upload
from solarwise.ingestion.schema import DatasetMetadata
from solarwise.ingestion.validator import validate_table
from tests import support
from tests.builders import PLANT

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "samples"
SMALL_PLANT = PlantSpec(name="Example", capacity_dc_kwp=1000, capacity_ac_kw=900, latitude=33.5, longitude=6.8,
                        timezone="Africa/Algiers")


def preview(text: str, plant: PlantSpec = PLANT) -> UploadPreview:
    return preview_table(parse_csv(text.encode()), plant=plant)


def codes(result: UploadPreview, column: str | None = None) -> set[str]:
    return {n.code for n in result.notes if column is None or n.column == column}


# --------------------------------------------------------------------------- headers


HEADERS: list[tuple[str, ColumnRole, Metric | None, str | None, Confidence]] = [
    ("timestamp", ColumnRole.TIMESTAMP, None, None, Confidence.EXACT),
    ("Date", ColumnRole.TIMESTAMP, None, None, Confidence.NAME),
    ("Horodatage", ColumnRole.TIMESTAMP, None, None, Confidence.NAME),
    ("device_code", ColumnRole.DEVICE, None, None, Confidence.EXACT),
    ("Inverter", ColumnRole.DEVICE, None, None, Confidence.NAME),
    ("actual_energy_kwh", ColumnRole.QUANTITY, Metric.ACTUAL_ENERGY, "kWh", Confidence.EXACT),
    ("Energy (kWh)", ColumnRole.QUANTITY, Metric.ACTUAL_ENERGY, "kWh", Confidence.NAME),
    ("energy_mwh", ColumnRole.QUANTITY, Metric.ACTUAL_ENERGY, "mwh", Confidence.NAME),
    ("Énergie produite (MWh)", ColumnRole.QUANTITY, Metric.ACTUAL_ENERGY, "mwh", Confidence.NAME),
    ("E_AC", ColumnRole.QUANTITY, Metric.ACTUAL_ENERGY, "kWh", Confidence.NAME),
    ("Yield", ColumnRole.QUANTITY, Metric.ACTUAL_ENERGY, "kWh", Confidence.AMBIGUOUS),
    ("Expected production (kWh)", ColumnRole.QUANTITY, Metric.EXPECTED_ENERGY, "kWh", Confidence.NAME),
    ("Reference production", ColumnRole.QUANTITY, Metric.EXPECTED_ENERGY, "kWh", Confidence.NAME),
    ("Production attendue", ColumnRole.QUANTITY, Metric.EXPECTED_ENERGY, "kWh", Confidence.NAME),
    ("Budget", ColumnRole.QUANTITY, Metric.EXPECTED_ENERGY, "kWh", Confidence.NAME),
    ("Irradiance (W/m2)", ColumnRole.QUANTITY, Metric.POA_IRRADIATION, "w/m2", Confidence.AMBIGUOUS),
    ("POA irradiation [kWh/m²]", ColumnRole.QUANTITY, Metric.POA_IRRADIATION, "kWh/m2", Confidence.NAME),
    ("poa_irradiance_w_m2", ColumnRole.QUANTITY, Metric.POA_IRRADIATION, "w/m2", Confidence.NAME),
    ("GHI Wh/m2", ColumnRole.QUANTITY, Metric.GHI, "wh/m2", Confidence.NAME),
    ("Module temperature (°C)", ColumnRole.QUANTITY, Metric.MODULE_TEMP, "degC", Confidence.NAME),
    ("Tmod_C", ColumnRole.QUANTITY, Metric.MODULE_TEMP, "degC", Confidence.NAME),
    ("Ambient temperature (°C)", ColumnRole.QUANTITY, Metric.AMBIENT_TEMP, "degC", Confidence.NAME),
    ("Température ambiante (°C)", ColumnRole.QUANTITY, Metric.AMBIENT_TEMP, "degC", Confidence.NAME),
    ("Temperature", ColumnRole.QUANTITY, Metric.AMBIENT_TEMP, "degC", Confidence.AMBIGUOUS),
    ("Relative humidity (%)", ColumnRole.QUANTITY, Metric.RELATIVE_HUMIDITY, "percent", Confidence.NAME),
    ("humidity_pct", ColumnRole.QUANTITY, Metric.RELATIVE_HUMIDITY, "percent", Confidence.NAME),
    ("Wind speed (m/s)", ColumnRole.QUANTITY, Metric.WIND_SPEED, "m/s", Confidence.NAME),
    ("vitesse vent ms", ColumnRole.QUANTITY, Metric.WIND_SPEED, "m/s", Confidence.NAME),
    ("wind_speed_m_s", ColumnRole.QUANTITY, Metric.WIND_SPEED, "m/s", Confidence.NAME),
    ("Rainfall (mm)", ColumnRole.QUANTITY, Metric.PRECIPITATION, "mm", Confidence.NAME),
    ("Soiling ratio", ColumnRole.QUANTITY, Metric.SOILING_RATIO, "fraction", Confidence.NAME),
    ("soiling_loss_pct", ColumnRole.QUANTITY, Metric.SOILING_RATIO, "percent", Confidence.NAME),
    ("Soiling", ColumnRole.QUANTITY, Metric.SOILING_RATIO, "fraction", Confidence.AMBIGUOUS),
    ("Availability (%)", ColumnRole.QUANTITY, Metric.AVAILABILITY, "percent", Confidence.NAME),
    ("Curtailed energy (MWh)", ColumnRole.QUANTITY, Metric.CURTAILED_ENERGY, "mwh", Confidence.NAME),
    ("Cleaning", ColumnRole.CLEANING, None, None, Confidence.NAME),
    ("cleaning_event", ColumnRole.CLEANING, None, None, Confidence.NAME),
    ("Alarms", ColumnRole.EVENTS, None, None, Confidence.NAME),
    ("Equipment alarms", ColumnRole.EVENTS, None, None, Confidence.NAME),
    ("Operational events", ColumnRole.EVENTS, None, None, Confidence.NAME),
    ("Status", ColumnRole.EVENTS, None, None, Confidence.AMBIGUOUS),
    ("PR", ColumnRole.UNUSED, None, None, Confidence.NONE),
    ("Operator on duty", ColumnRole.UNUSED, None, None, Confidence.NONE),
]


@pytest.mark.parametrize(("header", "role", "metric", "unit", "confidence"), HEADERS, ids=[h[0] for h in HEADERS])
def test_what_a_header_is_read_as(header: str, role: ColumnRole, metric: Metric | None, unit: str | None,
                                  confidence: Confidence) -> None:
    described = describe_header(header)
    assert (described.role, described.metric, described.unit, described.confidence) == (role, metric, unit, confidence)
    assert described.reason


def test_a_unit_in_the_header_is_stated_and_a_missing_one_is_only_assumed() -> None:
    assert describe_header("Energy (MWh)").unit_source == "HEADER"
    assert describe_header("Energy").unit_source == "ASSUMED" and describe_header("Energy").unit == "kWh"
    assert split_header("Module temperature (°C)") == ("module temperature", "degC")
    assert split_header("poa_irradiance_w_m2") == ("poa irradiance", "w/m2")
    assert split_header("kWh") == ("kwh", None)  # a header that is nothing but a unit names no quantity


def test_a_soiling_column_says_whether_it_is_a_ratio_or_a_loss() -> None:
    assert describe_header("Soiling ratio").reported_as == "RATIO"
    assert describe_header("Soiling loss (%)").reported_as == "LOSS"
    assert describe_header("Pertes par salissure (%)").reported_as == "LOSS"
    assert describe_header("Energy (kWh)").reported_as is None


@pytest.mark.parametrize("header", ["Inverter output power (kW)", "Energy (kW)", "Module temperature (kWh)"])
def test_a_column_whose_unit_belongs_to_another_quantity_is_not_proposed(header: str) -> None:
    """Power is not energy, whatever the name says: the column is left for the uploader to assign."""
    described = describe_header(header)
    assert described.role is ColumnRole.UNUSED and described.metric is None
    assert "not a unit" in described.reason
    assert describe_header("AC power (MW)").role is ColumnRole.UNUSED  # a name that fits no quantity at all


def test_every_proposed_unit_is_one_the_validator_accepts() -> None:
    for header, _role, metric, unit, _confidence in HEADERS:
        if metric is not None and unit is not None:
            assert unit.lower() in {u.lower() for u in accepted_units(metric)}, header


def test_irradiation_columns_also_accept_irradiance() -> None:
    for metric in PLANT_LEVEL_METRICS:
        units = accepted_units(metric)
        assert units[0] == METRIC_SPECS[metric].unit
        dimensions = {dimension_of(u) for u in units}
        if METRIC_SPECS[metric].dimension == "irradiation":
            assert dimensions == {"irradiation", "irradiance"} and "w/m2" in units
        else:
            assert dimensions == {METRIC_SPECS[metric].dimension}


# --------------------------------------------------------------------------- the proposal


def test_an_operators_export_is_mapped_without_any_declaration() -> None:
    result = preview(support.operator_csv(alarms={10: "Inverter fault INV-02"}, cleaned=(5,)))
    proposal = result.proposal
    assert proposal.timestamp_column == "Date" and proposal.device_column is None
    assert proposal.cleaning_column == "Cleaning" and proposal.event_column == "Alarms"
    assert proposal.interval_minutes == 1440
    mapped = {metric.value: (c.column, c.unit, c.reported_as) for metric, c in proposal.channels.items()}
    assert mapped == {
        "actual_energy": ("Energy (kWh)", "kWh", "RATIO"),
        "expected_energy": ("Expected production (kWh)", "kWh", "RATIO"),
        "poa_irradiation": ("Irradiance (W/m2)", "w/m2", "RATIO"),
        "module_temp": ("Module temperature (°C)", "degC", "RATIO"),
        "soiling_ratio": ("Soiling loss (%)", "percent", "LOSS"),
    }
    assert result.rows_total == 30 and result.file_format == "CSV" and result.embedded_metadata is False


def test_a_proposal_never_says_where_the_data_come_from() -> None:
    result = preview(support.operator_csv())
    dumped = result.model_dump_json()
    for word in ("provenance", "MEASURED", "MODELLED", "SYNTHETIC"):
        assert word not in dumped


def test_reading_a_file_does_not_change_it() -> None:
    table = parse_csv(support.operator_csv(cells={(3, "Energy (kWh)"): "n/a", (4, "Energy (kWh)"): "-5"}).encode())
    before = copy.deepcopy(table.rows)
    preview_table(table, plant=PLANT)
    assert table.rows == before


def test_the_rows_shown_are_the_cells_of_the_file() -> None:
    result = preview(support.operator_csv(cells={(0, "Energy (kWh)"): "", (1, "Alarms"): "Grid outage"}))
    assert [c.name for c in result.columns] == support.OPERATOR_HEADER
    assert len(result.sample_rows) == 12
    first = dict(zip(support.OPERATOR_HEADER, result.sample_rows[0], strict=True))
    assert first["Date"] == "2026-05-01" and first["Energy (kWh)"] == ""  # an empty cell stays empty: never a zero
    assert dict(zip(support.OPERATOR_HEADER, result.sample_rows[1], strict=True))["Alarms"] == "Grid outage"
    energy = next(c for c in result.columns if c.name == "Energy (kWh)")
    assert (energy.filled, energy.empty, energy.numeric) == (29, 1, 29) and energy.minimum == energy.maximum == 46000.0


def test_two_columns_for_one_quantity_the_surer_reading_wins() -> None:
    result = preview("timestamp,Energy,actual_energy_kwh\n2026-05-01,1,45000\n2026-05-02,2,46000\n")
    assert result.proposal.channels[Metric.ACTUAL_ENERGY].column == "actual_energy_kwh"
    other = next(c for c in result.columns if c.name == "Energy")
    assert other.role is ColumnRole.UNUSED and "actual_energy_kwh" in other.reason


def test_a_date_column_and_a_time_column_are_reported() -> None:
    result = preview("Date,Time,Energy (kWh)\n2026-05-01,10:00,400\n2026-05-01,11:00,500\n")
    assert result.proposal.timestamp_column == "Date"
    assert "DATE_AND_TIME_IN_TWO_COLUMNS" in codes(result)


def test_a_column_of_text_is_not_proposed_as_a_quantity() -> None:
    result = preview("timestamp,Energy (kWh),Temperature\n2026-05-01,45000,hot\n2026-05-02,46000,mild\n")
    column = next(c for c in result.columns if c.name == "Temperature")
    assert column.role is ColumnRole.UNUSED and "no cell of the column is a number" in column.reason
    assert Metric.AMBIENT_TEMP not in result.proposal.channels


def test_the_interval_is_read_from_the_timestamps() -> None:
    hourly = "timestamp,Energy (kWh)\n" + "".join(f"2026-05-01T{h:02d}:00,{h}\n" for h in range(6, 18))
    assert preview(hourly).proposal.interval_minutes == 60
    quarter = "timestamp,Energy (kWh)\n" + "".join(f"2026-05-01T10:{m:02d},{m}\n" for m in (0, 15, 30, 45))
    assert preview(quarter).proposal.interval_minutes == 15
    odd = "timestamp,Energy (kWh)\n2026-05-01T10:00,1\n2026-05-01T10:07,2\n2026-05-01T10:14,3\n"
    result = preview(odd)
    assert result.proposal.interval_minutes is None and "INTERVAL_NOT_REGULAR" in codes(result)


# --------------------------------------------------------------------------- notes on the values


def daily(header: str, values: list[str], extra_header: str = "", extra: str = "") -> str:
    lines = [f"timestamp,{header}{extra_header}"]
    lines += [f"2026-05-{i + 1:02d},{value}{extra}" for i, value in enumerate(values)]
    return "\n".join(lines) + "\n"


def test_units_that_do_not_fit_the_values_are_flagged_with_a_suggestion() -> None:
    cases = [
        (daily("Module temperature", ["315.2", "318.9", "321.4"]), "LOOKS_LIKE_KELVIN", "k"),
        (daily("Relative humidity", ["0.21", "0.35", "0.18", "0.40", "0.27"]), "LOOKS_LIKE_FRACTION", "fraction"),
        (daily("Soiling ratio", ["97.5", "96.8", "95.9"]), "LOOKS_LIKE_PERCENT", "percent"),
        (daily("Availability", ["99.5", "98.0", "100"]), "LOOKS_LIKE_PERCENT", "percent"),
        # 10 MWp: at most 8,500 kW x 24 h = 204,000 kWh a day.
        (daily("Energy", ["48000000", "51000000", "47500000"]), "LOOKS_LIKE_WH", "wh"),
        (daily("Energy", ["48.2", "51.0", "47.5"]), "LOOKS_LIKE_MWH", "mwh"),
    ]
    for text, code, unit in cases:
        result = preview(text)
        note = next((n for n in result.notes if n.code == code), None)
        assert note is not None, (code, codes(result))
        assert note.suggested_unit == unit and note.severity == "WARNING"
        # Offered, not applied: the proposal keeps the unit the header gave or the canonical one.
        channel = next(iter(result.proposal.channels.values()))
        assert channel.unit.lower() != unit


def test_a_meter_counter_is_told_from_the_energy_of_each_interval() -> None:
    counter = daily("Energy", [str(5_000_000 + 46_000 * i) for i in range(12)])
    result = preview(counter)
    assert "LOOKS_LIKE_A_COUNTER" in codes(result) and "LOOKS_LIKE_WH" not in codes(result)


def test_irradiance_in_a_column_read_as_irradiation_is_flagged() -> None:
    hourly = "timestamp,POA irradiation\n" + "".join(f"2026-05-01T{h:02d}:00,{v}\n" for h, v in zip(range(8, 14), (310, 520, 700, 850, 930, 960), strict=True))
    result = preview(hourly)
    note = next(n for n in result.notes if n.code == "LOOKS_LIKE_IRRADIANCE")
    assert note.suggested_unit == "w/m2"
    assert result.proposal.channels[Metric.POA_IRRADIATION].unit == "kWh/m2"


def test_a_soiling_column_that_looks_like_the_other_kind_is_flagged() -> None:
    loss_named_ratio = preview(daily("Soiling ratio", ["0.03", "0.05", "0.08"]))
    assert "LOOKS_LIKE_A_LOSS" in codes(loss_named_ratio)
    ratio_named_loss = preview(daily("Soiling loss (%)", ["97", "96", "95"]))
    assert "LOOKS_LIKE_A_RATIO" in codes(ratio_named_loss)
    assert not codes(preview(daily("Soiling ratio", ["0.97", "0.96", "0.95"]))) & {"LOOKS_LIKE_A_LOSS", "LOOKS_LIKE_A_RATIO"}


def test_cells_that_would_be_rejected_are_announced_and_left_as_they_are() -> None:
    text = daily("Energy (kWh)", ["46000", "error", "-12", "", "45000", "n/a"])
    table = parse_csv(text.encode())
    result = preview_table(table, plant=PLANT)
    found = codes(result, "Energy (kWh)")
    assert {"TEXT_IN_NUMERIC_COLUMN", "NEGATIVE_VALUES"} <= found
    assert [row["Energy (kWh)"] for row in table.rows] == ["46000", "error", "-12", "", "45000", "n/a"]
    column = next(c for c in result.columns if c.name == "Energy (kWh)")
    assert (column.filled, column.empty, column.numeric) == (4, 2, 3)  # empty and n/a are missing, not zero
    assert column.minimum == -12.0 and column.maximum == 46000.0


def test_other_patterns_worth_a_look() -> None:
    assert "CONSTANT_COLUMN" in codes(preview(daily("Module temperature (°C)", ["45"] * 12)))
    assert "MOSTLY_EMPTY" in codes(preview(daily("Soiling ratio", ["0.97", "", "", "", ""])))
    assert "UNIT_NOT_STATED" in codes(preview(daily("Energy", ["46000", "45000"])), "Energy")
    assert "UNIT_NOT_STATED" not in codes(preview(daily("Energy (kWh)", ["46000", "45000"])))
    unread = preview("Date,Energy (kWh)\nMay 1st,46000\n2026-05-02,45000\n2026-05-03,45500\n")
    assert "TIMESTAMPS_NOT_READ" in codes(unread)
    no_time = preview("Energy (kWh),Soiling ratio\n46000,0.97\n45000,0.96\n")
    assert no_time.proposal.timestamp_column is None and "NO_TIMESTAMP_COLUMN" in codes(no_time)


def test_what_the_file_lacks_is_said_plainly() -> None:
    result = preview(daily("Energy (kWh)", ["46000", "45000", "45500"]))
    assert {"NO_EXPECTED_ENERGY", "NO_SOILING_MEASUREMENT", "NO_IRRADIANCE", "NO_TEMPERATURE"} <= codes(result)
    soiling = next(n for n in result.notes if n.code == "NO_SOILING_MEASUREMENT")
    assert "never Clean now" in soiling.message
    nothing = preview("timestamp,Operator\n2026-05-01,A\n2026-05-02,B\n")
    assert "NO_ENERGY_COLUMN" in codes(nothing) and not nothing.proposal.channels


def test_events_and_unknown_devices_are_announced() -> None:
    result = preview(support.operator_csv(alarms={3: "Inverter fault INV-02", 4: "Inverter fault INV-02", 9: "Grid outage"}))
    events = next(n for n in result.notes if n.code == "EVENTS_IN_FILE")
    assert "3 marked row(s)" in events.message and "2 different text(s)" in events.message
    quiet = preview(support.operator_csv())
    assert "NO_EVENT_IN_COLUMN" in codes(quiet)
    devices = preview("timestamp,device_code,actual_energy_kwh\n2026-05-01,INV-77,500\n2026-05-02,INV-77,510\n")
    assert "DEVICES_NOT_REGISTERED" in codes(devices)


# --------------------------------------------------------------------------- the files offered for download


def test_the_example_files_are_read_completely_and_import_cleanly() -> None:
    for name in ("solarwise-operational-data.example.csv", "solarwise-operational-data.example.json"):
        template = templates.find(name)
        assert template is not None and template.example is True
        table = parse_upload(templates.read(template), name)
        result = preview_table(table, plant=SMALL_PLANT)
        assert result.rows_total == 14 and result.proposal.interval_minutes == 1440
        proposal = result.proposal
        assert proposal.timestamp_column == "timestamp" and proposal.cleaning_column == "cleaning_event"
        assert proposal.event_column == "alarm"
        assert {m.value for m in proposal.channels} == {
            "actual_energy", "expected_energy", "poa_irradiation", "module_temp", "ambient_temp", "relative_humidity",
            "wind_speed", "precipitation", "soiling_ratio",
        }
        assert all(c.role is not ColumnRole.UNUSED for c in result.columns)
        assert not [n for n in result.notes if n.severity == "WARNING"]
        metadata = DatasetMetadata.model_validate({
            "name": name, "timestamp_column": proposal.timestamp_column,
            "channels": {m.value: {"column": c.column, "unit": c.unit} for m, c in proposal.channels.items()},
            "events": {"cleaning_column": proposal.cleaning_column, "event_column": proposal.event_column},
        })
        report, parsed = validate_table(table, metadata, plant=SMALL_PLANT)
        assert report.accepted and parsed is not None and report.rows_plant == 14 and report.values_rejected == 0
        assert [e.evidence_type.value for e in report.events] == ["CLEANING_EVENT", "INVERTER_FAULT", "GRID_OUTAGE"]
        # Nothing was declared about where the values come from, so nothing counts as measured.
        assert all(c.provenance == "UNKNOWN" for c in report.channels)


def test_a_template_cannot_be_imported_by_mistake() -> None:
    with pytest.raises(ParseError, match="no data rows"):
        parse_upload(templates.read(templates.TEMPLATES[0]), templates.TEMPLATES[0].name)
    name = "solarwise-operational-data.template.json"
    table = parse_upload(templates.read(templates.find(name)), name)  # type: ignore[arg-type]
    report, parsed = validate_table(table, DatasetMetadata(name="template"), plant=SMALL_PLANT)
    assert not report.accepted and parsed is None


def test_the_templates_share_one_set_of_columns() -> None:
    header = templates.read(templates.TEMPLATES[0]).decode().strip().split(",")
    assert header[0] == "timestamp" and "energy_kwh" in header and "alarm" in header
    for template in templates.TEMPLATES:
        data = templates.read(template)
        if template.name.endswith(".csv"):
            assert data.decode().splitlines()[0].split(",") == header
        else:
            assert list(json.loads(data)["records"][0]) == header
        assert template.title and template.description


def test_the_copies_in_data_samples_are_the_packaged_files() -> None:
    for template in templates.TEMPLATES:
        assert (SAMPLES / template.name).read_bytes() == templates.read(template), template.name


def test_a_table_built_by_hand_is_previewed_like_a_file() -> None:
    table = RawTable(columns=["timestamp", "Energy (kWh)"], rows=[{"timestamp": "2026-05-01", "Energy (kWh)": 46000.0},
                                                               {"timestamp": "2026-05-02", "Energy (kWh)": None}],
                     file_format="JSON")
    result = preview_table(table, plant=PLANT)
    assert result.sample_rows == [["2026-05-01", "46000.0"], ["2026-05-02", ""]]
    assert result.proposal.channels[Metric.ACTUAL_ENERGY].column == "Energy (kWh)"
