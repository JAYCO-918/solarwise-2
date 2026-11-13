"""A model may suggest how to read a file.  It may not read it for the uploader, and it may not touch a value."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from solarwise.ai.data_assist import (
    DATA_REVIEW_SYSTEM_PROMPT,
    NOTICE_AI,
    NOTICE_ENGINE,
    NOTICE_FALLBACK,
    review_data,
    review_packet,
)
from solarwise.ai.providers import ProviderError
from solarwise.core.models import Metric
from solarwise.ingestion.detect import ColumnRole, UploadPreview, preview_table
from solarwise.ingestion.parser import parse_csv
from tests.builders import PLANT

pytestmark = pytest.mark.safety

#: A file whose headers the deterministic reader cannot place: a site's own abbreviations.
SITE_EXPORT = (
    "Date,Prod,Ref,G_incl,T1,T2,HR,Rem\n"
    + "".join(f"2026-05-{d:02d},46000,50000,6.4,44.5,27.1,21,{'INV-02 trip' if d == 9 else ''}\n" for d in range(1, 15))
)


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


def site_preview() -> UploadPreview:
    return preview_table(parse_csv(SITE_EXPORT.encode()), plant=PLANT)


GOOD: dict[str, Any] = {
    "suggestions": [
        {"column": "Prod", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh",
         "reason": "Prod reads as the production of the plant, and the values fit its capacity in kWh per day."},
        {"column": "Ref", "role": "QUANTITY", "metric": "expected_energy", "unit": "kWh",
         "reason": "Ref reads as the reference production, slightly above Prod on every row."},
        {"column": "G_incl", "role": "QUANTITY", "metric": "poa_irradiation", "unit": "kWh/m2",
         "reason": "G_incl reads as the irradiation in the inclined plane, and 6.4 fits a daily value in kWh/m2."},
        {"column": "T1", "role": "QUANTITY", "metric": "module_temp", "unit": "degC", "reason": "The warmer of the two temperatures."},
        {"column": "T2", "role": "QUANTITY", "metric": "ambient_temp", "unit": "degC", "reason": "The cooler of the two temperatures."},
        {"column": "Rem", "role": "EVENTS", "reason": "Rem holds remarks such as an inverter trip."},
    ],
    "observations": [{"column": "Prod", "text": "Prod is 46000 on every row, which is unusual for a real series."}],
    "missing_context": ["Whether T1 is the module temperature should be confirmed on site."],
}


def test_the_deterministic_reader_leaves_this_file_mostly_unmapped() -> None:
    preview = site_preview()
    assert preview.proposal.timestamp_column == "Date"
    assert set(preview.proposal.channels) == {Metric.RELATIVE_HUMIDITY}
    assert {c.name for c in preview.columns if c.role is ColumnRole.UNUSED} == {"Prod", "Ref", "G_incl", "T1", "T2", "Rem"}


def test_the_model_is_given_names_statistics_and_samples_never_the_file() -> None:
    preview = site_preview()
    packet = review_packet(preview, PLANT)
    prod = next(c for c in packet["columns"] if c["name"] == "Prod")
    assert prod["samples"] == ["46000"] and prod["minimum"] == prod["maximum"] == 46000.0 and prod["filled"] == 14
    assert all(len(c["samples"]) <= 5 for c in packet["columns"])
    assert "2026-05-07" not in json.dumps(packet)  # the eighth row and after are not in what is sent
    assert {q["metric"] for q in packet["quantities"]} >= {"actual_energy", "soiling_ratio", "poa_irradiation"}
    irradiation = next(q for q in packet["quantities"] if q["metric"] == "poa_irradiation")
    assert "w/m2" in irradiation["accepted_units"]
    assert "provenance" not in json.dumps(packet).lower()


def test_checked_suggestions_are_returned_and_nothing_is_applied() -> None:
    preview = site_preview()
    before = copy.deepcopy(preview)
    provider = FakeProvider(GOOD)
    review = review_data(preview, PLANT, provider)
    assert review.generated_by == "AI" and review.provider == "fake" and review.notice == NOTICE_AI
    assert [(s.column, s.role.value, s.metric.value if s.metric else None, s.unit) for s in review.suggestions] == [
        ("Prod", "QUANTITY", "actual_energy", "kWh"), ("Ref", "QUANTITY", "expected_energy", "kWh"),
        ("G_incl", "QUANTITY", "poa_irradiation", "kWh/m2"), ("T1", "QUANTITY", "module_temp", "degC"),
        ("T2", "QUANTITY", "ambient_temp", "degC"), ("Rem", "EVENTS", None, None),
    ]
    assert review.suggestions[0].current.role == "UNUSED" and review.suggestions[0].current.metric is None
    assert [o.column for o in review.observations] == ["Prod"] and len(review.missing_context) == 1
    assert review.discarded == []
    assert preview == before  # the proposal the uploader sees is untouched: a suggestion is only a suggestion
    system, user = provider.calls[0]
    assert system == DATA_REVIEW_SYSTEM_PROMPT and json.loads(user) == review_packet(preview, PLANT)


DISCARDED: list[tuple[str, dict[str, Any], str]] = [
    ("a column that is not in the file", {"column": "Energy", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh"},
     "no such column"),
    ("a quantity that does not exist", {"column": "Prod", "role": "QUANTITY", "metric": "power_factor", "unit": "kWh"},
     "unknown quantity"),
    ("a role that does not exist", {"column": "Prod", "role": "PRODUCTION"}, "unknown role"),
    ("a unit of another quantity", {"column": "Prod", "role": "QUANTITY", "metric": "actual_energy", "unit": "degC"},
     "is not a unit of actual energy"),
    ("a unit that does not exist", {"column": "Prod", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh/kWp"},
     "unknown unit"),
    ("a text column proposed as a quantity", {"column": "Rem", "role": "QUANTITY", "metric": "soiling_ratio", "unit": "fraction"},
     "no cell of the column is a number"),
    ("a device-level quantity", {"column": "Prod", "role": "QUANTITY", "metric": "device_energy", "unit": "kWh"},
     "cannot be assigned"),
    ("what the reader already proposes", {"column": "HR", "role": "QUANTITY", "metric": "relative_humidity", "unit": "percent"},
     "the same as the reader's proposal"),
    ("a provenance", {"column": "Prod", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh",
                      "reason": "This column is measured by the revenue meter."}, "says where the data come from"),
    ("a change of values", {"column": "Prod", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh",
                            "reason": "Replace the missing values by zero before importing."}, "proposes to change values"),
    ("a link", {"column": "Prod", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh",
                "reason": "See https://example.org for the meaning of Prod."}, "link"),
]


@pytest.mark.parametrize(("what", "suggestion", "reason"), DISCARDED, ids=[d[0] for d in DISCARDED])
def test_a_suggestion_that_fails_a_check_is_discarded_and_reported(what: str, suggestion: dict[str, Any], reason: str) -> None:
    review = review_data(site_preview(), PLANT, FakeProvider({"suggestions": [suggestion, GOOD["suggestions"][1]]}))
    assert review.generated_by == "AI"
    assert [s.column for s in review.suggestions] == ["Ref"], what  # the sound one is kept
    assert len(review.discarded) == 1 and reason in review.discarded[0]


def test_two_suggestions_for_one_role_or_one_column_keep_the_first() -> None:
    answer = {"suggestions": [
        GOOD["suggestions"][0],
        {"column": "Ref", "role": "QUANTITY", "metric": "actual_energy", "unit": "kWh", "reason": "Could also be the production."},
        {"column": "Prod", "role": "QUANTITY", "metric": "expected_energy", "unit": "kWh", "reason": "Or the reference."},
    ]}
    review = review_data(site_preview(), PLANT, FakeProvider(answer))
    assert [(s.column, s.metric) for s in review.suggestions] == [("Prod", Metric.ACTUAL_ENERGY)]
    assert len(review.discarded) == 2


def test_a_soiling_loss_may_be_suggested_and_a_unit_defaults_to_the_stored_one() -> None:
    text = "Date,Energy (kWh),SL\n" + "".join(f"2026-05-{d:02d},46000,{d * 0.4:.1f}\n" for d in range(1, 11))
    preview = preview_table(parse_csv(text.encode()), plant=PLANT)
    answer = {"suggestions": [{"column": "SL", "role": "QUANTITY", "metric": "soiling_ratio", "unit": "percent",
                               "reported_as": "LOSS", "reason": "SL grows from near zero, like a soiling loss in percent."}]}
    suggestion = review_data(preview, PLANT, FakeProvider(answer)).suggestions[0]
    assert (suggestion.metric, suggestion.unit, suggestion.reported_as) == (Metric.SOILING_RATIO, "percent", "LOSS")
    no_unit = {"suggestions": [{"column": "SL", "role": "QUANTITY", "metric": "soiling_ratio", "reason": "A soiling figure."}]}
    suggestion = review_data(preview, PLANT, FakeProvider(no_unit)).suggestions[0]
    assert suggestion.unit == "fraction" and suggestion.reported_as == "RATIO"


def test_observations_may_only_quote_what_is_in_the_summary() -> None:
    answer = {"observations": [
        {"column": "Prod", "text": "Prod is 46000 on every one of the 14 rows."},
        {"column": "Prod", "text": "About 37 % of the values of Prod are outliers."},
        {"column": "Ghost", "text": "The file has no soiling column at all."},
        {"column": None, "text": "These values are synthetic data, not real ones."},
        {"column": None, "text": "Interpolate the missing values before the import."},
    ]}
    review = review_data(site_preview(), PLANT, FakeProvider(answer))
    assert [(o.column, o.text[:22]) for o in review.observations] == [
        ("Prod", "Prod is 46000 on every"), (None, "The file has no soilin"),
    ]
    assert len(review.discarded) == 3
    assert any("figures that are not in the file summary (37)" in d for d in review.discarded)
    assert any("says where the data come from" in d for d in review.discarded)
    assert any("proposes to change values" in d for d in review.discarded)


def test_the_number_of_suggestions_is_bounded() -> None:
    header = "Date," + ",".join(f"c{i}" for i in range(20))
    text = header + "\n" + "".join(f"2026-05-{d:02d}," + ",".join("1" for _ in range(20)) + "\n" for d in range(1, 4))
    preview = preview_table(parse_csv(text.encode()), plant=PLANT)
    answer = {"suggestions": [{"column": f"c{i}", "role": "UNUSED", "reason": "Not needed."} for i in range(20)]}
    review = review_data(preview, PLANT, FakeProvider(answer))
    assert review.suggestions == [] and len(review.discarded) == 20  # UNUSED is what the reader already says


@pytest.mark.parametrize("answer", ["I would map Prod to the energy.", "", json.dumps([1, 2]), json.dumps({"suggestions": "all of them"}),
                                    json.dumps({"suggestions": [{"role": "QUANTITY"}]})])
def test_an_answer_that_is_not_the_requested_structure_leaves_the_reading_as_it_was(answer: str) -> None:
    review = review_data(site_preview(), PLANT, FakeProvider(answer))
    assert review.generated_by == "DETERMINISTIC_ENGINE" and review.notice == NOTICE_FALLBACK
    assert review.fallback_reason is not None and review.fallback_reason.startswith("the model's answer was not usable")
    assert review.suggestions == [] and review.observations == []


def test_without_a_model_or_with_one_that_fails_the_deterministic_reading_stands() -> None:
    none = review_data(site_preview(), PLANT, None)
    assert none.generated_by == "DETERMINISTIC_ENGINE" and none.notice == NOTICE_ENGINE and none.fallback_reason is None
    assert none.provider is None and none.suggestions == []
    failed = review_data(site_preview(), PLANT, FakeProvider(ProviderError("the language-model provider did not answer within the time limit", kind="TIMEOUT")))
    assert failed.generated_by == "DETERMINISTIC_ENGINE" and "time limit" in (failed.fallback_reason or "")
    assert failed.provider == "fake" and failed.suggestions == []


def test_an_empty_answer_is_a_valid_answer() -> None:
    review = review_data(site_preview(), PLANT, FakeProvider({"suggestions": [], "observations": [], "missing_context": []}))
    assert review.generated_by == "AI" and review.suggestions == [] and review.discarded == []
