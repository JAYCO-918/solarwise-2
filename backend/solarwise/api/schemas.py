"""Request and response models of the API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from solarwise.ai.analyst import Insight
from solarwise.core.baseline import PvgisMonth
from solarwise.core.economics import EconomicInputs, EconomicsResult
from solarwise.core.forecast import PerformanceForecast
from solarwise.core.models import (
    METRIC_SPECS,
    BaselineDescriptor,
    EvidenceRecord,
    EvidenceType,
    InspectionFinding,
    PlantSpec,
    SoilingMethod,
)
from solarwise.core.pipeline import AnalysisOptions, AnalysisResult
from solarwise.core.provenance import Provenance, ProvenanceTag
from solarwise.db.models import (
    AiInsight,
    Analysis,
    Dataset,
    DatasetFile,
    Device,
    EconomicReference,
    EvidenceRow,
    Plant,
    User,
)
from solarwise.ingestion.detect import UploadPreview
from solarwise.ingestion.schema import DatasetMetadata
from solarwise.ingestion.validator import ValidationReport

# --------------------------------------------------------------------------- accounts


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class RegisterRequest(BaseModel):
    """Sign-up.  There is no role on purpose: an account created by its own user is never an administrator, and a
    request that names one is refused instead of being silently corrected."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator("full_name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("the name must not be blank")
        return value


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    is_demo: bool
    is_active: bool

    @classmethod
    def of(cls, user: User) -> UserOut:
        return cls(id=user.id, email=user.email, full_name=user.full_name, role=user.role, is_demo=user.is_demo,
                   is_active=user.is_active)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - the OAuth token type, not a secret
    expires_at: datetime
    user: UserOut


class UserCreate(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    full_name: str = Field(default="", max_length=200)
    role: str = Field(default="VIEWER", pattern="^(ADMIN|ENGINEER|VIEWER)$")


class UserUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern="^(ADMIN|ENGINEER|VIEWER)$")
    full_name: str | None = Field(default=None, max_length=200)


# --------------------------------------------------------------------------- plants


class PlantCreate(BaseModel):
    spec: PlantSpec
    description: str = Field(default="", max_length=4000)


class PlantUpdate(BaseModel):
    """Fields of the plant description to change; fields left out are kept."""

    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=4000)


class PvgisOut(BaseModel):
    available: bool
    source: str | None = None
    months: list[PvgisMonth] = []


class AnalysisSummary(BaseModel):
    id: int
    plant_id: int
    dataset_id: int
    created_at: datetime
    context: str
    period_start: date
    period_end: date
    decision: str
    rule: str
    reason_code: str
    diagnostic_status: str
    simulated: bool
    operational_authorization: bool
    gap_pct: float | None
    window_gap_pct: float | None
    headline: str
    engine_version: str

    @classmethod
    def of(cls, a: Analysis) -> AnalysisSummary:
        return cls(
            id=a.id, plant_id=a.plant_id, dataset_id=a.dataset_id, created_at=a.created_at, context=a.context,
            period_start=a.period_start, period_end=a.period_end, decision=a.decision, rule=a.rule,
            reason_code=a.reason_code, diagnostic_status=a.diagnostic_status, simulated=a.simulated,
            operational_authorization=a.operational_authorization, gap_pct=a.gap_pct,
            window_gap_pct=a.window_gap_pct, headline=a.headline, engine_version=a.engine_version,
        )


class PlantOut(BaseModel):
    id: int
    name: str
    description: str
    is_demonstration: bool
    spec: PlantSpec
    role: str
    created_at: datetime
    updated_at: datetime
    dataset_count: int = 0
    device_count: int = 0
    pvgis: PvgisOut
    latest_analysis: AnalysisSummary | None = None

    @classmethod
    def of(cls, plant: Plant, role: str, *, dataset_count: int = 0, device_count: int = 0,
           latest: Analysis | None = None) -> PlantOut:
        return cls(
            id=plant.id, name=plant.name, description=plant.description, is_demonstration=plant.is_demonstration,
            spec=PlantSpec.model_validate(plant.spec), role=role, created_at=plant.created_at,
            updated_at=plant.updated_at, dataset_count=dataset_count, device_count=device_count,
            pvgis=PvgisOut(
                available=bool(plant.pvgis_monthly), source=plant.pvgis_source,
                months=[PvgisMonth.model_validate(m) for m in plant.pvgis_monthly or []],
            ),
            latest_analysis=AnalysisSummary.of(latest) if latest is not None else None,
        )


class DeviceIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    capacity_kwp: float = Field(gt=0)
    kind: str = Field(default="INVERTER", max_length=30)
    description: str = Field(default="", max_length=500)


class DeviceOut(DeviceIn):
    id: int

    @classmethod
    def of(cls, device: Device) -> DeviceOut:
        return cls(id=device.id, code=device.code, capacity_kwp=device.capacity_kwp, kind=device.kind,
                   description=device.description)


class PermissionIn(BaseModel):
    email: str = Field(max_length=254)
    role: str = Field(pattern="^(OWNER|EDITOR|VIEWER)$")


class PermissionOut(BaseModel):
    user_id: int
    email: str
    full_name: str
    role: str


class PvgisManual(BaseModel):
    months: list[PvgisMonth] = Field(min_length=12, max_length=12)
    source: str = Field(min_length=3, max_length=500)


class PvgisFetch(BaseModel):
    #: System losses passed to PVGIS [%]; defaults to the plant's declared system losses.
    loss_pct: float | None = Field(default=None, ge=0, lt=60)


# --------------------------------------------------------------------------- datasets


class ChannelOut(BaseModel):
    metric: str
    column: str
    description: str
    unit: str
    original_unit: str | None
    provenance: str
    provenance_label: str
    source: str
    method: str | None
    uncertainty_pct: float | None
    uncertainty_abs: float | None
    boundary: str | None
    soiling_method: str | None
    notes: str | None


def _channels(dataset: Dataset) -> list[ChannelOut]:
    out: list[ChannelOut] = []
    for key, raw in dataset.channels.items():
        spec = next(s for m, s in METRIC_SPECS.items() if m.value == key)
        tag = ProvenanceTag.model_validate(raw["tag"])
        out.append(
            ChannelOut(
                metric=key, column=spec.column, description=spec.description, unit=spec.unit,
                original_unit=raw.get("original_unit"), provenance=tag.provenance.value, provenance_label=tag.label,
                source=tag.source, method=tag.method, uncertainty_pct=raw.get("uncertainty_pct"),
                uncertainty_abs=raw.get("uncertainty_abs"), boundary=raw.get("boundary"),
                soiling_method=raw.get("soiling_method"), notes=raw.get("notes"),
            )
        )
    return out


class DatasetOut(BaseModel):
    id: int
    plant_id: int
    name: str
    description: str
    kind: str
    file_name: str | None
    file_format: str
    content_sha256: str
    interval_minutes: int
    timezone: str
    period_start: date
    period_end: date
    rows_plant: int
    rows_device: int
    is_synthetic: bool
    archived: bool
    created_at: datetime
    scenario: dict[str, Any] | None
    disclaimer: str | None
    channels: list[ChannelOut]
    baseline: BaselineDescriptor | None
    latest_analysis: AnalysisSummary | None = None

    @classmethod
    def of(cls, d: Dataset, latest: Analysis | None = None) -> DatasetOut:
        baseline = d.declared_metadata.get("baseline")
        return cls(
            id=d.id, plant_id=d.plant_id, name=d.name, description=d.description, kind=d.kind, file_name=d.file_name,
            file_format=d.file_format, content_sha256=d.content_sha256, interval_minutes=d.interval_minutes,
            timezone=d.timezone, period_start=d.period_start, period_end=d.period_end, rows_plant=d.rows_plant,
            rows_device=d.rows_device, is_synthetic=d.is_synthetic, archived=d.archived, created_at=d.created_at,
            scenario=d.default_options, disclaimer=d.declared_metadata.get("disclaimer"), channels=_channels(d),
            baseline=BaselineDescriptor.model_validate(baseline) if baseline is not None else None,
            latest_analysis=AnalysisSummary.of(latest) if latest is not None else None,
        )


class OriginalFileOut(BaseModel):
    """The uploaded file, kept byte for byte."""

    file_name: str
    content_type: str
    size_bytes: int
    sha256: str
    #: Cells and rows rejected at import; the rows concerned can be downloaded.
    rejections: int = 0

    @classmethod
    def of(cls, f: DatasetFile) -> OriginalFileOut:
        return cls(file_name=f.file_name, content_type=f.content_type, size_bytes=f.size_bytes, sha256=f.sha256,
                   rejections=f.rejections)


class DatasetDetail(DatasetOut):
    declared_metadata: DatasetMetadata
    validation_report: ValidationReport
    #: ``None`` for a dataset that did not come from an upload (demonstration scenario, NASA POWER).
    original_file: OriginalFileOut | None = None
    #: Evidence records that came with the dataset: events of the file, or of a demonstration scenario.
    events: list[EvidenceOut] = []

    @classmethod
    def detail(cls, d: Dataset, latest: Analysis | None = None, *, original: DatasetFile | None = None,
               events: list[EvidenceRow] | None = None) -> DatasetDetail:
        base = DatasetOut.of(d, latest)
        return cls(
            **base.model_dump(),
            declared_metadata=DatasetMetadata.model_validate(d.declared_metadata),
            validation_report=ValidationReport.model_validate(d.validation_report),
            original_file=OriginalFileOut.of(original) if original is not None else None,
            events=[EvidenceOut.of(row) for row in events or []],
        )


class OverlapOut(BaseModel):
    """A dataset of the plant that already covers some of the same days."""

    dataset_id: int
    name: str
    period_start: date
    period_end: date


class UploadCheck(BaseModel):
    """Result of validating an upload.  Nothing has been stored."""

    accepted: bool
    stored: bool = False
    duplicate_of: int | None
    content_sha256: str
    declared_metadata: DatasetMetadata
    report: ValidationReport
    dataset: DatasetOut | None = None
    #: SHA-256 of the uploaded bytes alone.
    file_sha256: str = ""
    #: Datasets of the plant imported from the very same file under another declaration.
    same_file_as: list[int] = []
    #: Datasets of the plant that cover some of the same days.  A warning, not a refusal.
    overlapping: list[OverlapOut] = []
    #: Events of the file stored as evidence records of the dataset (after an import).
    events_stored: int = 0


class UploadPreviewOut(BaseModel):
    """A file as it was received, and what its columns probably are.  Nothing was validated or stored."""

    file_name: str
    size_bytes: int
    file_sha256: str
    #: Datasets of the plant already imported from this very file.
    same_file_as: list[int] = []
    preview: UploadPreview


# --------------------------------------------------------------------------- evidence


class EvidenceIn(BaseModel):
    reference: str = Field(min_length=1, max_length=64)
    evidence_type: EvidenceType
    observed_start: datetime
    observed_end: datetime | None = None
    provenance: Provenance = Provenance.UNKNOWN
    source: str = Field(default="", max_length=500)
    method: str | None = Field(default=None, max_length=500)
    description: str = Field(default="", max_length=2000)
    value: float | None = None
    unit: str | None = Field(default=None, max_length=30)
    std_uncertainty: float | None = Field(default=None, ge=0)
    soiling_method: SoilingMethod | None = None
    finding: InspectionFinding | None = None
    device_code: str | None = Field(default=None, max_length=64)
    resolved: bool | None = None
    document_ref: str | None = Field(default=None, max_length=500)


class EvidenceOut(BaseModel):
    id: int
    plant_id: int
    dataset_id: int | None
    created_at: datetime
    provenance_label: str
    record: EvidenceRecord

    @classmethod
    def of(cls, row: EvidenceRow) -> EvidenceOut:
        record = EvidenceRecord.model_validate(row.record)
        return cls(id=row.id, plant_id=row.plant_id, dataset_id=row.dataset_id, created_at=row.created_at,
                   provenance_label=record.tag.label, record=record)


# --------------------------------------------------------------------------- analyses


class AnalysisRequest(BaseModel):
    """What the client may choose.  The evaluation context is not among it: the server decides it."""

    model_config = ConfigDict(extra="forbid")

    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    #: Weather dataset of the same plant used for the weather channels the production dataset lacks.
    weather_dataset_id: int | None = None


class AnalysisDetail(AnalysisSummary):
    dataset_name: str
    dataset_sha256: str
    options: AnalysisOptions
    result: AnalysisResult


class AiStatus(BaseModel):
    """Whether a language model is configured.  Never contains the key."""

    enabled: bool
    provider: str | None
    model: str | None
    #: Host name of the endpoint when a base URL is configured (no path, no credentials).
    endpoint_host: str | None
    capabilities: list[str]
    fallback: str
    role: str


class InsightRecord(BaseModel):
    """One stored insight, without its text."""

    id: int
    created_at: datetime
    generated_by: str
    provider: str | None
    model: str | None
    fell_back: bool

    @classmethod
    def of(cls, row: AiInsight) -> InsightRecord:
        return cls(id=row.id, created_at=row.created_at, generated_by=row.generated_by, provider=row.provider,
                   model=row.model, fell_back=row.fallback_reason is not None)


class InsightOut(BaseModel):
    #: ``False``: nothing was generated yet; ``insight`` is the engine's own, assembled for this answer.
    stored: bool
    id: int | None
    insight: Insight
    #: Every insight kept for the analysis, newest first.
    history: list[InsightRecord] = []


class EconomicsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recoverable_low_kwh: float | None = Field(default=None, ge=0)
    recoverable_base_kwh: float | None = Field(default=None, ge=0)
    recoverable_high_kwh: float | None = Field(default=None, ge=0)
    inputs: EconomicInputs
    horizon_days: float | None = Field(default=None, gt=0, le=366)
    projected_daily_clean_energy_kwh: float | None = Field(default=None, gt=0)
    cleaning_effectiveness: float | None = Field(default=None, gt=0, le=1)


class EconomicsResponse(BaseModel):
    advisory: bool = True
    notice: str
    result: EconomicsResult


class EvaluateRequest(BaseModel):
    """A complete case supplied in one request.  Nothing is stored."""

    model_config = ConfigDict(extra="forbid")

    plant: PlantSpec
    metadata: DatasetMetadata
    records: list[dict[str, Any]] = Field(min_length=1, max_length=20_000)
    devices: list[DeviceIn] = Field(default_factory=list, max_length=500)
    evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=500)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)


class EvaluateResponse(BaseModel):
    advisory: bool = True
    notice: str
    validation: ValidationReport
    result: AnalysisResult | None


class ForecastResponse(BaseModel):
    analysis_id: int
    forecast: PerformanceForecast


# --------------------------------------------------------------------------- reference and integrations


class ReferenceOut(BaseModel):
    key: str
    label: str
    category: str
    classification: str
    amount: float | None
    currency: str | None
    unit: str | None
    source_title: str
    source_reference: str
    verification_status: str
    applicability: str
    notes: str

    @classmethod
    def of(cls, r: EconomicReference) -> ReferenceOut:
        return cls(
            key=r.key, label=r.label, category=r.category, classification=r.classification, amount=r.amount,
            currency=r.currency, unit=r.unit, source_title=r.source_title, source_reference=r.source_reference,
            verification_status=r.verification_status, applicability=r.applicability, notes=r.notes,
        )


class NasaPowerRequest(BaseModel):
    start: date
    end: date
    #: Store the result as a weather dataset of the plant (otherwise only a preview is returned).
    store: bool = False


DatasetDetail.model_rebuild()
