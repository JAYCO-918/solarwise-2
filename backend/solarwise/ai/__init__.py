"""Optional language-model layer.

The decision, every figure and every reason come from the deterministic engine.
A language model, when one is configured, is only asked to *rephrase* the
engine's explanation in plain language.  Its answer is checked against the
engine's own output before it is shown; if any check fails, or no model is
configured, or the provider cannot be reached, the engine's deterministic text
is used instead.
"""

from solarwise.ai.explain import AiExplanation, explain
from solarwise.ai.guardrails import GuardrailCheck, check_output
from solarwise.ai.packet import EvidencePacket, build_packet
from solarwise.ai.providers import Provider, ProviderError, build_provider

__all__ = [
    "AiExplanation",
    "EvidencePacket",
    "GuardrailCheck",
    "Provider",
    "ProviderError",
    "build_packet",
    "build_provider",
    "check_output",
    "explain",
]
