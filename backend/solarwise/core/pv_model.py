"""Photovoltaic engineering relations.

Everything here is a closed-form engineering calculation.  Outputs of the
temperature models and of :func:`expected_energy_kwh` are *modelled* quantities
and must be tagged accordingly by the caller; :func:`performance_ratio` applied
to measured inputs is a plain ratio of measurements.

References
----------
* IEC 61724-1:2021, *Photovoltaic system performance - Part 1: Monitoring*
  (reference yield, final yield, performance ratio, temperature-corrected
  performance ratio, soiling ratio).
* Ross (1976) / the NOCT approach for cell temperature.
* Faiman, D. (2008). Assessing the outdoor operating temperature of
  photovoltaic modules. *Prog. Photovolt.* 16, 307-315.
* Dobos, A. (2014). *PVWatts Version 5 Manual*, NREL/TP-6A20-62641
  (structure of the simple DC model used for the engineering estimate).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

#: Irradiance at Standard Test Conditions [kW/m2].
G_STC_KW_M2 = 1.0
#: Cell temperature at Standard Test Conditions [degC].
T_STC_C = 25.0
#: NOCT reference conditions: 800 W/m2 irradiance, 20 degC ambient.
_NOCT_IRRADIANCE_W_M2 = 800.0
_NOCT_AMBIENT_C = 20.0


def _finite(*values: float) -> bool:
    return all(math.isfinite(v) for v in values)


def cell_temperature_noct(ambient_c: float, irradiance_w_m2: float, noct_c: float = 45.0) -> float:
    """Cell temperature from the NOCT model [degC].

    ``T_cell = T_amb + (NOCT - 20) / 800 * G``.  Wind is not considered.
    """
    if not _finite(ambient_c, irradiance_w_m2, noct_c):
        raise ValueError("non-finite input")
    if irradiance_w_m2 < 0:
        raise ValueError("irradiance must be non-negative")
    return ambient_c + (noct_c - _NOCT_AMBIENT_C) / _NOCT_IRRADIANCE_W_M2 * irradiance_w_m2


def cell_temperature_faiman(
    ambient_c: float,
    irradiance_w_m2: float,
    wind_speed_ms: float,
    u0: float = 25.0,
    u1: float = 6.84,
) -> float:
    """Module temperature from the Faiman model [degC].

    ``T_mod = T_amb + G / (u0 + u1 * v)`` with ``u0`` [W m-2 K-1] and
    ``u1`` [W m-3 s K-1].  Defaults are the values reported by Faiman (2008).
    """
    if not _finite(ambient_c, irradiance_w_m2, wind_speed_ms, u0, u1):
        raise ValueError("non-finite input")
    if irradiance_w_m2 < 0 or wind_speed_ms < 0:
        raise ValueError("irradiance and wind speed must be non-negative")
    denominator = u0 + u1 * wind_speed_ms
    if denominator <= 0:
        raise ValueError("heat-loss coefficient must be positive")
    return ambient_c + irradiance_w_m2 / denominator


def temperature_factor(cell_temp_c: float, gamma_per_c: float) -> float:
    """Relative power at ``cell_temp_c`` versus STC: ``1 + gamma * (T - 25)``.

    ``gamma_per_c`` is the module power temperature coefficient (negative for
    all commercial technologies, e.g. ``-0.0035`` for -0.35 %/degC).
    """
    if not _finite(cell_temp_c, gamma_per_c):
        raise ValueError("non-finite input")
    return max(0.0, 1.0 + gamma_per_c * (cell_temp_c - T_STC_C))


def energy_weighted_irradiance_from_daily(irradiation_kwh_m2: float, daylight_h: float) -> float:
    """Energy-weighted mean irradiance [W/m2] of a day known only by its total.

    Assuming a half-sine irradiance profile ``G(t) = G_peak * sin(pi t / D)``
    over a day of length ``D``, the irradiance weighted by itself is
    ``int(G^2) / int(G) = (pi^2 / 8) * H / D``.  This is a *proxy* for clear
    days; it is used only when sub-daily data are unavailable.
    """
    if not _finite(irradiation_kwh_m2, daylight_h):
        raise ValueError("non-finite input")
    if irradiation_kwh_m2 < 0:
        raise ValueError("irradiation must be non-negative")
    if daylight_h <= 0:
        return 0.0
    return (math.pi**2 / 8.0) * irradiation_kwh_m2 * 1000.0 / daylight_h


def reference_yield_h(poa_irradiation_kwh_m2: float) -> float:
    """Reference yield Y_r [h] = in-plane irradiation / G_STC (IEC 61724-1)."""
    return poa_irradiation_kwh_m2 / G_STC_KW_M2


def performance_ratio(
    energy_kwh: float | None, capacity_kwp: float | None, poa_irradiation_kwh_m2: float | None
) -> float | None:
    """Performance ratio PR = Y_f / Y_r = E / (P0 * H_poa / G_STC) (IEC 61724-1).

    Returns ``None`` when any input is missing or the reference yield is zero.
    """
    if energy_kwh is None or capacity_kwp is None or poa_irradiation_kwh_m2 is None:
        return None
    if not _finite(energy_kwh, capacity_kwp, poa_irradiation_kwh_m2):
        return None
    if capacity_kwp <= 0 or poa_irradiation_kwh_m2 <= 0 or energy_kwh < 0:
        return None
    return energy_kwh / (capacity_kwp * reference_yield_h(poa_irradiation_kwh_m2))


def temperature_corrected_pr(
    energies_kwh: Sequence[float],
    poa_irradiations_kwh_m2: Sequence[float],
    cell_temps_c: Sequence[float],
    capacity_kwp: float,
    gamma_per_c: float,
) -> float | None:
    """Temperature-corrected performance ratio at STC (IEC 61724-1).

    ``PR_stc = sum(E_k) / sum(P0 * H_k / G_STC * (1 + gamma * (T_k - 25)))``
    """
    if not (len(energies_kwh) == len(poa_irradiations_kwh_m2) == len(cell_temps_c)):
        raise ValueError("input sequences must have equal length")
    if capacity_kwp <= 0:
        return None
    numerator = 0.0
    denominator = 0.0
    for energy, irradiation, temp in zip(energies_kwh, poa_irradiations_kwh_m2, cell_temps_c, strict=True):
        if not _finite(energy, irradiation, temp) or energy < 0 or irradiation < 0:
            raise ValueError("invalid interval value")
        numerator += energy
        denominator += capacity_kwp * reference_yield_h(irradiation) * temperature_factor(temp, gamma_per_c)
    if denominator <= 0:
        return None
    return numerator / denominator


def degradation_factor(years_in_operation: float, annual_rate: float) -> float:
    """Remaining relative power after ``years_in_operation`` at a constant annual rate."""
    if not _finite(years_in_operation, annual_rate):
        raise ValueError("non-finite input")
    if not 0.0 <= annual_rate < 1.0:
        raise ValueError("annual degradation rate must be within [0, 1)")
    return (1.0 - annual_rate) ** max(0.0, years_in_operation)


def expected_energy_kwh(
    capacity_kwp: float,
    poa_irradiation_kwh_m2: float,
    cell_temp_c: float,
    gamma_per_c: float,
    system_loss_fraction: float,
    degradation: float = 1.0,
    ac_limit_kwh: float | None = None,
) -> float:
    """Weather-adjusted engineering estimate of AC energy for one interval [kWh].

    ``E = P0 * (H_poa / G_STC) * (1 + gamma * (T_cell - 25)) * (1 - L_sys) * degradation``

    ``system_loss_fraction`` lumps every loss of a *clean, fully available*
    array other than temperature (wiring, mismatch, inverter and transformer
    efficiency, light-induced degradation ...).  Soiling is deliberately not
    part of it.  ``ac_limit_kwh`` caps the result at what the AC side can
    deliver during the interval (inverter clipping).
    """
    if not _finite(capacity_kwp, poa_irradiation_kwh_m2, cell_temp_c, gamma_per_c, system_loss_fraction):
        raise ValueError("non-finite input")
    if capacity_kwp <= 0:
        raise ValueError("capacity must be positive")
    if poa_irradiation_kwh_m2 < 0:
        raise ValueError("irradiation must be non-negative")
    if not 0.0 <= system_loss_fraction < 1.0:
        raise ValueError("system loss fraction must be within [0, 1)")
    if not 0.0 < degradation <= 1.0:
        raise ValueError("degradation factor must be within (0, 1]")
    energy = (
        capacity_kwp
        * reference_yield_h(poa_irradiation_kwh_m2)
        * temperature_factor(cell_temp_c, gamma_per_c)
        * (1.0 - system_loss_fraction)
        * degradation
    )
    if ac_limit_kwh is not None:
        energy = min(energy, max(0.0, ac_limit_kwh))
    return energy
