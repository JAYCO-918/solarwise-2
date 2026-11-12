"""Dataset metadata: what the uploader declares about a file.

Nothing about a dataset is assumed.  Provenance, units, uncertainty and the
properties of the baseline are *declared* in this document; what is not declared
is recorded as UNKNOWN and treated accordingly by the engines.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solarwise.core.models import (
    METRIC_SPECS,
    BaselineDescriptor,
    ChannelMeta,
    IrradiancePlane,
    MeteringBoundary,
    Metric,
    SoilingMethod,
)
from solarwise.core.provenance import Provenance, ProvenanceTag

#: Column holding the interval start.
DEFAULT_TIMESTAMP_COLUMN = "timestamp"
#: Optional column: rows with a value here are device-level rows.
DEFAULT_DEVICE_COLUMN = "device_code"


#: Text values of the shipped templates start with this word until they are filled in.
_TEMPLATE_MARKER = re.compile(r"^\s*REPLACE\b")


def unfilled_placeholders(payload: Any, path: str = "") -> list[str]:
    """Paths of the text values that still carry the marker of the shipped templates.

    A template declares channels as MEASURED so that it shows what a real declaration looks like.
    Imported as it stands it would vouch for data nobody described, so it is refused.
    """
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            found += unfilled_placeholders(value, f"{path}.{key}" if path else str(key))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found += unfilled_placeholders(value, f"{path}[{index}]")
    elif isinstance(payload, str) and _TEMPLATE_MARKER.match(payload):
        found.append(path or "(root)")
    return found


class ChannelDeclaration(BaseModel):
    """Declared properties of one data channel."""

    model_config = ConfigDict(extra="forbid")

    #: Name of the column in the file (defaults to the canonical column name).
    column: str | None = Field(default=None, max_length=120)
    #: Unit of the values in the file (defaults to the canonical unit).
    unit: str | None = Field(default=None, max_length=30)
    provenance: Provenance = Provenance.UNKNOWN
    #: For synthetic channels: the evidence class the values stand in for in a demonstration.
    emulates: Provenance | None = None
    source: str = Field(default="", max_length=500)
    method: str | None = Field(default=None, max_length=500)
    #: Relative standard uncertainty (one sigma) [% of value].
    uncertainty_pct: float | None = Field(default=None, ge=0, le=100)
    #: Absolute standard uncertainty (one sigma), in the canonical unit.
    uncertainty_abs: float | None = Field(default=None, ge=0)
    boundary: MeteringBoundary | None = None
    plane: IrradiancePlane | None = None
    soiling_method: SoilingMethod | None = None
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _check(self) -> ChannelDeclaration:
        if self.emulates is not None and self.provenance is not Provenance.SYNTHETIC:
            raise ValueError("'emulates' may only be declared for SYNTHETIC channels")
        if self.emulates is Provenance.SYNTHETIC:
            raise ValueError("a synthetic channel cannot emulate SYNTHETIC")
        return self

    def tag(self) -> ProvenanceTag:
        return ProvenanceTag(
            provenance=self.provenance,
            emulates=self.emulates,
            source=self.source or ("origin not declared" if self.provenance is Provenance.UNKNOWN else ""),
            method=self.method,
        )

    def to_meta(self, metric: Metric) -> ChannelMeta:
        spec = METRIC_SPECS[metric]
        return ChannelMeta(
            metric=metric,
            tag=self.tag(),
            unit=spec.unit,
            original_unit=self.unit,
            uncertainty_pct=self.uncertainty_pct,
            uncertainty_abs=self.uncertainty_abs,
            boundary=self.boundary,
            plane=self.plane,
            soiling_method=self.soiling_method,
            notes=self.notes,
        )


class SyntheticDeclaration(BaseModel):
    """Reproducibility record of an artificial dataset."""

    model_config = ConfigDict(extra="allow")

    generator: str = Field(max_length=200)
    generator_version: str = Field(max_length=50)
    seed: int | None = None
    statement: str = Field(max_length=2000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    #: Effects deliberately injected by the generator.
    injected_effects: list[str] = Field(default_factory=list)


class DatasetMetadata(BaseModel):
    """Everything declared about an uploaded dataset."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    #: IANA time zone applied to timestamps that carry no offset.  Defaults to the plant's.
    timezone: str | None = Field(default=None, max_length=64)
    #: Interval length; inferred from the timestamps when omitted.
    interval_minutes: int | None = None
    timestamp_column: str = Field(default=DEFAULT_TIMESTAMP_COLUMN, max_length=120)
    device_column: str = Field(default=DEFAULT_DEVICE_COLUMN, max_length=120)
    #: metric name -> declaration.  Keys are :class:`~solarwise.core.models.Metric` values.
    channels: dict[Metric, ChannelDeclaration] = Field(default_factory=dict)
    #: What a supplied expected-energy channel does and does not account for.
    baseline: BaselineDescriptor | None = None
    #: Installed DC capacity the file refers to; checked against the plant configuration.
    capacity_dc_kwp: float | None = Field(default=None, gt=0)
    synthetic: SyntheticDeclaration | None = None
    #: Statement displayed with every result derived from this dataset.
    disclaimer: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _check(self) -> DatasetMetadata:
        if self.interval_minutes is not None and self.interval_minutes not in (15, 30, 60, 1440):
            raise ValueError("interval_minutes must be one of 15, 30, 60 or 1440")
        any_synthetic = any(c.provenance is Provenance.SYNTHETIC for c in self.channels.values())
        if any_synthetic and self.synthetic is None:
            raise ValueError(
                "channels are declared SYNTHETIC but the 'synthetic' block (generator, version, statement) "
                "is missing: a synthetic dataset must document how it was produced"
            )
        return self

    @property
    def is_synthetic(self) -> bool:
        return self.synthetic is not None or any(
            c.provenance is Provenance.SYNTHETIC for c in self.channels.values()
        )
