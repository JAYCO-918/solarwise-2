"""ARTIFICIAL response fixtures for the external-data clients.

These payloads were written by hand for the tests.  Their *structure* follows
the published response formats of the two services; their *values* are invented
and describe no real place or period.  The services themselves cannot be
reached from the test environment, and the tests never contact them.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def nasa_power_payload(
    start: date = date(2026, 5, 1), days: int = 10, *, fill_days: tuple[int, ...] = (), ghi_unit: str = "kW-hr/m^2/day",
) -> dict[str, Any]:
    """Shape of a NASA POWER ``/api/temporal/daily/point`` answer (JSON).  ARTIFICIAL values."""
    keys = [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]

    def series(base: float, step: float) -> dict[str, float]:
        return {key: (-999.0 if i in fill_days else round(base + step * i, 2)) for i, key in enumerate(keys)}

    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [6.8, 33.5, 80.0]},
        "properties": {
            "parameter": {
                "ALLSKY_SFC_SW_DWN": series(7.0, 0.05),
                "T2M": series(24.0, 0.3),
                "WS2M": series(3.0, 0.1),
                "RH2M": series(30.0, -0.5),
                "PRECTOTCORR": series(0.0, 0.0),
            }
        },
        "header": {
            "title": "NASA/POWER Source Native Resolution Daily Data",
            "api": {"version": "v0.0.0-artificial-fixture", "name": "POWER Daily API"},
            "fill_value": -999.0,
            "start": keys[0],
            "end": keys[-1],
        },
        "messages": [],
        "parameters": {
            "ALLSKY_SFC_SW_DWN": {"units": ghi_unit, "longname": "All Sky Surface Shortwave Downward Irradiance"},
            "T2M": {"units": "C", "longname": "Temperature at 2 Meters"},
            "WS2M": {"units": "m/s", "longname": "Wind Speed at 2 Meters"},
            "RH2M": {"units": "%", "longname": "Relative Humidity at 2 Meters"},
            "PRECTOTCORR": {"units": "mm/day", "longname": "Precipitation Corrected"},
        },
    }


def pvgis_payload(*, months: int = 12) -> dict[str, Any]:
    """Shape of a PVGIS ``PVcalc`` answer (``outputformat=json``).  ARTIFICIAL values."""
    return {
        "inputs": {
            "location": {"latitude": 33.5, "longitude": 6.8, "elevation": 80.0},
            "meteo_data": {"radiation_db": "ARTIFICIAL-FIXTURE-DB", "meteo_db": "ARTIFICIAL", "year_min": 2005,
                           "year_max": 2020, "use_horizon": True, "horizon_db": "DEM-calculated"},
            "mounting_system": {"fixed": {"slope": {"value": 30, "optimal": False},
                                          "azimuth": {"value": 0, "optimal": False}, "type": "free-standing"}},
            "pv_module": {"technology": "c-Si", "peak_power": 1.0, "system_loss": 14.0},
        },
        "outputs": {
            "monthly": {
                "fixed": [
                    {"month": m, "E_d": round(3.5 + 0.2 * m, 2), "E_m": round((3.5 + 0.2 * m) * 30, 1),
                     "H(i)_d": round(4.5 + 0.25 * m, 2), "H(i)_m": round((4.5 + 0.25 * m) * 30, 1), "SD_m": 5.0}
                    for m in range(1, months + 1)
                ]
            },
            "totals": {"fixed": {"E_d": 4.8, "E_m": 146.0, "E_y": 1752.0}},
        },
        "meta": {},
    }
