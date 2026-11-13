"""Scripted answers of a stand-in model: one that keeps to the findings, and ones that do not."""

from __future__ import annotations

import json
from typing import Any

#: A faithful reading of scenario S05 (shading pattern, material unexplained residual, decision INVESTIGATE).
FAITHFUL_S05: dict[str, Any] = {
    "executive_summary": (
        "In this synthetic demonstration scenario the plant produced less than its baseline over the 21 days analysed, "
        "and the shortfall of 9.2 % in the assessment window is significant. The engine's result is Investigate. The "
        "pattern of the losses points to shading in the morning, but a material part of the loss is not explained and "
        "soiling is not shown."
    ),
    "performance_overview": (
        "The synthetic series shows an actual energy of 30.94 GWh against an expected 34.12 GWh, a gap of 9.3 % over "
        "the period and 9.2 % in the assessment window. The gap exceeds the materiality threshold of 3 %, so it is "
        "treated as significant."
    ),
    "anomalies": [
        "Losses are concentrated in the morning while midday is unaffected, which is typical of shading.",
        "8.7 % of the expected energy in the assessment window is not explained by any quantified factor.",
    ],
    "cause_interpretations": {
        "SHADING": "The engine gives shading moderate support: the morning pattern repeats day after day, but it is a "
                   "proxy until somebody confirms it on site.",
        "SOILING": "Soiling is not supported: the synthetic soiling channel indicates a near-clean array with a loss "
                   "of 0.6 %, which cannot explain the deviation.",
        "EQUIPMENT": "An equipment fault can be neither shown nor excluded, because no availability log and no "
                     "device-level energy are available.",
    },
    "data_quality_assessment": (
        "The synthetic data are complete for the analysed period and no blocking issue was found. Because every "
        "channel is synthetic, the result illustrates the method and does not describe a real plant."
    ),
    "economic_implications": (
        "No economic statement is possible: with a soiling loss of 0.6 % there is nothing material for a cleaning to "
        "bring back."
    ),
    "decision_rationale": (
        "The engine applied rule R4 because a significant loss is left unexplained. 5 of 10 gates are passed; the "
        "gates on credible soiling evidence and on its consistency with the gap are not."
    ),
    "uncertainty": [
        "The shading explanation rests on a pattern, not on a site observation.",
        "Equipment causes could not be evaluated for want of data.",
    ],
    "next_steps": [
        {"id": "N1", "why": "A site visit at the affected time of day is the only way to turn the shading pattern "
                            "into an observation."},
        {"id": "N4", "why": "The baseline depends on the irradiance sensor, so an error there would look like a loss."},
    ],
    "missing_information": [{"id": "M2", "why": "It would allow the engine to evaluate equipment causes."}],
    "limitations": ["The scenario is synthetic and its decision is simulated."],
}


def faithful(**changes: Any) -> str:
    """The faithful answer as the JSON text a model would send, with some fields replaced."""
    return json.dumps({**FAITHFUL_S05, **changes})


_SUPPORT_WORDS = {
    "STRONG": "strongly supported", "MODERATE": "moderately supported", "WEAK": "weakly supported",
    "NOT_SUPPORTED": "not supported", "NOT_EVALUABLE": "not evaluable",
}


def _anomalies(packet: dict[str, Any]) -> list[str]:
    """The anomalies the engine lists, each named in a sentence that adds nothing: a reading may word an anomaly in
    its own way, it may not pass it over."""
    named: list[str] = []
    if packet["technical_issues"]:
        named.append("The engine reports an open technical issue on the equipment in the assessment window.")
    if (packet["trend"].get("abrupt_drop") or {}).get("material"):
        named.append("The engine reports an abrupt drop of the performance index.")
    if any(conflict["severity"] == "CRITICAL" for conflict in packet["conflicts"]):
        named.append("The engine reports a critical contradiction between two pieces of evidence.")
    if packet["unexplained_residual"]["material"]:
        named.append("The engine reports that a material part of the gap is not explained by any quantified factor.")
    named += [
        f"The engine rates the explanation '{cause['title']}' as {_SUPPORT_WORDS[cause['engine_support']]} and present "
        "in the assessment window."
        for cause in packet["causes"]
        if cause["active_now"] and cause["category"] not in ("UNEXPLAINED", "DATA_QUALITY")
        and cause["engine_support"] in ("STRONG", "MODERATE")
    ]
    if packet["anomalies"] and not named:
        named.append("The engine lists an anomaly for this dataset; it is set out with the possible explanations.")
    return named


def scripted_model(body: dict[str, Any]) -> tuple[int, dict[str, str], Any]:
    """A stand-in model that keeps to the rules for any analysis: it restates what the packet says and no more.

    It reads the findings from the request, as a real model would, so the whole path - prompt, wire format,
    parsing, checks - is exercised without a hand-written answer per dataset.
    """
    packet = json.loads(body["messages"][1]["content"])
    label = packet["decision"]["label"]
    rule = packet["decision"]["rule"]
    synthetic = packet["evaluation"]["synthetic_data"]
    performance = packet["performance"]
    gates = packet["gates_summary"]
    figures = []
    if performance["gap_pct"] is not None:
        figures.append(f"the gap over the period is {performance['gap_pct']:.1f} %")
    if performance["window_gap_pct"] is not None:
        figures.append(f"the gap in the assessment window is {performance['window_gap_pct']:.1f} %")
    overview = ("In the findings " + " and ".join(figures) + ". ") if figures else "The findings state no gap. "
    estimated = packet["recoverable_energy"]["status"] == "ESTIMATED"
    answer = {
        "executive_summary": (
            f"The engine's result is {label}, issued under rule {rule}. This reading restates the findings of the "
            "engine for this dataset and adds no fact of its own. "
            + ("The data are synthetic, so the result illustrates the method only." if synthetic
               else "The result is decision support for qualified staff.")
        ),
        "performance_overview": overview + "The engine judges the significance of the gap from the declared uncertainties.",
        "anomalies": _anomalies(packet),
        "cause_interpretations": {
            cause["category"]: (
                f"The engine rates this explanation as {_SUPPORT_WORDS.get(cause['engine_support'], 'assessed by its factor status')}; "
                "this reading keeps to that rating and to the evidence listed."
            )
            for cause in packet["causes"]
        },
        "data_quality_assessment": (
            f"The engine reports the data quality as {packet['data']['quality'].lower()}. "
            + ("Every decisive channel is synthetic, which limits the result to an illustration." if synthetic
               else "The provenance of each channel is the one declared at import.")
        ),
        "economic_implications": (
            f"The engine holds an estimate and its economic verdict is {packet['economics']['verdict'].lower()}." if estimated
            else "No economic statement is possible, because the engine established no energy that a cleaning would bring back."
        ),
        "decision_rationale": (
            f"{gates['passed']} of {gates['total']} gates are passed, and rule {rule} is the first rule that applies. "
            f"The result is therefore {label}."
        ),
        "uncertainty": ["The reading inherits every limit of the engine's findings."],
        "next_steps": [{"id": c["id"], "why": "It is the first step the engine lists."}
                       for c in packet["candidates"]["next_steps"][:1]],
        "missing_information": [{"id": c["id"], "why": "It is the first missing input the engine lists."}
                                for c in packet["candidates"]["missing_information"][:1]],
        "limitations": ["This reading adds no fact to the engine's findings."],
    }
    return 200, {}, {"choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(answer)}}]}
