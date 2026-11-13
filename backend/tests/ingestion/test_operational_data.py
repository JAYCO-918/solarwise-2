"""Operational files: irradiance, soiling loss, events, rejected rows - and what never happens to a value."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from solarwise.core.models import EvidenceType, Metric
from solarwise.core.pipeline import AnalysisInput, AnalysisOptions, run_analysis
from solarwise.core.provenance import EvaluationContext, Provenance
from solarwise.ingestion.parser import RawTable, parse_csv, parse_json
from solarwise.ingestion.schema import DatasetMetadata, EventsDeclaration
from solarwise.ingestion.validator import (
    EVENT_VOCABULARY,
    ISSUE_HINTS,
    MAX_EVENTS,
    MAX_IRRADIANCE_W_M2,
    ParsedDataset,
    Rejection,
    ValidationReport,
    classify_event,
    validate_table,
)
from tests import support
from tests.builders import PLANT, cleaning_assumptions, economic_inputs


def validate(text: str, meta: dict[str, Any], *, rejections: list[Rejection] | None = None,
             table: RawTable | None = None) -> tuple[ValidationReport, ParsedDataset | None]:
    return validate_table(table or parse_csv(text.encode()), DatasetMetadata.model_validate(meta), plant=PLANT,
                          rejections=rejections)


def issue(report: ValidationReport, code: str) -> Any:
    return next((i for i in report.issues if i.code == code), None)


ENERGY = {"actual_energy": {"column": "energy"}}


# --------------------------------------------------------------------------- irradiance


@pytest.mark.parametrize(
    ("stamps", "watts", "expected_kwh_m2"),
    [(["2026-05-01T10:00", "2026-05-01T11:00"], 800.0, 0.8),
     (["2026-05-01T10:00", "2026-05-01T10:30"], 800.0, 0.4),
     (["2026-05-01T10:00", "2026-05-01T10:15"], 800.0, 0.2),
     (["2026-05-01", "2026-05-02"], 270.0, 6.48)],
)
def test_mean_irradiance_times_the_interval_is_the_irradiation(stamps: list[str], watts: float, expected_kwh_m2: float) -> None:
    text = "timestamp,energy,irr\n" + "".join(f"{stamp},100,{watts}\n" for stamp in stamps)
    report, parsed = validate(text, {"name": "x", "channels": {**ENERGY, "poa_irradiation": {"column": "irr", "unit": "W/m2"}}})
    assert parsed is not None and report.accepted
    assert [o.poa_irradiation_kwh_m2 for o in parsed.observations] == pytest.approx([expected_kwh_m2] * 2)
    channel = next(c for c in report.channels if c.metric is Metric.POA_IRRADIATION)
    assert channel.unit_in == "W/m2" and channel.unit == "kWh/m2"
    assert channel.minimum == pytest.approx(expected_kwh_m2) and channel.maximum == pytest.approx(expected_kwh_m2)
    converted = issue(report, "IRRADIANCE_CONVERTED")
    assert converted is not None and converted.severity.value == "WARNING" and "mean over each interval" in converted.message
    assert converted.hint == ISSUE_HINTS["IRRADIANCE_CONVERTED"]
    assert parsed.channels[Metric.POA_IRRADIATION].original_unit == "W/m2"


def test_irradiance_in_kilowatts_and_for_the_horizontal_plane() -> None:
    text = "timestamp,energy,ghi\n2026-05-01T10:00,100,0.6\n2026-05-01T11:00,100,0.9\n"
    _, parsed = validate(text, {"name": "x", "channels": {**ENERGY, "ghi": {"column": "ghi", "unit": "kW/m2"}}})
    assert parsed is not None
    assert [o.ghi_kwh_m2 for o in parsed.observations] == pytest.approx([0.6, 0.9])


def test_an_impossible_irradiance_is_rejected_as_missing_never_as_zero() -> None:
    text = f"timestamp,energy,irr\n2026-05-01T10:00,100,{MAX_IRRADIANCE_W_M2 + 400}\n2026-05-01T11:00,100,750\n2026-05-01T12:00,100,\n"
    rejections: list[Rejection] = []
    report, parsed = validate(
        text, {"name": "x", "channels": {**ENERGY, "poa_irradiation": {"column": "irr", "unit": "w/m2"}}}, rejections=rejections
    )
    assert parsed is not None
    assert [o.poa_irradiation_kwh_m2 for o in parsed.observations] == [None, pytest.approx(0.75), None]
    assert [(r.row, r.column, r.code) for r in rejections] == [(2, "irr", "OUT_OF_RANGE")]
    channel = next(c for c in report.channels if c.metric is Metric.POA_IRRADIATION)
    assert (channel.values, channel.missing, channel.rejected) == (1, 1, 1)


def test_a_unit_of_another_quantity_is_still_refused_for_irradiation() -> None:
    text = "timestamp,energy,irr\n2026-05-01,100,5\n2026-05-02,100,6\n"
    report, parsed = validate(text, {"name": "x", "channels": {**ENERGY, "poa_irradiation": {"column": "irr", "unit": "kWh"}}})
    assert parsed is None and issue(report, "INVALID_UNIT").severity.value == "BLOCKING"
    # ... and irradiance is not accepted for a quantity that is not an irradiation.
    report, parsed = validate(text, {"name": "x", "channels": {"actual_energy": {"column": "energy", "unit": "W/m2"}}})
    assert parsed is None and issue(report, "INVALID_UNIT") is not None


# --------------------------------------------------------------------------- soiling loss


@pytest.mark.parametrize(("unit", "cells", "ratios"), [
    ("percent", ["8", "0", "12.5"], [0.92, 1.0, 0.875]),
    ("fraction", ["0.08", "0", "0.125"], [0.92, 1.0, 0.875]),
])
def test_a_measured_soiling_loss_is_stored_as_the_ratio_the_engine_uses(unit: str, cells: list[str], ratios: list[float]) -> None:
    text = "timestamp,energy,loss\n" + "".join(f"2026-05-{i + 1:02d},100,{c}\n" for i, c in enumerate(cells))
    meta = {"name": "x", "channels": {**ENERGY, "soiling_ratio": {"column": "loss", "unit": unit, "reported_as": "LOSS"}}}
    report, parsed = validate(text, meta)
    assert parsed is not None
    assert [o.soiling_ratio for o in parsed.observations] == pytest.approx(ratios)
    assert issue(report, "SOILING_LOSS_CONVERTED").severity.value == "INFO"


def test_a_loss_outside_the_possible_range_is_rejected_not_clipped() -> None:
    text = "timestamp,energy,loss\n2026-05-01,100,130\n2026-05-02,100,-30\n2026-05-03,100,8\n2026-05-04,100,\n"
    rejections: list[Rejection] = []
    meta = {"name": "x", "channels": {**ENERGY, "soiling_ratio": {"column": "loss", "unit": "percent", "reported_as": "LOSS"}}}
    report, parsed = validate(text, meta, rejections=rejections)
    assert parsed is not None
    # 130 % loss -> ratio -0.3 (rejected); -30 % loss -> ratio 1.3 (rejected); an empty cell stays missing.
    assert [o.soiling_ratio for o in parsed.observations] == [None, None, pytest.approx(0.92), None]
    assert [(r.row, r.code) for r in rejections] == [(2, "OUT_OF_RANGE"), (3, "OUT_OF_RANGE")]
    # The message speaks of the loss that is in the file, not of the ratio it would have been turned into.
    out_of_range = issue(report, "OUT_OF_RANGE")
    assert "not a possible soiling loss" in out_of_range.message and out_of_range.examples == ["row 2: 130", "row 3: -30"]
    assert issue(report, "NEGATIVE_VALUE") is None


def test_a_ratio_stays_a_ratio_and_only_soiling_can_be_reported_as_a_loss() -> None:
    text = "timestamp,energy,sr\n2026-05-01,100,0.92\n2026-05-02,100,0.93\n"
    for declaration in ({"column": "sr"}, {"column": "sr", "reported_as": "RATIO"}):
        _, parsed = validate(text, {"name": "x", "channels": {**ENERGY, "soiling_ratio": declaration}})
        assert parsed is not None and [o.soiling_ratio for o in parsed.observations] == [0.92, 0.93]
    with pytest.raises(ValueError, match="only applies to the soiling channel"):
        DatasetMetadata.model_validate({"name": "x", "channels": {"actual_energy": {"reported_as": "LOSS"}}})


# --------------------------------------------------------------------------- missing values


def test_what_is_missing_stays_missing_through_the_mapped_columns() -> None:
    text = support.operator_csv(days=6, cells={
        (0, "Energy (kWh)"): "", (1, "Energy (kWh)"): "n/a", (2, "Energy (kWh)"): "0", (3, "Energy (kWh)"): "abc",
        (4, "Irradiance (W/m2)"): "", (5, "Soiling loss (%)"): "NA",
    })
    meta = {
        "name": "x", "timestamp_column": "Date",
        "channels": {
            "actual_energy": {"column": "Energy (kWh)"}, "expected_energy": {"column": "Expected production (kWh)"},
            "poa_irradiation": {"column": "Irradiance (W/m2)", "unit": "w/m2"},
            "soiling_ratio": {"column": "Soiling loss (%)", "unit": "percent", "reported_as": "LOSS"},
        },
    }
    rejections: list[Rejection] = []
    report, parsed = validate(text, meta, rejections=rejections)
    assert parsed is not None
    energy = [o.actual_energy_kwh for o in parsed.observations]
    assert energy[:4] == [None, None, 0.0, None]  # empty, n/a and text are missing; a written zero is a zero
    assert parsed.observations[4].poa_irradiation_kwh_m2 is None
    assert parsed.observations[5].soiling_ratio is None
    assert all(o.expected_energy_kwh == 50_000.0 for o in parsed.observations)  # nothing else was touched
    assert [(r.row, r.column, r.value, r.code) for r in rejections] == [(5, "Energy (kWh)", "abc", "NON_NUMERIC")]
    assert "not as zero" in rejections[0].problem
    assert report.values_rejected == 1 and report.rejections_total == 1


# --------------------------------------------------------------------------- events


EVENT_META: dict[str, Any] = {
    "name": "x", "timestamp_column": "Date",
    "channels": {"actual_energy": {"column": "Energy (kWh)"}, "expected_energy": {"column": "Expected production (kWh)"}},
    "events": {"cleaning_column": "Cleaning", "event_column": "Alarms", "provenance": "MEASURED", "source": "SCADA log"},
}


def test_marks_and_alarm_texts_become_evidence_records() -> None:
    text = support.operator_csv(
        days=14, cleaned=(4,),
        alarms={7: "Inverter fault INV-02", 8: "Inverter fault INV-02", 10: "Curtailment order 50 %", 13: "Grid outage"},
    )
    report, parsed = validate(text, EVENT_META)
    assert parsed is not None
    summary = [(e.reference, e.evidence_type.value, e.first_day.isoformat(), e.last_day.isoformat(), e.intervals, e.open_at_end)
               for e in report.events]
    assert summary == [
        ("F-CLEAN-001", "CLEANING_EVENT", "2026-05-05", "2026-05-05", 1, False),
        ("F-EVT-002", "INVERTER_FAULT", "2026-05-08", "2026-05-09", 2, False),
        ("F-EVT-003", "CURTAILMENT_EVENT", "2026-05-11", "2026-05-11", 1, False),
        ("F-EVT-004", "GRID_OUTAGE", "2026-05-14", "2026-05-14", 1, True),
    ]
    records = {r.reference: r for r in parsed.events}
    assert list(records) == [e.reference for e in report.events]
    fault = records["F-EVT-002"]
    assert fault.evidence_type is EvidenceType.INVERTER_FAULT and fault.resolved is None
    assert fault.observed_end is not None and fault.observed_end > fault.observed_start  # it stopped being reported
    assert "Inverter fault INV-02" in fault.description and "rows 9 to 10" in fault.description
    assert fault.tag.provenance is Provenance.MEASURED and fault.tag.source == "SCADA log"
    assert fault.tag.method == "column 'Alarms' of the imported file"
    assert records["F-EVT-004"].observed_end is None  # still marked on the last row: not closed as far as the file tells
    assert records["F-CLEAN-001"].tag.method == "column 'Cleaning' of the imported file"
    found = issue(report, "EVENTS_FOUND")
    assert found is not None and found.count == 4 and "1 cleaning event" in found.message
    # The event columns are not unmapped columns, and events never became numbers.
    assert not [i for i in report.issues if i.code == "UNMAPPED_COLUMN" and i.column in ("Cleaning", "Alarms")]
    assert {c.metric for c in report.channels} == {Metric.ACTUAL_ENERGY, Metric.EXPECTED_ENERGY}


def test_events_without_a_declared_origin_are_recorded_as_unknown() -> None:
    meta = {**EVENT_META, "events": {"event_column": "Alarms"}}
    report, parsed = validate(support.operator_csv(days=5, alarms={2: "Inverter trip"}), meta)
    assert parsed is not None and parsed.events[0].tag.provenance is Provenance.UNKNOWN
    assert parsed.events[0].tag.source == "origin not declared" and report.events[0].provenance == "UNKNOWN"
    assert any(i.code == "PROVENANCE_NOT_DECLARED" and i.column == "Alarms" for i in report.issues)


@pytest.mark.parametrize(("text", "kind"), [
    ("Inverter fault INV-02", EvidenceType.INVERTER_FAULT), ("INV 3 trip", EvidenceType.INVERTER_FAULT),
    ("Défaut onduleur 4", EvidenceType.INVERTER_FAULT), ("Tracker stuck", EvidenceType.INVERTER_FAULT),
    ("Grid outage 09:10-10:40", EvidenceType.GRID_OUTAGE), ("Coupure réseau", EvidenceType.GRID_OUTAGE),
    ("Curtailment order from the dispatcher", EvidenceType.CURTAILMENT_EVENT), ("Limitation 50 %", EvidenceType.CURTAILMENT_EVENT),
    ("Pyranometer cleaning", EvidenceType.CLEANING_EVENT), ("Nettoyage des modules", EvidenceType.CLEANING_EVENT),
    ("Pyranometer drift", EvidenceType.SENSOR_FAULT), ("Data logger communication lost", EvidenceType.SENSOR_FAULT),
    ("Shading from the new building", EvidenceType.SHADING_OBSERVATION), ("Ombrage partiel", EvidenceType.SHADING_OBSERVATION),
    ("Err 0x21", EvidenceType.OTHER), ("Visit of the owner", EvidenceType.OTHER),
])
def test_how_the_text_of_an_event_is_read(text: str, kind: EvidenceType) -> None:
    assert classify_event(text) is kind


def test_the_vocabulary_names_every_kind_the_engine_acts_on() -> None:
    kinds = {kind for kind, _ in EVENT_VOCABULARY}
    assert kinds == {EvidenceType.CLEANING_EVENT, EvidenceType.CURTAILMENT_EVENT, EvidenceType.GRID_OUTAGE,
                     EvidenceType.SENSOR_FAULT, EvidenceType.SHADING_OBSERVATION, EvidenceType.INVERTER_FAULT}


def test_an_event_that_matches_nothing_is_kept_and_said_not_to_count() -> None:
    report, parsed = validate(support.operator_csv(days=5, alarms={1: "Err 0x21"}), EVENT_META)
    assert parsed is not None and parsed.events[0].evidence_type is EvidenceType.OTHER
    unclassified = issue(report, "EVENT_UNCLASSIFIED")
    assert unclassified.severity.value == "WARNING" and "do not enter the diagnosis" in unclassified.message
    assert unclassified.hint and "vocabulary" in unclassified.hint


@pytest.mark.parametrize("cell", ["", "0", "OK", "ok", "Normal", "none", "No alarm", "-", "n/a", "RAS", "false"])
def test_cells_that_say_nothing_happened_are_not_events(cell: str) -> None:
    _, parsed = validate(support.operator_csv(days=4, alarms=dict.fromkeys(range(4), cell)), EVENT_META)
    assert parsed is not None and parsed.events == []


@pytest.mark.parametrize("mark", ["1", "x", "X", "yes", "Oui", "true", "cleaned", "done"])
def test_what_counts_as_a_cleaning_mark(mark: str) -> None:
    report, parsed = validate(support.operator_csv(days=4, cells={(2, "Cleaning"): mark}), EVENT_META)
    assert parsed is not None and [e.evidence_type for e in parsed.events] == [EvidenceType.CLEANING_EVENT]
    assert report.events[0].first_day == date(2026, 5, 3)


def test_a_cleaning_cell_that_is_not_a_mark_is_reported_not_guessed() -> None:
    report, parsed = validate(support.operator_csv(days=4, cells={(2, "Cleaning"): "maybe"}), EVENT_META)
    assert parsed is not None and parsed.events == []
    assert issue(report, "CLEANING_MARK_NOT_UNDERSTOOD").severity.value == "WARNING"


def test_one_cleaning_record_per_day_whatever_the_interval() -> None:
    text = "timestamp,energy,clean\n" + "".join(f"2026-05-01T{h:02d}:00,100,{'1' if 8 <= h <= 11 else ''}\n" for h in range(6, 18))
    text += "".join(f"2026-05-02T{h:02d}:00,100,{'x' if h == 9 else ''}\n" for h in range(6, 18))
    _, parsed = validate(text, {"name": "x", "channels": ENERGY, "events": {"cleaning_column": "clean"}})
    assert parsed is not None
    assert [e.observed_start.date().isoformat() for e in parsed.events] == ["2026-05-01", "2026-05-02"]


def test_an_alarm_over_consecutive_intervals_is_one_event_and_a_gap_starts_another() -> None:
    hours = {8: "Inverter fault", 9: "Inverter fault", 10: "Inverter fault", 13: "Inverter fault", 14: "Sensor fault"}
    text = "timestamp,energy,alarm\n" + "".join(f"2026-05-01T{h:02d}:00,100,{hours.get(h, '')}\n" for h in range(6, 18))
    report, _ = validate(text, {"name": "x", "channels": ENERGY, "events": {"event_column": "alarm"}})
    assert [(e.evidence_type.value, e.intervals) for e in report.events] == [
        ("INVERTER_FAULT", 3), ("INVERTER_FAULT", 1), ("SENSOR_FAULT", 1),
    ]


def test_a_status_column_is_not_read_as_an_event_log() -> None:
    days = MAX_EVENTS + 20
    first = date(2024, 1, 1).toordinal()
    rows = [f"{date.fromordinal(first + i).isoformat()},100,{'Status A' if i % 2 else 'Status B'}" for i in range(days)]
    text = "timestamp,energy,status\n" + "\n".join(rows) + "\n"
    report, parsed = validate(text, {"name": "x", "channels": ENERGY, "events": {"event_column": "status"}})
    assert parsed is not None and parsed.events == [] and report.events == []
    too_many = issue(report, "TOO_MANY_EVENTS")
    assert too_many.severity.value == "ERROR" and "status column" in too_many.message
    assert report.accepted and report.rows_plant == days  # the measurements are still importable


def test_a_declared_event_column_that_is_not_in_the_file_is_an_error() -> None:
    report, parsed = validate(support.operator_csv(days=3), {**EVENT_META, "events": {"event_column": "Alarm log"}})
    assert parsed is not None and parsed.events == []
    assert any(i.code == "DECLARED_COLUMN_MISSING" and i.column == "Alarm log" for i in report.issues)


def test_the_events_block_is_checked() -> None:
    with pytest.raises(ValueError, match="names no column"):
        EventsDeclaration()
    with pytest.raises(ValueError, match="two different columns"):
        EventsDeclaration(cleaning_column="a", event_column="a")
    with pytest.raises(ValueError, match="only be declared for SYNTHETIC"):
        EventsDeclaration(event_column="a", provenance=Provenance.MEASURED, emulates=Provenance.MEASURED)
    with pytest.raises(ValueError, match="'synthetic' block"):
        DatasetMetadata.model_validate({"name": "x", "events": {"event_column": "a", "provenance": "SYNTHETIC"}})
    declared = DatasetMetadata.model_validate({
        "name": "x", "events": {"event_column": "a", "provenance": "SYNTHETIC", "emulates": "MEASURED"},
        "synthetic": {"generator": "g", "generator_version": "1", "statement": "artificial"},
    })
    assert declared.is_synthetic and declared.events is not None and declared.events.tag("a").label == "SYNTHETIC (emulates MEASURED)"


def test_events_in_a_json_file() -> None:
    records = [{"timestamp": f"2026-05-{d:02d}", "energy": 100.0, "alarm": "Inverter fault" if d == 3 else None,
                "cleaning": d == 2} for d in range(1, 6)]
    table = parse_json(json.dumps({"records": records}).encode())
    meta = {"name": "x", "channels": ENERGY, "events": {"cleaning_column": "cleaning", "event_column": "alarm"}}
    report, parsed = validate("", meta, table=table)
    assert parsed is not None
    assert [(e.evidence_type.value, e.first_day.day) for e in report.events] == [("CLEANING_EVENT", 2), ("INVERTER_FAULT", 3)]


# --------------------------------------------------------------------------- events and the decision


def _analyse(text: str, meta: dict[str, Any]) -> Any:
    report, parsed = validate(text, meta)
    assert parsed is not None and report.accepted
    return run_analysis(
        AnalysisInput(
            plant=PLANT, observations=parsed.observations, interval_minutes=parsed.interval_minutes,
            channels=parsed.channels, context=EvaluationContext.OPERATIONAL, declared_baseline=parsed.baseline,
            records=parsed.events,
            options=AnalysisOptions(cleaning=cleaning_assumptions(), economics=economic_inputs()),
        )
    )


def _measured(meta_events: dict[str, Any] | None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "name": "x", "timestamp_column": "Date",
        "channels": {
            "actual_energy": {"column": "Energy (kWh)", "provenance": "MEASURED", "source": "meter", "uncertainty_pct": 0.5,
                              "boundary": "GRID_METER"},
            "expected_energy": {"column": "Expected production (kWh)", "provenance": "MODELLED", "source": "model",
                                "uncertainty_pct": 2.0, "boundary": "GRID_METER"},
            "soiling_ratio": {"column": "Soiling loss (%)", "unit": "percent", "reported_as": "LOSS", "provenance": "MEASURED",
                              "source": "soiling station", "uncertainty_abs": 0.005, "soiling_method": "SOILING_STATION"},
        },
        "baseline": {"method": "TELEMETRY_MODEL", "irradiance_adjusted": True, "temperature_adjusted": True,
                     "degradation_adjusted": True, "soiling_allowance_fraction": 0.0},
    }
    if meta_events is not None:
        meta["events"] = meta_events
    return meta


@pytest.mark.safety
def test_a_logged_fault_can_only_make_the_engine_more_cautious() -> None:
    """Measured soiling that explains the gap: CLEAN_NOW.  The same file with an open inverter alarm: not CLEAN_NOW."""
    events = {"cleaning_column": "Cleaning", "event_column": "Alarms", "provenance": "MEASURED", "source": "SCADA log"}
    clean = _analyse(support.operator_csv(), _measured(events))
    assert clean.recommendation.decision.value == "CLEAN_NOW" and clean.recommendation.operational_authorization is True

    with_fault = _analyse(support.operator_csv(alarms={28: "Inverter fault INV-02", 29: "Inverter fault INV-02"}), _measured(events))
    assert with_fault.recommendation.decision.value == "INVESTIGATE" and with_fault.recommendation.rule == "R1"
    assert with_fault.recommendation.operational_authorization is False
    assert with_fault.diagnostics.unresolved_technical_issue is True

    # An alarm of unknown origin is just as much a reason to look before cleaning.
    unknown = _analyse(support.operator_csv(alarms={29: "Inverter trip"}), _measured({"event_column": "Alarms"}))
    assert unknown.recommendation.decision.value == "INVESTIGATE"


@pytest.mark.safety
def test_no_event_can_produce_a_cleaning_decision() -> None:
    """Without a soiling measurement nothing in an event column leads to CLEAN_NOW - not even 'cleaning needed'."""
    meta = _measured({"cleaning_column": "Cleaning", "event_column": "Alarms", "provenance": "MEASURED", "source": "log"})
    del meta["channels"]["soiling_ratio"]
    for alarms in ({}, {29: "Soiling alarm: clean now"}, {29: "Dust storm"}, {20: "Cleaning needed", 29: "Cleaning needed"}):
        result = _analyse(support.operator_csv(alarms=alarms, cleaned=(3,)), meta)
        assert result.recommendation.decision.value != "CLEAN_NOW", alarms
        assert result.recommendation.operational_authorization is False


@pytest.mark.safety
def test_an_event_the_vocabulary_does_not_know_changes_nothing() -> None:
    events = {"event_column": "Alarms", "provenance": "MEASURED", "source": "log"}
    plain = _analyse(support.operator_csv(), _measured(events))
    noted = _analyse(support.operator_csv(alarms={29: "Err 0x21"}), _measured(events))
    assert noted.recommendation.decision == plain.recommendation.decision
    assert noted.recommendation.rule == plain.recommendation.rule


# --------------------------------------------------------------------------- rejections and hints


def test_every_rejected_cell_and_row_is_collected_with_its_row_number() -> None:
    text = support.operator_csv(days=8, cells={
        (0, "Date"): "not a date", (1, "Energy (kWh)"): "abc", (2, "Energy (kWh)"): "-40", (3, "Soiling loss (%)"): "250",
        (5, "Date"): "2026-05-05",  # the same day as row 6 (index 4), with other values further down
        (5, "Energy (kWh)"): "1",
    })
    meta = {
        "name": "x", "timestamp_column": "Date",
        "channels": {"actual_energy": {"column": "Energy (kWh)"},
                     "soiling_ratio": {"column": "Soiling loss (%)", "unit": "percent", "reported_as": "LOSS"}},
    }
    rejections: list[Rejection] = []
    report, parsed = validate(text, meta, rejections=rejections)
    assert parsed is not None
    found = sorted((r.row, r.column, r.code) for r in rejections)
    assert found == [
        (2, "Date", "INVALID_TIMESTAMP"), (3, "Energy (kWh)", "NON_NUMERIC"), (4, "Energy (kWh)", "NEGATIVE_VALUE"),
        (5, "Soiling loss (%)", "OUT_OF_RANGE"), (6, "Date", "CONFLICTING_DUPLICATES"), (7, "Date", "CONFLICTING_DUPLICATES"),
    ]
    assert report.rejections_total == len(rejections) == 6
    assert report.rows_rejected == 3 and report.values_rejected == 3
    assert {r.value for r in rejections if r.code == "NON_NUMERIC"} == {"abc"}
    # Without a collector the report says the same; nothing is kept in memory.
    again, _ = validate(text, meta)
    assert again.rejections_total == 6 and again.model_dump(exclude={"issues"}) == report.model_dump(exclude={"issues"})


def test_issues_say_what_to_do_about_them() -> None:
    text = support.operator_csv(days=4, cells={(1, "Energy (kWh)"): "abc", (2, "Date"): "??"})
    report, _ = validate(text, {"name": "x", "timestamp_column": "Date", "channels": {"actual_energy": {"column": "Energy (kWh)"}}})
    hints = {i.code: i.hint for i in report.issues}
    assert hints["NON_NUMERIC"] == ISSUE_HINTS["NON_NUMERIC"] and "leave them empty" in (hints["NON_NUMERIC"] or "")
    assert hints["INVALID_TIMESTAMP"] and hints["PROVENANCE_NOT_DECLARED"]
    assert all(hint is None or hint[0].isupper() for hint in hints.values())
    assert report.model_dump(mode="json")["issues"][0].keys() >= {"code", "severity", "message", "hint", "examples"}


def test_a_report_stored_before_these_fields_existed_is_still_read() -> None:
    report, _ = validate(support.operator_csv(days=3), {"name": "x", "timestamp_column": "Date",
                                                        "channels": {"actual_energy": {"column": "Energy (kWh)"}}})
    old = report.model_dump(mode="json")
    del old["events"], old["rejections_total"]
    for item in old["issues"]:
        del item["hint"]
    restored = ValidationReport.model_validate(old)
    assert restored.events == [] and restored.rejections_total == 0 and restored.issues[0].hint is None
