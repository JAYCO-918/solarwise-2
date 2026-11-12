"""Run a demonstration scenario through the same path as an uploaded dataset."""

from __future__ import annotations

from solarwise.core.pipeline import AnalysisInput, AnalysisOptions, AnalysisResult, run_analysis
from solarwise.core.provenance import EvaluationContext
from solarwise.demo.scenarios import Scenario
from solarwise.ingestion.parser import RawTable
from solarwise.ingestion.validator import ParsedDataset, ValidationReport, validate_table


def scenario_table(scenario: Scenario) -> RawTable:
    columns: list[str] = []
    for row in scenario.rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    return RawTable(columns=columns, rows=scenario.rows, file_format="JSON")


def parse_scenario(scenario: Scenario) -> tuple[ValidationReport, ParsedDataset]:
    """Validate the scenario exactly as an upload would be validated."""
    report, parsed = validate_table(
        scenario_table(scenario),
        scenario.metadata,
        plant=scenario.plant,
        known_devices={d.code: d for d in scenario.devices},
    )
    if parsed is None:  # pragma: no cover - the shipped scenarios are valid by construction
        raise RuntimeError(f"scenario {scenario.key} failed validation: {report.summary}")
    return report, parsed


def scenario_input(
    scenario: Scenario,
    context: EvaluationContext = EvaluationContext.DEMONSTRATION,
    *,
    with_economics: bool = True,
) -> AnalysisInput:
    _, parsed = parse_scenario(scenario)
    return AnalysisInput(
        plant=scenario.plant,
        observations=parsed.observations,
        interval_minutes=parsed.interval_minutes,
        channels=parsed.channels,
        context=context,
        options=AnalysisOptions(
            cleaning=scenario.cleaning if with_economics else None,
            economics=scenario.economics if with_economics else None,
        ),
        declared_baseline=parsed.baseline,
        device_observations=parsed.device_observations,
        devices={d.code: d for d in scenario.devices},
        device_tag=parsed.device_tag,
        records=scenario.evidence,
        dataset_name=scenario.metadata.name,
        dataset_disclaimer=scenario.metadata.disclaimer,
    )


def run_scenario(
    scenario: Scenario, context: EvaluationContext = EvaluationContext.DEMONSTRATION
) -> AnalysisResult:
    return run_analysis(scenario_input(scenario, context))
