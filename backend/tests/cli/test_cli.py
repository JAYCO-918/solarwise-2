"""Command line: the same engine and the same validation as the web application."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from solarwise import __version__
from solarwise.cli import EXIT_ERROR, EXIT_OK, EXIT_REFUSED, main, table_csv
from solarwise.core.provenance import EvaluationContext
from solarwise.demo.run import run_scenario
from solarwise.demo.scenarios import SCENARIO_KEYS, build_scenario
from solarwise.ingestion.schema import unfilled_placeholders

REPO = Path(__file__).resolve().parents[3]
SAMPLES = REPO / "data" / "samples"
SHIPPED_DEMO = REPO / "data" / "demo"


@pytest.fixture(scope="module")
def exported(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("demo-export")
    assert main(["export-demo", "--out", str(target)]) == EXIT_OK
    return target


def analyze_args(directory: Path, key: str, *extra: str) -> list[str]:
    return [
        "analyze", str(directory / f"{key}.csv"), "--plant", str(directory / "plant.json"),
        "--devices", str(directory / "devices.json"), "--metadata", str(directory / f"{key}.metadata.json"),
        "--evidence", str(directory / f"{key}.evidence.json"), "--options", str(directory / f"{key}.options.json"),
        *extra,
    ]


def strip_volatile(result: dict) -> dict:
    return {k: v for k, v in result.items() if k != "generated_at"}


# --------------------------------------------------------------------------- basics


def test_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--version"])
    assert stopped.value.code == 0 and __version__ in capsys.readouterr().out
    with pytest.raises(SystemExit) as stopped:
        main([])
    assert stopped.value.code == 2


def test_scenarios_listing_matches_the_expected_decisions(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios", "--json"]) == EXIT_OK
    listing = json.loads(capsys.readouterr().out)
    assert [row["key"] for row in listing["scenarios"]] == list(SCENARIO_KEYS)
    for row in listing["scenarios"]:
        assert (row["decision"], row["rule"]) == (row["expected_decision"], row["expected_rule"])
        assert row["simulated"] is True and row["operational_authorization"] is False


@pytest.mark.safety
def test_scenarios_evaluated_as_operational_data_never_reach_a_decision(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenarios", "--operational", "--json"]) == EXIT_OK
    listing = json.loads(capsys.readouterr().out)
    assert {(row["decision"], row["rule"]) for row in listing["scenarios"]} == {("INVESTIGATE", "R0")}


def test_one_scenario_as_text(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["scenario", "s02"]) == EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("S02_confirmed_soiling: Confirmed soiling")
    assert "SIMULATED DECISION - Clean now" in out
    assert "Decision        CLEAN_NOW  (rule R3" in out
    assert "Authorisation   none - advisory result" in out
    assert out.count("[pass]") == 10 and "[FAIL]" not in out
    assert main(["scenario", "nope"]) == EXIT_ERROR
    assert "unknown scenario" in capsys.readouterr().err


# --------------------------------------------------------------------------- files


def test_export_writes_every_scenario_with_its_declarations(exported: Path) -> None:
    for key in SCENARIO_KEYS:
        for suffix in (".csv", ".metadata.json", ".evidence.json", ".options.json"):
            assert (exported / f"{key}{suffix}").is_file()
        metadata = json.loads((exported / f"{key}.metadata.json").read_text())
        assert metadata["synthetic"]["statement"].startswith("SYNTHETIC DEMONSTRATION DATASET")
        assert {c["provenance"] for c in metadata["channels"].values()} == {"SYNTHETIC"}
    readme = (exported / "README.md").read_text()
    assert "Every file in this directory is synthetic" in readme
    assert json.loads((exported / "plant.json").read_text())["is_demonstration"] is True


def test_shipped_demo_files_are_exactly_what_the_generator_writes(exported: Path) -> None:
    """data/demo is generated: it must not drift from the code or be edited by hand."""
    shipped = sorted(p.name for p in SHIPPED_DEMO.iterdir())
    assert shipped == sorted(p.name for p in exported.iterdir())
    for name in shipped:
        assert (SHIPPED_DEMO / name).read_bytes() == (exported / name).read_bytes(), f"{name} differs: run `solarwise export-demo`"


@pytest.mark.parametrize("key", SCENARIO_KEYS)
def test_analysing_the_exported_files_reproduces_the_scenario_exactly(
    exported: Path, key: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(analyze_args(exported, key, "--demonstration", "--format", "result-json")) == EXIT_OK
    from_files = json.loads(capsys.readouterr().out)
    in_memory = run_scenario(build_scenario(key), EvaluationContext.DEMONSTRATION).model_dump(mode="json")
    assert strip_volatile(from_files) == strip_volatile(in_memory)


@pytest.mark.safety
def test_offline_analysis_of_synthetic_files_as_operational_data_is_refused_a_decision(
    exported: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(analyze_args(exported, "S02_confirmed_soiling", "--format", "result-json")) == EXIT_OK
    recommendation = json.loads(capsys.readouterr().out)["recommendation"]
    assert recommendation["decision"] == "INVESTIGATE" and recommendation["rule"] == "R0"
    assert recommendation["operational_authorization"] is False


@pytest.mark.safety
def test_offline_analysis_never_carries_an_operational_authorisation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Measured data, every gate passed: the engine says CLEAN_NOW, but an unrecorded run authorises nothing."""
    days = 30
    rows = [
        {"timestamp": f"2026-05-{d:02d}T00:00+01:00", "actual_energy_kwh": 46000.0, "expected_energy_kwh": 50000.0,
         "soiling_ratio": 0.92, "availability_fraction": 1.0, "poa_irradiation_kwh_m2": 7.0, "module_temp_c": 45.0}
        for d in range(1, days + 1)
    ]
    (tmp_path / "data.csv").write_text(table_csv(list(rows[0]), rows))
    measured = {"provenance": "MEASURED", "source": "artificial test fixture"}
    metadata = {
        "name": "Artificial fixture",
        "interval_minutes": 1440,
        "channels": {
            "actual_energy": {**measured, "uncertainty_pct": 0.5, "boundary": "GRID_METER"},
            "expected_energy": {"provenance": "MODELLED", "source": "artificial test fixture", "uncertainty_pct": 2.0, "boundary": "GRID_METER"},
            "soiling_ratio": {**measured, "uncertainty_abs": 0.005, "soiling_method": "SOILING_STATION"},
            "availability": measured, "poa_irradiation": measured, "module_temp": measured,
        },
        "baseline": {"method": "TELEMETRY_MODEL", "irradiance_adjusted": True, "temperature_adjusted": True,
                     "degradation_adjusted": True, "soiling_allowance_fraction": 0.0, "description": "artificial"},
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    (tmp_path / "plant.json").write_text(json.dumps(
        {"name": "Test plant", "capacity_dc_kwp": 10000.0, "latitude": 33.0, "longitude": 6.0, "timezone": "Africa/Algiers"}
    ))
    options = json.loads((SHIPPED_DEMO / "S02_confirmed_soiling.options.json").read_text())
    options["economics"].update(water_volume_m3=10.0, labour_hours=10.0, equipment_cost=1000.0, operational_cost=1000.0)
    (tmp_path / "options.json").write_text(json.dumps(options))
    code = main(["analyze", str(tmp_path / "data.csv"), "--plant", str(tmp_path / "plant.json"),
                 "--metadata", str(tmp_path / "metadata.json"), "--options", str(tmp_path / "options.json"),
                 "--format", "result-json"])
    assert code == EXIT_OK
    recommendation = json.loads(capsys.readouterr().out)["recommendation"]
    assert recommendation["decision"] == "CLEAN_NOW" and recommendation["simulated"] is False
    assert recommendation["operational_authorization"] is False


def test_reports_can_be_written_in_every_format(exported: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for fmt, check in (("html", b"<!doctype html>"), ("pdf", b"%PDF-"), ("csv", b"# SolarWise DZ daily export"), ("json", b"{")):
        out = tmp_path / f"report.{fmt}"
        assert main(analyze_args(exported, "S04_inverter_fault", "--demonstration", "--format", fmt, "-o", str(out))) == EXIT_OK
        content = out.read_bytes()
        assert content.lstrip(b'"').lower().startswith(check.lower())
        assert b"SIMULATED" in content or fmt == "pdf"
    capsys.readouterr()
    assert main(analyze_args(exported, "S04_inverter_fault", "--demonstration", "--format", "pdf")) == EXIT_ERROR
    assert "--out" in capsys.readouterr().err


def test_table_csv_keeps_missing_values_empty_and_floats_exact() -> None:
    text = table_csv(["a", "b", "c"], [{"a": 0.1 + 0.2, "b": None, "c": "x,y"}, {"a": 0.0}])
    rows = list(csv.reader(io.StringIO(text)))
    assert rows == [["a", "b", "c"], ["0.30000000000000004", "", "x,y"], ["0.0", "", ""]]


# --------------------------------------------------------------------------- refusals


def test_a_file_that_fails_validation_is_refused_with_the_reasons(exported: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("timestamp,actual_energy_kwh\nnot a date,12\nalso not a date,13\n")
    code = main(["validate", str(bad), "--plant", str(exported / "plant.json")])
    assert code == EXIT_REFUSED
    out = capsys.readouterr().out
    assert out.startswith("Import refused") and "BLOCKING" in out
    assert main(["analyze", str(bad), "--plant", str(exported / "plant.json")]) == EXIT_REFUSED


@pytest.mark.parametrize(
    ("argument", "content", "message"),
    [
        ("--plant", "{not json", "not valid JSON"),
        ("--plant", json.dumps({"name": "x"}), "plant description is not valid"),
        ("--options", json.dumps({"surprise": 1}), "options file is not valid"),
        ("--evidence", json.dumps({"reference": "x"}), "must be a JSON list"),
        ("--devices", json.dumps([{"code": "A"}]), "invalid device entry"),
        ("--metadata", json.dumps({"channels": {"actual_energy": {"provenance": "CERTAIN"}}}), "metadata"),
    ],
)
def test_unusable_input_files_are_reported_without_a_traceback(
    exported: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str], argument: str, content: str, message: str
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text(content)
    args = analyze_args(exported, "S01_normal_operation")
    args[args.index(argument) + 1] = str(broken)
    assert main(args) == EXIT_ERROR
    err = capsys.readouterr().err
    assert err.startswith("error:") and message in err and "Traceback" not in err


def test_a_missing_file_is_reported(exported: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["analyze", "/nonexistent/data.csv", "--plant", str(exported / "plant.json")]) == EXIT_ERROR
    assert "cannot read" in capsys.readouterr().err


# --------------------------------------------------------------------------- templates


@pytest.mark.safety
@pytest.mark.parametrize("name", ["plant.template.json", "daily_measured.template.metadata.json",
                                  "evidence.template.json", "options.template.json"])
def test_shipped_templates_cannot_be_used_as_they_stand(name: str) -> None:
    payload = json.loads((SAMPLES / name).read_text())
    assert unfilled_placeholders(payload), "a template must carry REPLACE markers"

    def numbers(value: object) -> list[float]:
        if isinstance(value, bool):
            return []
        if isinstance(value, int | float):
            return [float(value)]
        if isinstance(value, dict):
            return [n for v in value.values() for n in numbers(v)]
        if isinstance(value, list):
            return [n for v in value for n in numbers(v)]
        return []

    # No figure that could be mistaken for a price, a cost, a capacity or a measurement.
    assert set(numbers(payload)) <= {0.0, 1440.0}


@pytest.mark.safety
def test_a_template_is_refused_by_the_command_line(exported: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["validate", str(exported / "S01_normal_operation.csv"), "--plant", str(exported / "plant.json"),
                 "--metadata", str(SAMPLES / "daily_measured.template.metadata.json")])
    assert code == EXIT_ERROR
    err = capsys.readouterr().err
    assert "template placeholders" in err and "channels.actual_energy.source" in err
    code = main(["validate", str(exported / "S01_normal_operation.csv"), "--plant", str(SAMPLES / "plant.template.json")])
    assert code == EXIT_ERROR and "has not been filled in" in capsys.readouterr().err


def test_placeholder_detection() -> None:
    assert unfilled_placeholders({"a": "REPLACE - x", "b": [{"c": " REPLACE"}], "d": "Replacement of inverter 3", "e": 4}) == ["a", "b[0].c"]
    assert unfilled_placeholders("REPLACEMENT PARTS") == []


def test_template_header_lists_only_known_columns() -> None:
    from solarwise.core.models import METRIC_SPECS

    header = (SAMPLES / "daily_measured.template.csv").read_text().strip().split(",")
    known = {spec.column for spec in METRIC_SPECS.values()} | {"timestamp", "device_code"}
    assert header[0] == "timestamp" and set(header) <= known
    declared = json.loads((SAMPLES / "daily_measured.template.metadata.json").read_text())["channels"]
    assert {METRIC_SPECS[m].column for m in METRIC_SPECS if m.value in declared} == set(header) - {"timestamp"}


# --------------------------------------------------------------------------- the templates, once filled in


def _filled(value: object, key: str = "") -> object:
    """Replace every placeholder of a template the way a user would: text for text, a date for a date."""
    if isinstance(value, dict):
        return {k: _filled(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_filled(v, key) for v in value]
    if isinstance(value, str) and value.lstrip().startswith("REPLACE"):
        return "2026-01-31T06:00:00+01:00" if key.startswith("observed_") else "filled in by the operator"
    return value


def test_the_metadata_template_is_a_valid_declaration_once_its_placeholders_are_replaced() -> None:
    from solarwise.ingestion.schema import DatasetMetadata

    template = json.loads((SAMPLES / "daily_measured.template.metadata.json").read_text(encoding="utf-8"))
    metadata = DatasetMetadata.model_validate(_filled(template))
    assert unfilled_placeholders(metadata.model_dump(mode="json")) == []
    # The template shows a measured dataset: nothing in it is declared synthetic.
    assert not metadata.is_synthetic


def test_the_evidence_template_holds_valid_records_once_its_placeholders_are_replaced() -> None:
    from solarwise.core.models import EvidenceRecord

    template = json.loads((SAMPLES / "evidence.template.json").read_text(encoding="utf-8"))
    records = [EvidenceRecord.model_validate(item) for item in _filled(template)]  # type: ignore[union-attr]
    assert len(records) == len(template) > 0


def test_the_options_template_is_valid_and_supplies_no_figure() -> None:
    from solarwise.core.pipeline import AnalysisOptions

    template = json.loads((SAMPLES / "options.template.json").read_text(encoding="utf-8"))
    options = AnalysisOptions.model_validate(_filled(template))
    assert options.cleaning is not None and options.economics is not None
    numbers = {
        **options.cleaning.model_dump(exclude={"source_note"}),
        **options.economics.model_dump(include={
            "energy_value_per_kwh", "water_cost", "water_volume_m3", "water_price_per_m3", "labour_cost",
            "labour_hours", "labour_rate_per_hour", "equipment_cost", "operational_cost", "downtime_cost",
            "downtime_energy_kwh", "cost_uncertainty_pct",
        }),
    }
    assert all(value is None for value in numbers.values()), numbers


def test_the_plant_template_needs_its_figures_and_is_valid_with_them() -> None:
    from pydantic import ValidationError

    from solarwise.core.models import PlantSpec

    template = _filled(json.loads((SAMPLES / "plant.template.json").read_text(encoding="utf-8")))
    assert isinstance(template, dict)
    with pytest.raises(ValidationError):
        PlantSpec.model_validate(template)  # capacity and coordinates are not optional and have no default
    spec = PlantSpec.model_validate({**template, "capacity_dc_kwp": 1000.0, "latitude": 33.5, "longitude": 6.8})
    assert spec.is_demonstration is False


# --------------------------------------------------------------------------- API description


def test_openapi_command_writes_the_api_description(tmp_path: Path) -> None:
    target = tmp_path / "openapi.json"
    assert main(["openapi", "--out", str(target)]) == EXIT_OK
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["info"]["version"] == __version__
    assert "/api/v1/datasets/{dataset_id}/analyses" in document["paths"]
    assert {"AnalysisResult", "Recommendation", "Gate"} <= set(document["components"]["schemas"])


def test_the_api_description_used_by_the_web_interface_is_current(tmp_path: Path) -> None:
    """The TypeScript types of the web interface are generated from ``frontend/openapi.json``.

    If this fails the API changed: run ``solarwise openapi -o ../frontend/openapi.json`` and then
    ``npm run gen:api`` in ``frontend/``.
    """
    shipped = REPO / "frontend" / "openapi.json"
    if not shipped.exists():
        pytest.skip("the web interface is not part of this checkout")
    target = tmp_path / "openapi.json"
    assert main(["openapi", "--out", str(target)]) == EXIT_OK
    assert json.loads(shipped.read_text(encoding="utf-8")) == json.loads(target.read_text(encoding="utf-8"))


def test_check_config_says_who_can_create_accounts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env file of a developer
    for name in ("SOLARWISE_ALLOW_REGISTRATION", "SOLARWISE_ENVIRONMENT", "SOLARWISE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert main(["check-config"]) == EXIT_OK
    development = capsys.readouterr().out
    assert "sign-up" in development and "open: visitors can create their own account" in development
    assert "warning: sign-up is open" not in development

    monkeypatch.setenv("SOLARWISE_ENVIRONMENT", "production")
    monkeypatch.setenv("SOLARWISE_SECRET_KEY", "k" * 48)
    assert main(["check-config"]) == EXIT_OK
    assert "warning: sign-up is open" in capsys.readouterr().out

    monkeypatch.setenv("SOLARWISE_ALLOW_REGISTRATION", "false")
    assert main(["check-config"]) == EXIT_OK
    production = capsys.readouterr().out
    assert "closed: accounts are created by an administrator" in production
    assert "warning: sign-up is open" not in production


def test_check_config_says_which_language_model_is_configured_and_never_its_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env file of a developer
    for name in ("SOLARWISE_AI_PROVIDER", "SOLARWISE_AI_MODEL", "SOLARWISE_AI_API_KEY", "SOLARWISE_AI_BASE_URL",
                 "SOLARWISE_ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)
    assert main(["check-config"]) == EXIT_OK
    assert "language model       off (engine text only)" in capsys.readouterr().out

    monkeypatch.setenv("SOLARWISE_AI_PROVIDER", "openai-compatible")
    monkeypatch.setenv("SOLARWISE_AI_API_KEY", "sk-a-secret-that-must-not-be-printed")
    assert main(["check-config"]) == EXIT_OK
    assert "a provider is set but no model is named" in capsys.readouterr().out

    monkeypatch.setenv("SOLARWISE_AI_MODEL", "some-model")
    monkeypatch.setenv("SOLARWISE_AI_BASE_URL", "https://llm.example.org/v1")
    assert main(["check-config"]) == EXIT_OK
    configured = capsys.readouterr().out
    assert "openai-compatible, model some-model, at https://llm.example.org/v1, key configured" in configured
    assert "sk-a-secret-that-must-not-be-printed" not in configured

    # A model served on one's own machines may take no key; a commercial API always does.
    monkeypatch.delenv("SOLARWISE_AI_API_KEY")
    assert main(["check-config"]) == EXIT_OK
    assert "model some-model, at https://llm.example.org/v1, no key" in capsys.readouterr().out
    monkeypatch.delenv("SOLARWISE_AI_BASE_URL")
    assert main(["check-config"]) != EXIT_OK
    assert "SOLARWISE_AI_API_KEY is required" in capsys.readouterr().err


def test_settings_that_cannot_be_used_are_explained_before_the_server_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from solarwise.config import get_settings

    monkeypatch.chdir(tmp_path)  # no .env file here
    monkeypatch.setenv("SOLARWISE_ENVIRONMENT", "production")
    monkeypatch.delenv("SOLARWISE_SECRET_KEY", raising=False)
    get_settings.cache_clear()
    try:
        assert main(["serve"]) == EXIT_ERROR
        assert main(["migrate"]) == EXIT_ERROR
    finally:
        get_settings.cache_clear()
    message = capsys.readouterr().err
    assert "SOLARWISE_SECRET_KEY (at least 32 characters) is required in production" in message
    assert "Traceback" not in message
