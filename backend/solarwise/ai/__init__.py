"""The language-model layer: interpretation and explanation above the engineering pipeline.

The decision, every gate, every figure and every piece of evidence come from the
deterministic engine.  A language model, when one is configured, reads that
result and writes:

* a *diagnostic analysis* and an *operational report* (:mod:`solarwise.ai.analyst`,
  :mod:`solarwise.ai.report`): what the findings mean, how the evidence weighs for
  and against each possible cause, what is uncertain or missing, and what
  matters most among the steps the engine proposed;
* a *plain-language rewording* of the engine's explanation (:mod:`solarwise.ai.explain`);
* *suggestions for the mapping of an uploaded file* (:mod:`solarwise.ai.data_assist`).

It never decides, never supplies a fact, and never acts.  Whatever it writes is
checked against the engine's result before it is shown; if a check fails, if no
model is configured or if the provider cannot be reached, the engine's own
deterministic text is used instead, and the page says so.
"""

from solarwise.ai.analyst import Insight, deterministic_insight, generate_insight
from solarwise.ai.data_assist import DataReview, review_data
from solarwise.ai.explain import AiExplanation, explain
from solarwise.ai.guardrails import GuardrailCheck, check_narrative, check_output
from solarwise.ai.packet import AnalystPacket, EvidencePacket, build_analyst_packet, build_packet
from solarwise.ai.providers import Provider, ProviderError, build_provider
from solarwise.ai.report import build_operational_report, render_operational_json

__all__ = [
    "AiExplanation",
    "AnalystPacket",
    "DataReview",
    "EvidencePacket",
    "GuardrailCheck",
    "Insight",
    "Provider",
    "ProviderError",
    "build_analyst_packet",
    "build_operational_report",
    "build_packet",
    "build_provider",
    "check_narrative",
    "check_output",
    "deterministic_insight",
    "explain",
    "generate_insight",
    "render_operational_json",
    "review_data",
]
