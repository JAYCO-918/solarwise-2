"""Reports: built from the stored result only, complete, and honest about what the result is."""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import UTC, datetime
from functools import cache

import pytest

from solarwise.core.pipeline import AnalysisResult, run_analysis
from solarwise.core.provenance import EvaluationContext
from solarwise.demo.run import run_scenario
from solarwise.demo.scenarios import build_scenario
from solarwise.reports import ReportMeta, build_document, render_csv, render_html, render_json, render_pdf
from tests.builders import PLANT, make_case, soiled_case

META = ReportMeta(analysis_id=7, dataset_name="Artificial dataset", dataset_sha256="ab" * 32,
                  created_at=datetime(2026, 7, 1, 8, 30, tzinfo=UTC), created_by="Test Engineer")


@cache
def scenario(key: str) -> AnalysisResult:
    return run_scenario(build_scenario(key), EvaluationContext.DEMONSTRATION)


@cache
def operational_clean_now() -> AnalysisResult:
    return run_analysis(soiled_case())


def visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


# --------------------------------------------------------------------------- content


def test_operational_report_states_the_decision_without_any_simulation_marking() -> None:
    document = build_document(operational_clean_now(), META)
    assert document.simulated is False and "SIMULATED" not in document.banner
    assert document.banner.startswith("Operational recommendation")
    assert document.decision == "CLEAN_NOW" and document.decision_label == "Clean now"
    assert "Operational recommendation based on measured evidence" in document.authorization_note
    html = render_html(document)
    assert "SIMULATED" not in html
    text = visible_text(html)
    assert "Test plant" in text and "Artificial dataset" in text and "abab" in text and "Test Engineer" in text


@pytest.mark.safety
@pytest.mark.parametrize("key", ["S01_normal_operation", "S02_confirmed_soiling", "S05_shading", "S07_missing_data"])
def test_every_demonstration_report_is_marked_simulated_in_all_formats(key: str) -> None:
    result = scenario(key)
    document = build_document(result, META)
    assert document.simulated and document.banner.startswith("SIMULATED DECISION")
    html = render_html(document)
    assert html.count("SIMULATED DECISION") >= 2  # banner and headline
    assert "SYNTHETIC" in html
    assert "SIMULATED DECISION" in render_csv(result, META)
    assert json.loads(render_json(result, META))["report"]["marking"].startswith("SIMULATED DECISION")
    assert render_pdf(document).startswith(b"%PDF-")


def test_report_shows_gates_attribution_assumptions_provenance_and_rule() -> None:
    result = scenario("S02_confirmed_soiling")
    document = build_document(result, META)
    tables = {t.title: t for t in document.tables}
    assert len(tables["Decision gates"].rows) == 10
    assert {row[1] for row in tables["Decision gates"].rows} == {"passed"}
    assert tables["Loss attribution over the period"].rows
    assumptions = {row[0]: row for row in tables["Assumptions used"].rows}
    assert assumptions["Cleaning effectiveness"][2] == "User Assumption"
    assert assumptions["Measured soiling loss"][2] == "Derived From Data"
    assert "not a market price" in assumptions["Energy value"][3]
    provenance_rows = tables["Provenance of the data"].rows
    assert provenance_rows and all("SYNTHETIC" in row[1] for row in provenance_rows)
    assert "rule R3" in document.footer
    economics = tables["Economics of one cleaning (DZD)"]
    assert [row[0] for row in economics.rows] == ["Conservative", "Base", "Optimistic"]
    assert economics.note is not None and "Verdict: Profitable" in economics.note and "Decision grade: yes" in economics.note
    assert len(tables["Recoverable energy"].rows) == 9


def test_report_of_a_refused_decision_lists_the_failed_gates_and_what_is_missing() -> None:
    result = scenario("S07_missing_data")
    document = build_document(result, META)
    gates = next(t for t in document.tables if t.title == "Decision gates")
    assert any(row[1] != "passed" for row in gates.rows)
    text = visible_text(render_html(document))
    assert "Investigate" in text and "not sufficient" in text
    assert "What would change this decision" in text


@pytest.mark.safety
def test_no_confidence_percentage_appears_in_a_report() -> None:
    for key in ("S02_confirmed_soiling", "S05_shading", "S08_conflicting_evidence"):
        text = visible_text(render_html(build_document(scenario(key), META))).lower()
        assert not re.search(r"\d+(\.\d+)?\s*%\s*(confidence|confident|certain|probab|likel)", text)
        assert not re.search(r"(confidence|probability|likelihood)\s*(of|:|is)?\s*\d+(\.\d+)?\s*%", text)


@pytest.mark.safety
def test_missing_figures_are_printed_as_not_available_never_as_zero() -> None:
    result = run_analysis(make_case(true_soiling_ratio=0.92, cleaning=None, economics=None))
    document = build_document(result, META)
    economics = next(b for b in document.blocks if b.title == "Economics")
    text = " ".join(economics.paragraphs + economics.bullets)
    assert "not available" in text or "Missing" in text or "missing" in text
    assert "0 DZD" not in text


# --------------------------------------------------------------------------- rendering


@pytest.mark.safety
def test_html_escapes_every_piece_of_free_text() -> None:
    hostile = PLANT.model_copy(update={"name": '"><script>alert(document.cookie)</script><b onmouseover=x>'})
    result = run_analysis(soiled_case(plant=hostile))
    meta = ReportMeta(analysis_id=1, dataset_name="<img src=x onerror=alert(1)>", dataset_sha256=None,
                      created_at=META.created_at, created_by="<svg/onload=alert(1)>")
    html = render_html(build_document(result, meta))
    assert "<script" not in html.lower() and "<img" not in html.lower() and "<svg" not in html.lower()
    assert "onmouseover=x>" not in html.replace("&gt;", ">") or "&lt;b onmouseover" in html
    assert "&lt;script&gt;alert(document.cookie)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_html_is_self_contained() -> None:
    html = render_html(build_document(scenario("S02_confirmed_soiling"), META))
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert not re.search(r"""(src|href)\s*=\s*["']https?://""", html), "no remote resources"
    assert "<script" not in html.lower() and "@import" not in html and "url(http" not in html


def test_pdf_is_a_complete_multi_page_document() -> None:
    pdf = render_pdf(build_document(scenario("S02_confirmed_soiling"), META))
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf))
    assert pages >= 3
    assert len(pdf) > 20_000


def test_pdf_survives_hostile_and_non_latin_text() -> None:
    plant = PLANT.model_copy(update={"name": "Centrale d'El Foulia <b>&amp; محطة الفولية</b> </para><font size=99>"})
    pdf = render_pdf(build_document(run_analysis(soiled_case(plant=plant)), META))
    assert pdf.startswith(b"%PDF-")


def test_csv_has_one_row_per_day_and_empty_cells_for_missing_values() -> None:
    result = run_analysis(soiled_case(days=20, missing_actual_days=(4, 5)))
    rows = [row for row in csv.reader(io.StringIO(render_csv(result, META))) if row and not row[0].startswith("#")]
    header, data = rows[0], rows[1:]
    assert len(data) == 20
    index = {name: i for i, name in enumerate(header)}
    assert data[4][index["actual_energy_kwh"]] == "" and data[5][index["actual_energy_kwh"]] == ""
    # A day without both values is left out of the comparison altogether: nothing is computed for it.
    assert data[4][index["gap_kwh"]] == "" and data[4][index["status"]] == "MISSING"
    assert data[4][index["performance_index_pct"]] == "" and data[4][index["data_coverage"]] == "0.000"
    assert data[3][index["expected_energy_kwh"]] == "50000.000" and data[3][index["status"]] == "OK"
    assert data[0][index["actual_energy_kwh"]] == "46000.000"
    assert {row[index["actual_provenance"]] for row in data} == {"MEASURED"}
    assert {row[index["decision_simulated"]] for row in data} == {"false"}
    assert any("not zeros" in line for line in render_csv(result, META).splitlines() if line.startswith(('"#', "#")))


def test_json_export_is_strict_json_and_round_trips() -> None:
    result = scenario("S04_inverter_fault")
    text = render_json(result, META)
    assert "NaN" not in text and "Infinity" not in text
    document = json.loads(text)
    assert document["report"]["format"] == "solarwise-analysis" and document["report"]["analysis_id"] == 7
    assert AnalysisResult.model_validate(document["result"]).model_dump() == result.model_dump()


def test_reports_are_deterministic() -> None:
    result = scenario("S02_confirmed_soiling")
    assert render_html(build_document(result, META)) == render_html(build_document(result, META))
    assert render_csv(result, META) == render_csv(result, META)
    assert render_json(result, META) == render_json(result, META)
