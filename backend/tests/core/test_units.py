"""Unit conversion: explicit, dimension-checked, never guessed."""

from __future__ import annotations

import math

import pytest

from solarwise.core.units import UnitError, canonical_unit, convert, dimension_of, to_canonical


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (1.0, "MWh", 1000.0),
        (2500.0, "Wh", 2.5),
        (3.6, "MJ", 1.0),
        (1.0, "GWh", 1_000_000.0),
        (36.0, "MJ/m2", 10.0),
        (5500.0, "Wh/m2", 5.5),
        (300.15, "K", 27.0),
        (77.0, "degF", 25.0),
        (36.0, "km/h", 10.0),
        (95.0, "%", 0.95),
        (1.0, "in", 25.4),
    ],
)
def test_conversion_to_canonical(value: float, unit: str, expected: float) -> None:
    assert to_canonical(value, unit) == pytest.approx(expected, rel=1e-12)


def test_round_trip() -> None:
    assert convert(convert(1234.5, "kWh", "MJ"), "MJ", "kWh") == pytest.approx(1234.5)
    assert convert(25.0, "degC", "degF") == pytest.approx(77.0)
    assert convert(25.0, "degC", "K") == pytest.approx(298.15)


def test_aliases_and_case() -> None:
    assert dimension_of("kWh/m²") == "irradiation"
    assert canonical_unit("°C") == "degC"
    assert to_canonical(1.0, " mwh ") == 1000.0


def test_unknown_unit_is_rejected() -> None:
    with pytest.raises(UnitError, match="unknown unit"):
        to_canonical(1.0, "furlong")


def test_missing_unit_is_rejected() -> None:
    with pytest.raises(UnitError, match="missing"):
        to_canonical(1.0, "  ")


def test_cross_dimension_conversion_is_rejected() -> None:
    with pytest.raises(UnitError, match="cannot convert"):
        convert(1.0, "kWh", "kW")


def test_expected_dimension_is_enforced() -> None:
    # Power is not energy: a kW value must not be read as kWh.
    with pytest.raises(UnitError, match="expected 'energy'"):
        to_canonical(5.0, "kW", expected_dimension="energy")


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_values_are_rejected(bad: float) -> None:
    with pytest.raises(UnitError, match="non-finite"):
        to_canonical(bad, "kWh")
