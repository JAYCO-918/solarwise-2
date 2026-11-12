"""Shared material for the service and API tests.

Every dataset built here is artificial and exists only to exercise the code.
Where a file is declared ``MEASURED`` it is so that the operational code path
can be tested; no real plant is described anywhere in this test suite.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from tests.builders import PLANT

ADMIN_EMAIL = "admin@example.org"
ADMIN_PASSWORD = "correct horse battery staple"
ENGINEER_EMAIL = "engineer@example.org"
ENGINEER_PASSWORD = "an engineer's long passphrase"
VIEWER_EMAIL = "viewer@example.org"
VIEWER_PASSWORD = "a viewer's long passphrase"

PLANT_PAYLOAD: dict[str, Any] = {"spec": PLANT.model_dump(mode="json"), "description": "Artificial test plant"}


def daily_csv(
    *, days: int = 30, start: date = date(2026, 5, 1), expected_kwh: float = 50_000.0, soiling_loss: float = 0.08,
    with_soiling_channel: bool = True, blank_actual_days: tuple[int, ...] = (),
) -> str:
    """Daily file: ``actual = expected x (1 - soiling_loss)``, with a soiling-ratio channel reporting that loss."""
    header = ["timestamp", "actual_energy_kwh", "expected_energy_kwh", "availability_fraction"]
    if with_soiling_channel:
        header.append("soiling_ratio")
    lines = [",".join(header)]
    for index in range(days):
        day = start + timedelta(days=index)
        actual = "" if index in blank_actual_days else f"{expected_kwh * (1.0 - soiling_loss):.3f}"
        row = [day.isoformat(), actual, f"{expected_kwh:.3f}", "1.0"]
        if with_soiling_channel:
            row.append(f"{1.0 - soiling_loss:.4f}")
        lines.append(",".join(row))
    return "\n".join(lines) + "\n"


def metadata(
    *, name: str = "Artificial test dataset", production: str = "MEASURED", with_soiling_channel: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    """Declarations for :func:`daily_csv`."""
    channels: dict[str, Any] = {
        "actual_energy": {"provenance": production, "source": "revenue meter (test fixture)", "uncertainty_pct": 0.5,
                          "boundary": "GRID_METER"},
        "expected_energy": {"provenance": "MODELLED", "source": "performance model (test fixture)",
                            "uncertainty_pct": 2.0, "boundary": "GRID_METER"},
        "availability": {"provenance": "MEASURED", "source": "SCADA availability log (test fixture)"},
    }
    if with_soiling_channel:
        channels["soiling_ratio"] = {
            "provenance": "MEASURED", "source": "soiling station (test fixture)", "uncertainty_abs": 0.005,
            "soiling_method": "SOILING_STATION",
        }
    payload: dict[str, Any] = {
        "name": name,
        "channels": channels,
        "baseline": {
            "method": "TELEMETRY_MODEL", "irradiance_adjusted": True, "temperature_adjusted": True,
            "degradation_adjusted": True, "soiling_allowance_fraction": 0.0,
        },
    }
    payload.update(extra)
    return payload


def upload_parts(csv_text: str, meta: dict[str, Any] | None = None, filename: str = "data.csv") -> dict[str, Any]:
    """Keyword arguments for ``client.post(..., **upload_parts(...))``."""
    return {
        "files": {"file": (filename, csv_text.encode(), "text/csv")},
        "data": {"metadata": json.dumps(meta if meta is not None else metadata())},
    }


#: Assumptions that make cleaning clearly profitable for :func:`daily_csv` (all of them test assumptions).
PROFITABLE_OPTIONS: dict[str, Any] = {
    "cleaning": {
        "cleaning_effectiveness": 0.9, "cleaning_effectiveness_low": 0.8, "cleaning_effectiveness_high": 1.0,
        "benefit_horizon_days": 30, "benefit_horizon_days_low": 24, "benefit_horizon_days_high": 36,
        "source_note": "test assumption",
    },
    "economics": {
        "currency": "DZD", "energy_value_per_kwh": 5.0, "energy_value_basis": "SELLING_PRICE",
        "energy_value_source": "test assumption", "water_cost": 10_000, "labour_cost": 60_000,
        "equipment_cost": 20_000, "operational_cost": 10_000, "downtime_cost": 0, "cost_uncertainty_pct": 20,
    },
}
