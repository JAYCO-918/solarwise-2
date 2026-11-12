"""Checks applied to a language model's answer before it may be shown.

The checks are deliberately strict and purely mechanical.  A rejected answer
costs nothing: the engine's own explanation is shown instead.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from solarwise.ai.packet import EvidencePacket

MAX_CHARS = 2_500
MIN_CHARS = 80

_NUMBER_WITH_DECIMALS = re.compile(r"(?<![A-Za-z_])\d[\d,]*(?:\.\d+)?")

#: Phrases that claim more certainty than the engine ever states.
_OVERCLAIM = re.compile(
    r"\b(guarantee[sd]?|certainly|definitely|undoubtedly|without (?:a |any )?doubt|proves? that|proven|"
    r"100\s?% (?:sure|certain)|probability|confidence (?:level|of)|likelihood of \d)",
    re.IGNORECASE,
)
#: Wording that tells the reader to clean.
_URGES_CLEANING = re.compile(
    r"\b(?:should|must|need(?:s)? to|ought to|recommend(?:s|ed)?(?: that you)?|advise[sd]?|time to|go ahead and|proceed (?:to|with))"
    r"\s+(?:be\s+)?(?:immediately\s+|now\s+|promptly\s+)?(?:clean(?:ed|ing)?|wash(?:ed|ing)?)\b"
    r"|\bclean(?:ing)? (?:is|was) (?:recommended|justified|warranted|required|needed|advised)\b",
    re.IGNORECASE,
)
#: Wording that tells the reader not to clean.
_DISCOURAGES_CLEANING = re.compile(
    r"\b(?:do not|don't|should not|shouldn't|no need to|not necessary to|unnecessary to) clean\b"
    r"|\bclean(?:ing)? is (?:not|un)\s?(?:recommended|justified|warranted|necessary|needed)\b",
    re.IGNORECASE,
)
_NEGATION_BEFORE = re.compile(r"\b(?:not|no|never|cannot|can't|without|neither|nor|whether)\b[^.;:!?]{0,60}$", re.IGNORECASE)
_URL = re.compile(r"https?://|www\.", re.IGNORECASE)
_MARKUP = re.compile(r"<[^>]+>|```|\[[^\]]+\]\([^)]+\)")
_ROLE_PLAY = re.compile(r"\b(?:as an ai|i am an ai|language model|system prompt|ignore (?:all|previous|the above))\b", re.IGNORECASE)


class GuardrailCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


def _number_allowed(token: str, allowed: list[float]) -> bool:
    """A quoted number must be one of the engine's figures, possibly rounded - never a new one."""
    cleaned = token.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError:
        return False
    decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
    tolerance = 0.5 * 10 ** (-decimals) + 1e-9
    return any(abs(candidate - value) <= tolerance for candidate in allowed)


def check_output(text: str, packet: EvidencePacket) -> list[GuardrailCheck]:
    checks: list[GuardrailCheck] = []
    stripped = text.strip()

    checks.append(
        GuardrailCheck(
            name="length", passed=MIN_CHARS <= len(stripped) <= MAX_CHARS,
            detail=f"{len(stripped)} characters (allowed {MIN_CHARS} to {MAX_CHARS})",
        )
    )

    unknown = [t for t in _NUMBER_WITH_DECIMALS.findall(stripped) if not _number_allowed(t, packet.allowed_numbers)]
    checks.append(
        GuardrailCheck(
            name="figures_from_engine_only", passed=not unknown,
            detail="every figure is one of the engine's" if not unknown
            else "figures that the engine did not produce: " + ", ".join(sorted(set(unknown))[:8]),
        )
    )

    overclaim = _OVERCLAIM.search(stripped)
    checks.append(
        GuardrailCheck(
            name="no_overclaiming", passed=overclaim is None,
            detail="" if overclaim is None else f"claims certainty the engine does not state: '{overclaim.group(0)}'",
        )
    )

    contradiction = ""
    if packet.decision != "CLEAN_NOW":
        for match in _URGES_CLEANING.finditer(stripped):
            if not _NEGATION_BEFORE.search(stripped[: match.start()]):
                contradiction = f"urges cleaning ('{match.group(0)}') although the engine decided {packet.decision}"
                break
    else:
        discouraged = _DISCOURAGES_CLEANING.search(stripped)
        if discouraged is not None:
            contradiction = f"discourages cleaning ('{discouraged.group(0)}') although the engine decided CLEAN_NOW"
    checks.append(GuardrailCheck(name="consistent_with_decision", passed=not contradiction, detail=contradiction))

    foreign = _URL.search(stripped) or _MARKUP.search(stripped) or _ROLE_PLAY.search(stripped)
    checks.append(
        GuardrailCheck(
            name="plain_text_only", passed=foreign is None,
            detail="" if foreign is None else f"contains a link, mark-up or meta-commentary: '{foreign.group(0)[:40]}'",
        )
    )
    return checks
