"""Provenance: classes, propagation, and what counts as evidence in which context."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from solarwise.core.provenance import (
    UNKNOWN_TAG,
    EvaluationContext,
    Provenance,
    ProvenanceTag,
    derive,
    measured,
    modelled,
    synthetic,
    weakest_effective_class,
)

OPERATIONAL = EvaluationContext.OPERATIONAL
DEMO = EvaluationContext.DEMONSTRATION


def test_labels() -> None:
    assert measured("meter").label == "MEASURED"
    assert modelled("PVGIS").label == "MODELLED"
    assert synthetic("generator").label == "SYNTHETIC"
    assert synthetic("generator", emulates=Provenance.MEASURED).label == "SYNTHETIC (emulates MEASURED)"
    assert UNKNOWN_TAG.label == "UNKNOWN"


def test_synthetic_data_is_always_flagged_synthetic() -> None:
    assert synthetic("generator", emulates=Provenance.MEASURED).is_synthetic
    assert not measured("meter").is_synthetic


@pytest.mark.safety
def test_synthetic_never_counts_as_measured_in_operation() -> None:
    tag = synthetic("generator", emulates=Provenance.MEASURED)
    assert tag.effective_class(OPERATIONAL) is Provenance.SYNTHETIC
    assert tag.effective_class(DEMO) is Provenance.MEASURED


@pytest.mark.safety
def test_plain_synthetic_counts_as_synthetic_even_in_a_demonstration() -> None:
    assert synthetic("generator").effective_class(DEMO) is Provenance.SYNTHETIC


def test_real_classes_are_unaffected_by_context() -> None:
    for context in (OPERATIONAL, DEMO):
        assert measured("meter").effective_class(context) is Provenance.MEASURED
        assert modelled("model").effective_class(context) is Provenance.MODELLED
        assert UNKNOWN_TAG.effective_class(context) is Provenance.UNKNOWN


def test_only_synthetic_data_may_declare_an_emulated_class() -> None:
    with pytest.raises(ValidationError):
        ProvenanceTag(provenance=Provenance.MEASURED, emulates=Provenance.MEASURED, source="x")
    with pytest.raises(ValidationError):
        ProvenanceTag(provenance=Provenance.SYNTHETIC, emulates=Provenance.SYNTHETIC, source="x")


@pytest.mark.safety
def test_a_value_derived_from_measured_and_modelled_inputs_is_modelled() -> None:
    result = derive([measured("meter"), modelled("PVGIS")], source="calc")
    assert result.provenance is Provenance.MODELLED


@pytest.mark.safety
def test_applying_a_model_to_measured_inputs_yields_a_modelled_value() -> None:
    assert derive([measured("meter")], source="calc", model_applied=True).provenance is Provenance.MODELLED
    assert derive([measured("meter")], source="calc").provenance is Provenance.MEASURED


@pytest.mark.safety
def test_synthetic_inputs_contaminate_everything_derived_from_them() -> None:
    result = derive([measured("meter"), synthetic("generator", emulates=Provenance.MEASURED)], source="calc")
    assert result.provenance is Provenance.SYNTHETIC
    assert result.is_synthetic
    assert result.effective_class(OPERATIONAL) is Provenance.SYNTHETIC


@pytest.mark.safety
def test_unknown_inputs_make_the_result_unknown() -> None:
    result = derive([measured("meter"), UNKNOWN_TAG, modelled("m")], source="calc")
    assert result.provenance is Provenance.UNKNOWN


def test_derivation_without_inputs_is_unknown() -> None:
    assert derive([], source="calc").provenance is Provenance.UNKNOWN


def test_weakest_class_of_a_set() -> None:
    tags = [measured("meter"), modelled("model")]
    assert weakest_effective_class(tags, OPERATIONAL) is Provenance.MODELLED
    tags.append(synthetic("generator", emulates=Provenance.MEASURED))
    assert weakest_effective_class(tags, OPERATIONAL) is Provenance.SYNTHETIC
    assert weakest_effective_class(tags, DEMO) is Provenance.MODELLED
