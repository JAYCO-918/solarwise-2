"""The operational report: eight sections, each saying who wrote it; the engine's decision and tables untouched."""

from __future__ import annotations

import html as html_module
import json
import re
from datetime import UTC, datetime
from functools import cache

import pytest

from solarwise.ai import build_operational_report, deterministic_insight, generate_insight, render_operational_json
from solarwise.ai.report import narrative_source
from solarwise.core.models import PlantSpec
from solarwise.core.pipeline import AnalysisResult, run_analysis
from solarwise.core.provenance import EvaluationContext
from solarwise.demo.run import run_scenario
from solarwise.demo.scenarios import SCENARIO_KEYS, build_scenario
from solarwise.reports import ReportMeta, build_document, render_html, render_pdf
from tests.ai.answers import FAITHFUL_S05, faithful
from tests.builders import soiled_case

META = ReportMeta(analysis_id=7, dataset_name="Artificial dataset", dataset_sha256="ab" * 32,
                  created_at=datetime(2026, 7, 1, 8, 30, tzinfo=UTC), created_by="Test Engineer")
NOW = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
SECTIONS = [
    "1. Executive summary", "2. Plant performance overview", "3. Main detected anomalies",
    "4. Evidence-based diagnostic analysis", "5. Data-quality assessment", "6. Economic implications",
    "7. Recommended actions", "8. Limitations and uncertainty",
]


class FakeProvider:
    name = "openai-compatible"
    model = "example-model"

    def __init__(self, answer: str) -> None:
        self.answer = answer

    def complete(self, system: str, user: str) -> str:
        return self.answer


@cache
def scenario(key: str) -> AnalysisResult:
    return run_scenario(build_scenario(key), EvaluationContext.DEMONSTRATION)


def visible_text(html: str) -> str:
    body = html[html.index("<body>"):]
    return html_module.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


def test_the_eight_sections_are_there_in_order_whoever_wrote_the_narrative() -> None:
    result = scenario("S05_shading")
    for insight in (deterministic_insight(result, now=NOW), generate_insight(result, FakeProvider(faithful()), now=NOW)):
        document = build_operational_report(result, insight, META)
        assert [b.title for b in document.blocks] == SECTIONS
        assert document.title == "SolarWise DZ - operational report" and document.tables_title == "Annex - the engine's figures"
        assert document.hypotheses == [] and document.explanation == []
        text = visible_text(render_html(document))
        positions = [text.index(section) for section in SECTIONS]
        assert positions == sorted(positions)
        assert text.index("8. Limitations and uncertainty") < text.index("Annex - the engine's figures") < text.index("Decision gates")


def test_the_decision_box_and_the_annex_are_the_engines_in_both_cases() -> None:
    result = scenario("S05_shading")
    analysis_report = build_document(result, META)
    for insight in (deterministic_insight(result, now=NOW), generate_insight(result, FakeProvider(faithful()), now=NOW)):
        document = build_operational_report(result, insight, META)
        for name in ("simulated", "banner", "decision", "decision_label", "headline", "authorization_note", "key_figures",
                     "disclaimers"):
            assert getattr(document, name) == getattr(analysis_report, name), name
        by_title = {t.title: t for t in analysis_report.tables}
        assert document.tables and all(t == by_title[t.title] for t in document.tables)
        assert {"Decision gates", "Loss attribution over the period", "Provenance of the data", "Data quality"} <= {
            t.title for t in document.tables
        }


def test_a_report_written_by_the_engine_says_no_model_was_used() -> None:
    result = scenario("S05_shading")
    insight = deterministic_insight(result, now=NOW)
    document = build_operational_report(result, insight, META)
    assert narrative_source(insight) == "engine text, no language model"
    assert document.notice is not None and document.notice.startswith("How this report was written. No language model was used")
    assert {b.label for b in document.blocks} <= {"engine text, no language model", "engine"}
    text = visible_text(render_html(document))
    assert "No language model was used" in text and "language model example-model" not in text
    assert ("Narrative written by", "engine text, no language model") in document.facts


def test_a_report_written_with_a_model_names_it_and_marks_each_section() -> None:
    result = scenario("S05_shading")
    insight = generate_insight(result, FakeProvider(faithful()), now=NOW)
    assert insight.generated_by == "AI"
    document = build_operational_report(result, insight, META)
    assert document.notice is not None and "language model (openai-compatible, model example-model)" in document.notice
    assert "on 2026-07-02 09:00 UTC" in document.notice and "the model could not change them" in document.notice
    labels = {b.title: b.label for b in document.blocks}
    assert labels["1. Executive summary"] == "language model example-model"
    assert labels["4. Evidence-based diagnostic analysis"] == "support and evidence: engine; interpretation: language model example-model"
    assert labels["7. Recommended actions"] == "steps: engine; reasons: language model example-model"
    text = visible_text(render_html(document))
    assert FAITHFUL_S05["executive_summary"] in text
    assert "SIMULATED DECISION (demonstration, not an operational instruction): Investigate." in text
    shading = next(c for b in document.blocks for c in b.children if c.title.startswith("Shading"))
    assert shading.title == "Shading - moderate support - present in the assessment window"
    assert shading.paragraphs[0].startswith("Engine: ") and shading.paragraphs[1].startswith("Interpretation (language model example-model): ")
    assert any(b.startswith("Missing evidence: ") for b in shading.bullets)
    actions = next(b for b in document.blocks if b.title == "7. Recommended actions")
    steps = next(c for c in actions.children if c.title == "Next steps, in order")
    assert " Why: " in steps.bullets[0] and " Why: " not in steps.bullets[-1]
    gates = next(c for c in actions.children if c.title == "Gates behind the decision")
    assert gates.label == "engine" and gates.paragraphs == ["5 of 10 gates are passed. Clean now requires every gate."]
    assert sum(1 for b in gates.bullets if b.startswith("NOT passed: ")) == 4
    assert ("Evidence packet (SHA-256)", insight.packet_sha256) in document.facts


def test_a_rejected_answer_is_named_in_the_report_and_not_one_sentence_of_it_is_printed() -> None:
    result = scenario("S05_shading")
    rogue = faithful(executive_summary="The loss is caused by soiling: the modules are dirty and should be washed at once.")
    insight = generate_insight(result, FakeProvider(rogue), now=NOW)
    document = build_operational_report(result, insight, META)
    text = visible_text(render_html(document))
    assert "A language model was asked, but its answer could not be used" in text
    assert "soiling_not_asserted_without_measurement" in text
    assert "should be washed at once" not in text and "the modules are dirty" not in text
    assert result.explanation.summary in text


@pytest.mark.parametrize("key", SCENARIO_KEYS)
def test_every_scenario_renders_in_html_pdf_and_json_marked_simulated(key: str) -> None:
    result = scenario(key)
    insight = deterministic_insight(result, now=NOW)
    document = build_operational_report(result, insight, META)
    html = render_html(document)
    assert "SIMULATED DECISION" in html and "<script" not in html.lower() and "http://" not in html and "https://" not in html
    pdf = render_pdf(document)
    assert pdf.startswith(b"%PDF") and len(pdf) > 15_000
    envelope = json.loads(render_operational_json(result, insight, META))
    assert envelope["report"]["simulated"] is True and envelope["report"]["operational_authorization"] is False
    assert envelope["report"]["marking"] == "SIMULATED DECISION - not an operational instruction"
    assert envelope["insight"]["decision"]["value"] == result.recommendation.decision.value


def test_an_operational_report_carries_no_simulation_marking() -> None:
    result = run_analysis(soiled_case())
    insight = deterministic_insight(result, now=NOW)
    document = build_operational_report(result, insight, META)
    text = visible_text(render_html(document))
    assert "SIMULATED" not in text and "Decision of the engine: Clean now." in text
    assert "The engine estimates a recoverable energy" in text
    envelope = json.loads(render_operational_json(result, insight, META))
    assert envelope["report"]["simulated"] is False and envelope["report"]["marking"] is None
    assert envelope["report"]["operational_authorization"] is True


def test_the_pdf_is_a_complete_multi_page_document() -> None:
    result = scenario("S02_confirmed_soiling")
    document = build_operational_report(result, deterministic_insight(result, now=NOW), META)
    pdf = render_pdf(document)
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type\s*/Page[^s]", pdf)) >= 4 and len(pdf) > 30_000
    assert pdf != render_pdf(build_document(result, META))  # another document than the analysis report


def test_free_text_is_escaped_in_the_report() -> None:
    case = soiled_case()
    case.plant = PlantSpec.model_validate({**case.plant.model_dump(), "name": '<img src=x onerror=alert(1)> & "Plant"'})
    result = run_analysis(case)
    html = render_html(build_operational_report(result, deterministic_insight(result, now=NOW), META))
    assert "<img" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html


def test_the_report_is_the_same_for_the_same_insight() -> None:
    result = scenario("S05_shading")
    insight = deterministic_insight(result, now=NOW)
    first = render_html(build_operational_report(result, insight, META))
    assert first == render_html(build_operational_report(result, insight, META))
    assert render_operational_json(result, insight, META) == render_operational_json(result, insight, META)
