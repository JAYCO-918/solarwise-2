"""Unit handling.

SolarWise stores every quantity in one canonical unit per physical dimension
and converts explicitly at the system boundary (imports, API inputs).  A unit
that is not recognised, or a conversion between different dimensions, raises
:class:`UnitError` - the engines never guess.

Canonical units
---------------
energy        kWh            irradiation   kWh/m2
power         kW             irradiance    W/m2
temperature   degC           speed         m/s
ratio         fraction       precipitation mm
area          m2             volume        m3
"""

from __future__ import annotations

import math
from dataclasses import dataclass


class UnitError(ValueError):
    """Raised for unknown units and for conversions between dimensions."""


@dataclass(frozen=True)
class _Unit:
    dimension: str
    canonical: str
    #: canonical = value * scale + offset
    scale: float
    offset: float = 0.0


_UNITS: dict[str, _Unit] = {
    # --- energy -> kWh
    "wh": _Unit("energy", "kWh", 1e-3),
    "kwh": _Unit("energy", "kWh", 1.0),
    "mwh": _Unit("energy", "kWh", 1e3),
    "gwh": _Unit("energy", "kWh", 1e6),
    "j": _Unit("energy", "kWh", 1.0 / 3.6e6),
    "kj": _Unit("energy", "kWh", 1.0 / 3.6e3),
    "mj": _Unit("energy", "kWh", 1.0 / 3.6),
    # --- power -> kW
    "w": _Unit("power", "kW", 1e-3),
    "kw": _Unit("power", "kW", 1.0),
    "mw": _Unit("power", "kW", 1e3),
    "wp": _Unit("power", "kW", 1e-3),
    "kwp": _Unit("power", "kW", 1.0),
    "mwp": _Unit("power", "kW", 1e3),
    # --- irradiation -> kWh/m2
    "wh/m2": _Unit("irradiation", "kWh/m2", 1e-3),
    "kwh/m2": _Unit("irradiation", "kWh/m2", 1.0),
    "mj/m2": _Unit("irradiation", "kWh/m2", 1.0 / 3.6),
    "j/m2": _Unit("irradiation", "kWh/m2", 1.0 / 3.6e6),
    # --- irradiance -> W/m2
    "w/m2": _Unit("irradiance", "W/m2", 1.0),
    "kw/m2": _Unit("irradiance", "W/m2", 1e3),
    # --- temperature -> degC
    "degc": _Unit("temperature", "degC", 1.0),
    "k": _Unit("temperature", "degC", 1.0, -273.15),
    "degf": _Unit("temperature", "degC", 5.0 / 9.0, -32.0 * 5.0 / 9.0),
    # --- speed -> m/s
    "m/s": _Unit("speed", "m/s", 1.0),
    "km/h": _Unit("speed", "m/s", 1.0 / 3.6),
    # --- ratio -> fraction
    "fraction": _Unit("ratio", "fraction", 1.0),
    "percent": _Unit("ratio", "fraction", 0.01),
    # --- precipitation depth -> mm
    "mm": _Unit("precipitation", "mm", 1.0),
    "cm": _Unit("precipitation", "mm", 10.0),
    "in": _Unit("precipitation", "mm", 25.4),
    # --- area -> m2
    "m2": _Unit("area", "m2", 1.0),
    "ha": _Unit("area", "m2", 1e4),
    "km2": _Unit("area", "m2", 1e6),
    # --- volume -> m3
    "l": _Unit("volume", "m3", 1e-3),
    "m3": _Unit("volume", "m3", 1.0),
}

_ALIASES: dict[str, str] = {
    "°c": "degc",
    "c": "degc",
    "celsius": "degc",
    "deg c": "degc",
    "°f": "degf",
    "f": "degf",
    "fahrenheit": "degf",
    "kelvin": "k",
    "%": "percent",
    "pct": "percent",
    "-": "fraction",
    "1": "fraction",
    "ratio": "fraction",
    "kwh/m²": "kwh/m2",
    "wh/m²": "wh/m2",
    "mj/m²": "mj/m2",
    "j/m²": "j/m2",
    "w/m²": "w/m2",
    "kw/m²": "kw/m2",
    "kw-hr/m^2": "kwh/m2",
    "kwh/m^2": "kwh/m2",
    "mj/m^2": "mj/m2",
    "w/m^2": "w/m2",
    "ms": "m/s",
    "m s-1": "m/s",
    "kph": "km/h",
    "kmh": "km/h",
    "m²": "m2",
    "m^2": "m2",
    "m³": "m3",
    "m^3": "m3",
    "litre": "l",
    "liter": "l",
    "litres": "l",
    "liters": "l",
    "inch": "in",
}


def _lookup(symbol: str) -> _Unit:
    if not isinstance(symbol, str) or not symbol.strip():
        raise UnitError("unit is missing")
    key = symbol.strip().lower()
    key = _ALIASES.get(key, key)
    unit = _UNITS.get(key)
    if unit is None:
        raise UnitError(f"unknown unit '{symbol}'")
    return unit


def accepted_units() -> dict[str, dict[str, object]]:
    """Per dimension: the canonical unit and every unit symbol that is understood."""
    out: dict[str, dict[str, object]] = {}
    for symbol, unit in _UNITS.items():
        entry = out.setdefault(unit.dimension, {"canonical": unit.canonical, "accepted": []})
        accepted = entry["accepted"]
        assert isinstance(accepted, list)
        accepted.append(symbol)
    return out


def dimension_of(symbol: str) -> str:
    """Physical dimension of ``symbol`` (``energy``, ``temperature`` ...)."""
    return _lookup(symbol).dimension


def canonical_unit(symbol: str) -> str:
    """Canonical unit of the dimension ``symbol`` belongs to."""
    return _lookup(symbol).canonical


def to_canonical(value: float, unit: str, *, expected_dimension: str | None = None) -> float:
    """Convert ``value`` expressed in ``unit`` to the canonical unit of its dimension."""
    u = _lookup(unit)
    if expected_dimension is not None and u.dimension != expected_dimension:
        raise UnitError(
            f"unit '{unit}' has dimension '{u.dimension}', expected '{expected_dimension}'"
        )
    if not math.isfinite(value):
        raise UnitError("cannot convert a non-finite value")
    return value * u.scale + u.offset


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert between two units of the same dimension."""
    src, dst = _lookup(from_unit), _lookup(to_unit)
    if src.dimension != dst.dimension:
        raise UnitError(
            f"cannot convert '{from_unit}' ({src.dimension}) to '{to_unit}' ({dst.dimension})"
        )
    canonical = to_canonical(value, from_unit)
    return (canonical - dst.offset) / dst.scale
