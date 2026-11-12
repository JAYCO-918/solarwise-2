"""Evidence provenance model.

Every number that enters or leaves a SolarWise engine carries a
:class:`ProvenanceTag`.  The tag answers one question: *where does this value
come from, and how much may we rely on it?*

Four classes are distinguished:

``MEASURED``
    Direct observation from a sensor, a SCADA historian, a revenue meter or a
    documented inspection.
``MODELLED``
    Output of an engineering or simulation model (PVGIS, a temperature model,
    a satellite-derived irradiance product, a statistical fit ...).
``SYNTHETIC``
    Artificially generated for testing or demonstration.  Never real.
``UNKNOWN``
    Origin or reliability cannot be established.

Two rules are enforced here and relied upon by every downstream engine:

1.  **Synthetic never becomes real.**  Any value derived from at least one
    synthetic input is itself synthetic.  There is no operation that turns a
    ``SYNTHETIC`` tag into ``MEASURED`` or ``MODELLED``.
2.  **A derived value is never better than its weakest input.**

Demonstration scenarios need to exercise the *logic* that applies to measured
evidence without ever relabelling artificial numbers as measurements.  For
that purpose a synthetic value may declare which evidence class it *emulates*
inside its scenario (``emulates=MEASURED`` for an artificial SCADA channel,
``emulates=MODELLED`` for an artificial baseline).  The emulated class is only
honoured when the evaluation context is explicitly ``DEMONSTRATION``; the
resulting decision is then flagged as simulated and can never authorise an
operation.  In the ``OPERATIONAL`` context a synthetic value is just synthetic.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Provenance(StrEnum):
    """Formal evidence classification."""

    MEASURED = "MEASURED"
    MODELLED = "MODELLED"
    SYNTHETIC = "SYNTHETIC"
    UNKNOWN = "UNKNOWN"


class EvaluationContext(StrEnum):
    """How the provenance of synthetic evidence is treated by the rule engines."""

    #: Real plant operation.  Synthetic evidence is never accepted as measured.
    OPERATIONAL = "OPERATIONAL"
    #: Illustrative scenario.  Synthetic evidence may stand in for the class it
    #: emulates, and every decision is marked as simulated / non-operational.
    DEMONSTRATION = "DEMONSTRATION"


#: Dominance order used when values are combined: the class with the highest
#: rank wins.  ``SYNTHETIC`` dominates everything so that artificial content
#: can never be hidden by mixing it with real data.
_DOMINANCE: dict[Provenance, int] = {
    Provenance.MEASURED: 0,
    Provenance.MODELLED: 1,
    Provenance.UNKNOWN: 2,
    Provenance.SYNTHETIC: 3,
}


class ProvenanceTag(BaseModel):
    """Provenance of a single value or channel."""

    model_config = ConfigDict(frozen=True)

    provenance: Provenance
    #: Only meaningful for synthetic values: the evidence class this artificial
    #: value stands in for inside a demonstration scenario.
    emulates: Provenance | None = None
    #: Human readable origin: instrument, model, generator, document ...
    source: str = Field(default="", max_length=500)
    #: Optional description of how the value was obtained or computed.
    method: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _check_emulation(self) -> ProvenanceTag:
        if self.emulates is not None:
            if self.provenance is not Provenance.SYNTHETIC:
                raise ValueError("'emulates' may only be declared for SYNTHETIC values")
            if self.emulates is Provenance.SYNTHETIC:
                raise ValueError("a synthetic value cannot emulate SYNTHETIC evidence")
        return self

    @property
    def is_synthetic(self) -> bool:
        return self.provenance is Provenance.SYNTHETIC

    @property
    def label(self) -> str:
        """Display label.  A synthetic value is always shown as synthetic."""
        if self.is_synthetic and self.emulates is not None:
            return f"SYNTHETIC (emulates {self.emulates.value})"
        return self.provenance.value

    def effective_class(self, context: EvaluationContext) -> Provenance:
        """Evidence class the rule engines must use for gating.

        * Non-synthetic values: their declared class.
        * Synthetic values in the ``OPERATIONAL`` context: ``SYNTHETIC``,
          unconditionally.
        * Synthetic values in the ``DEMONSTRATION`` context: the emulated class
          if one was declared, otherwise ``SYNTHETIC``.
        """
        if self.provenance is not Provenance.SYNTHETIC:
            return self.provenance
        if context is EvaluationContext.DEMONSTRATION and self.emulates is not None:
            return self.emulates
        return Provenance.SYNTHETIC


UNKNOWN_TAG = ProvenanceTag(provenance=Provenance.UNKNOWN, source="origin not declared")


def measured(source: str, method: str | None = None) -> ProvenanceTag:
    return ProvenanceTag(provenance=Provenance.MEASURED, source=source, method=method)


def modelled(source: str, method: str | None = None) -> ProvenanceTag:
    return ProvenanceTag(provenance=Provenance.MODELLED, source=source, method=method)


def synthetic(
    source: str, emulates: Provenance | None = None, method: str | None = None
) -> ProvenanceTag:
    return ProvenanceTag(provenance=Provenance.SYNTHETIC, emulates=emulates, source=source, method=method)


def _dominant(classes: Iterable[Provenance]) -> Provenance:
    return max(classes, key=lambda c: _DOMINANCE[c])


def derive(
    inputs: Iterable[ProvenanceTag],
    *,
    source: str,
    method: str | None = None,
    model_applied: bool = False,
) -> ProvenanceTag:
    """Provenance of a value computed from ``inputs``.

    Parameters
    ----------
    inputs:
        Tags of every value that contributed to the result.
    source, method:
        Description of the computation, recorded on the new tag.
    model_applied:
        ``True`` when the computation involves a physical or statistical model
        (rather than plain arithmetic such as a sum or a ratio).  A model
        applied to measured inputs yields a ``MODELLED`` result.

    Rules
    -----
    * no inputs                 -> ``UNKNOWN``
    * any synthetic input       -> ``SYNTHETIC`` (the emulated class, if every
      synthetic input declares one, follows the same weakest-link rule)
    * otherwise                 -> weakest class among the inputs
      (``UNKNOWN`` > ``MODELLED`` > ``MEASURED``), raised to at least
      ``MODELLED`` when ``model_applied`` is true.
    """
    tags = list(inputs)
    if not tags:
        return ProvenanceTag(provenance=Provenance.UNKNOWN, source=source, method=method)

    def _raise_for_model(cls: Provenance) -> Provenance:
        if model_applied and cls is Provenance.MEASURED:
            return Provenance.MODELLED
        return cls

    if any(t.is_synthetic for t in tags):
        emulated: Provenance | None
        if any(t.is_synthetic and t.emulates is None for t in tags):
            # A plain synthetic input (no declared role) contaminates the result:
            # nothing can be said about what the derived value would emulate.
            emulated = None
        else:
            stand_ins = [t.emulates if t.is_synthetic else t.provenance for t in tags]
            emulated = _raise_for_model(_dominant(c for c in stand_ins if c is not None))
        return ProvenanceTag(
            provenance=Provenance.SYNTHETIC, emulates=emulated, source=source, method=method
        )

    return ProvenanceTag(
        provenance=_raise_for_model(_dominant(t.provenance for t in tags)),
        source=source,
        method=method,
    )


def weakest_effective_class(tags: Iterable[ProvenanceTag], context: EvaluationContext) -> Provenance:
    """Weakest effective class among ``tags`` (``UNKNOWN`` when empty)."""
    classes = [t.effective_class(context) for t in tags]
    if not classes:
        return Provenance.UNKNOWN
    return _dominant(classes)


class Traced(BaseModel):
    """A numeric value together with its unit, provenance and (optional) uncertainty.

    ``value`` is ``None`` when the quantity could not be determined.  A missing
    value is never represented by zero.
    """

    model_config = ConfigDict(frozen=True)

    value: float | None
    unit: str
    tag: ProvenanceTag
    #: Standard uncertainty (one sigma) in the same unit.  Only populated when
    #: it follows mathematically from declared input uncertainties.
    std_uncertainty: float | None = None
    #: How the number was obtained, in engineering terms.
    basis: str | None = None
    note: str | None = None
