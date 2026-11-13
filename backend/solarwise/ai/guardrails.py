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


# --------------------------------------------------------------------------- the analyst's narrative

#: Total length of an analyst's narrative, every field together.
MAX_NARRATIVE_CHARS = 9_000
MIN_NARRATIVE_CHARS = 200

#: Words that turn a claim into its opposite or into a hypothesis, when they stand before it in the same clause.
_HEDGE_BEFORE = re.compile(
    r"\b(?:not|no|never|nothing|none|nobody|cannot|can't|couldn't|without|neither|nor|whether|if|unless|may|might|could|possibly|"
    r"would|unlikely|rather than|instead of|absence of|lack of|insufficient|does not|do not|did not|is not|are not|"
    r"was not|were not|has not|have not)\b[^.;:!?]{0,80}$",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
_DECIMAL_POINT = re.compile(r"(?<=\d)\.(?=\d)")


def _sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_END.split(text) if part.strip()]

#: Soiling stated as a fact.  Only allowed when the engine holds credible measured soiling evidence.
_SOILING_ASSERTED = re.compile(
    r"\bsoiling (?:is|was|has been|is now|is clearly|is therefore|is indeed) "
    r"(?:confirmed|established|proven|verified|demonstrated|present|responsible|the (?:main |primary |likely |root |only )?cause)\b"
    r"|\b(?:confirmed|established|proven|verified|demonstrated) soiling\b"
    r"|\b(?:caused by|due to|because of|attributable to|a result of|explained by|driven by|stems from|comes from) "
    r"(?:the |heavy |significant |severe |module |panel |accumulated |dust and |)*(?:soiling|dust|dirt)\b"
    r"|\b(?:modules|panels|array|arrays) (?:are|is) (?:dirty|soiled|heavily soiled|dusty)\b"
    r"|\bsoiling (?:explains|accounts for|causes|is causing|caused|reduced|is reducing|has reduced)\b"
    r"|\bdust (?:accumulation|deposition|build-?up) (?:explains|accounts for|causes|is causing|has caused|caused|reduced)\b",
    re.IGNORECASE,
)
#: Claims that the method or the result was proven on a real installation.
_VALIDATION_CLAIM = re.compile(
    r"\b(?:validated|verified|proven|tested|confirmed|demonstrated|calibrated) (?:on|at|with|against|in|by) "
    r"(?:a |an |the |real |actual |operating |operational |field |several |many |)*"
    r"(?:plants?|sites?|field|installations?|real data|operational data|real[- ]world|practice)\b"
    r"|\bfield[- ]validated\b|\breal[- ]world validation\b|\bproven in the field\b|\bbankable\b",
    re.IGNORECASE,
)
#: A confirmation that is asked for is the opposite of one that is claimed: "until confirmed on site", "must be
#: verified on site".  The marker has to stand right before the word (two words at most in between), so that "it
#: should be noted that the method was validated on real plants" is still a claim.  "Once" and "when" are left out
#: on purpose: "once validated on real plants, the method was adopted" claims a validation.
_STILL_TO_BE_DONE = re.compile(
    r"\b(?:until|pending|to be|should be|must be|needs? to be|has to be|have to be|remains? to be|yet to be|"
    r"still to be)\s+(?:\w+\s+){0,2}$",
    re.IGNORECASE,
)
#: Another probability vocabulary than the engine's ordinal support levels.
_PROBABILITY = re.compile(
    r"\b(?:guarantee[sd]?|certainly|definitely|undoubtedly|without (?:a |any )?doubt|100\s?% (?:sure|certain)|"
    r"probability|likelihood of \d|confidence (?:level|of|interval)|\d+\s?% (?:likely|chance|probability|confidence|certain)|"
    r"proves? that|proven)\b",
    re.IGNORECASE,
)
_DECISION_NAMED = re.compile(
    r"\b(?:decision|recommendation|recommends?|recommended|result|outcome|verdict|conclusion|concludes?|decided|decides)\b"
    r"[^.;:!?]{0,60}?\b(clean[ -]now|monitor|investigate)\b",
    re.IGNORECASE,
)
_MEASUREMENT_WORD = re.compile(r"\bmeasure(?:d|ment|ments)\b", re.IGNORECASE)
_SYNTHETIC_WORD = re.compile(
    r"\b(?:synthetic|simulat\w+|demonstration|artificial|emulat\w+|illustrative|stand[- ]in|generated)\b", re.IGNORECASE
)
_RECOVER_WORD = re.compile(r"\brecover\w*\b", re.IGNORECASE)
_DIGIT = re.compile(r"\d")
_OPERATIONAL_CLAIM = re.compile(
    r"\b(?:authori[sz]e[sd]?|authori[sz]ation (?:is|was) (?:granted|given)|go ahead|field work (?:can|may|should) "
    r"(?:start|begin|proceed)|operational (?:instruction|order)|dispatch (?:the |a )?(?:crew|team))\b",
    re.IGNORECASE,
)
_LABEL = {"CLEAN_NOW": "clean now", "MONITOR": "monitor", "INVESTIGATE": "investigate"}


def _first_unhedged(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    """First match of ``pattern`` that no negation or hedge precedes in its clause."""
    for match in pattern.finditer(text):
        if not _HEDGE_BEFORE.search(text[: match.start()]):
            return match
    return None


def check_narrative(
    text: str, *, decision: str, allowed_numbers: list[float], soiling_confirmed: bool, recoverable_estimated: bool,
    synthetic: bool, simulated: bool, operational_authorization: bool,
) -> list[GuardrailCheck]:
    """Checks applied to everything an analyst model wrote, before any of it may be shown.

    Strict on purpose: a rejected narrative costs nothing - the engine's own text is shown instead.
    """
    checks: list[GuardrailCheck] = []
    original = text.strip()
    # Clauses are told apart by their punctuation: a decimal point must not end one.  Same length, same positions.
    stripped = _DECIMAL_POINT.sub("\u00b7", original)

    checks.append(
        GuardrailCheck(
            name="length", passed=MIN_NARRATIVE_CHARS <= len(stripped) <= MAX_NARRATIVE_CHARS,
            detail=f"{len(stripped)} characters (allowed {MIN_NARRATIVE_CHARS} to {MAX_NARRATIVE_CHARS})",
        )
    )

    unknown = [t for t in _NUMBER_WITH_DECIMALS.findall(original) if not _number_allowed(t, allowed_numbers)]
    checks.append(
        GuardrailCheck(
            name="figures_from_engine_only", passed=not unknown,
            detail="every figure is one of the engine's" if not unknown
            else "figures that the engine did not produce: " + ", ".join(sorted(set(unknown))[:8]),
        )
    )

    probability = _first_unhedged(_PROBABILITY, stripped)
    checks.append(
        GuardrailCheck(
            name="no_overclaiming", passed=probability is None,
            detail="" if probability is None else f"claims certainty the engine does not state: '{probability.group(0)}'",
        )
    )

    contradiction = ""
    if decision != "CLEAN_NOW":
        for match in _URGES_CLEANING.finditer(stripped):
            if not _HEDGE_BEFORE.search(stripped[: match.start()]):
                contradiction = f"urges cleaning ('{match.group(0)}') although the engine decided {decision}"
                break
    else:
        discouraged = _DISCOURAGES_CLEANING.search(stripped)
        if discouraged is not None:
            contradiction = f"discourages cleaning ('{discouraged.group(0)}') although the engine decided CLEAN_NOW"
    if not contradiction:
        for match in _DECISION_NAMED.finditer(stripped):
            named = match.group(1).lower().replace("-", " ")
            if named != _LABEL[decision] and not _HEDGE_BEFORE.search(stripped[: match.start(1)]):
                contradiction = f"names another decision ('{match.group(0)[:70]}') than the engine's {decision}"
                break
    checks.append(GuardrailCheck(name="consistent_with_decision", passed=not contradiction, detail=contradiction))

    asserted = None if soiling_confirmed else _first_unhedged(_SOILING_ASSERTED, stripped)
    checks.append(
        GuardrailCheck(
            name="soiling_not_asserted_without_measurement", passed=asserted is None,
            detail=("credible measured soiling evidence exists" if soiling_confirmed else "soiling is not stated as a fact")
            if asserted is None
            else f"states soiling as a fact ('{asserted.group(0)}') although no credible measured soiling evidence exists",
        )
    )

    recoverable = ""
    if not recoverable_estimated:
        for sentence in _sentences(stripped):
            if _RECOVER_WORD.search(sentence) and _DIGIT.search(sentence):
                quoted = sentence.strip()[:70].replace("\u00b7", ".")
                recoverable = f"quotes a figure for recoverable energy ('{quoted}') although the engine estimated none"
                break
    checks.append(GuardrailCheck(name="no_recoverable_energy_without_estimate", passed=not recoverable, detail=recoverable))

    relabelled = ""
    if synthetic:
        for sentence in _sentences(stripped):
            word = _MEASUREMENT_WORD.search(sentence)
            if word is not None and not _SYNTHETIC_WORD.search(sentence) and not _HEDGE_BEFORE.search(sentence[: word.start()]):
                quoted = sentence.strip()[:70].replace("\u00b7", ".")
                relabelled = f"speaks of measurements ('{quoted}') although the data are synthetic"
                break
    checks.append(GuardrailCheck(name="synthetic_not_called_measured", passed=not relabelled, detail=relabelled))

    validation = next(
        (
            match for match in _VALIDATION_CLAIM.finditer(stripped)
            if not _HEDGE_BEFORE.search(stripped[: match.start()]) and not _STILL_TO_BE_DONE.search(stripped[: match.start()])
        ),
        None,
    )
    operational = None
    if simulated or not operational_authorization:
        operational = _first_unhedged(_OPERATIONAL_CLAIM, stripped)
    overreach = validation or operational
    checks.append(
        GuardrailCheck(
            name="no_validation_or_authorisation_claim", passed=overreach is None,
            detail="" if overreach is None
            else f"claims a validation or an authorisation that does not exist: '{overreach.group(0)[:60]}'",
        )
    )

    foreign = _URL.search(stripped) or _MARKUP.search(stripped) or _ROLE_PLAY.search(stripped)
    checks.append(
        GuardrailCheck(
            name="plain_text_only", passed=foreign is None,
            detail="" if foreign is None else f"contains a link, mark-up or meta-commentary: '{foreign.group(0)[:40]}'",
        )
    )
    return checks
