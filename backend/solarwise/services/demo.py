"""Seeding of the demonstration: the synthetic reference case and its ten scenarios."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from solarwise.core.pipeline import AnalysisOptions
from solarwise.db.models import Dataset, Device, Plant, PlantPermission, PlantRole, User
from solarwise.demo.generator import DEFAULT_SEED, REFERENCE_DEVICES, REFERENCE_PLANT
from solarwise.demo.run import parse_scenario
from solarwise.demo.scenarios import Scenario, build_all
from solarwise.services import analysis as analysis_service
from solarwise.services import datasets as dataset_service
from solarwise.services import evidence as evidence_service

DEMO_PLANT_DESCRIPTION = (
    "Demonstration plant. Name, location and nominal capacity refer to a public reference case; every technical "
    "parameter is an illustrative assumption and every dataset attached to it is synthetic. Nothing here "
    "describes the operation of a real plant."
)


def scenario_payload(scenario: Scenario) -> dict[str, Any]:
    """What the interface needs to present a scenario and pre-fill its assumptions."""
    return {
        "key": scenario.key,
        "number": scenario.number,
        "title": scenario.title,
        "story": scenario.story,
        "injected": scenario.injected,
        "expected_decision": scenario.expected_decision,
        "expected_rule": scenario.expected_rule,
        "expected_diagnostic_status": scenario.expected_diagnostic_status,
        "cleaning": scenario.cleaning.model_dump(mode="json") if scenario.cleaning is not None else None,
        "economics": scenario.economics.model_dump(mode="json") if scenario.economics is not None else None,
        "seed": DEFAULT_SEED,
    }


def demo_plant(db: Session) -> Plant | None:
    """The shared demonstration plant: the one created by the seeding, not by a visitor."""
    return db.scalar(
        select(Plant)
        .where(Plant.is_demonstration.is_(True), Plant.created_by_id.is_(None), Plant.name == REFERENCE_PLANT.name)
        .order_by(Plant.id)
    )


def seed_demo(db: Session) -> dict[str, int]:
    """Create the demonstration plant, its datasets and their analyses.  Safe to call repeatedly."""
    plant = demo_plant(db)
    created = {"plants": 0, "datasets": 0, "analyses": 0}
    if plant is None:
        plant = Plant(
            name=REFERENCE_PLANT.name,
            description=DEMO_PLANT_DESCRIPTION,
            capacity_dc_kwp=REFERENCE_PLANT.capacity_dc_kwp,
            latitude=REFERENCE_PLANT.latitude,
            longitude=REFERENCE_PLANT.longitude,
            timezone=REFERENCE_PLANT.timezone,
            is_demonstration=True,
            spec=REFERENCE_PLANT.model_dump(mode="json"),
        )
        db.add(plant)
        db.flush()
        for device in REFERENCE_DEVICES:
            db.add(
                Device(plant_id=plant.id, code=device.code, kind=device.kind, capacity_kwp=device.capacity_kwp,
                       description="Hypothetical block of the demonstration layout")
            )
        created["plants"] = 1
    db.flush()

    existing = {
        key for key in db.scalars(select(Dataset.scenario_key).where(Dataset.plant_id == plant.id)) if key is not None
    }
    for scenario in build_all():
        if scenario.key in existing:
            continue
        report, parsed = parse_scenario(scenario)
        digest = hashlib.sha256(
            json.dumps({"scenario": scenario.key, "seed": DEFAULT_SEED, "rows": scenario.rows}, sort_keys=True, default=str).encode()
        ).hexdigest()
        dataset = dataset_service.store_parsed(
            db, plant, None, parsed=parsed, report=report, content_sha256=digest,
            file_name=f"{scenario.key}.json", scenario_key=scenario.key, default_options=scenario_payload(scenario),
        )
        for record in scenario.evidence:
            evidence_service.add_evidence(db, plant, None, record, dataset)
        db.flush()
        options = AnalysisOptions(cleaning=scenario.cleaning, economics=scenario.economics)
        analysis_service.run_and_store(db, None, plant, dataset, options)
        created["datasets"] += 1
        created["analyses"] += 1
    return created


def grant_demo_access(db: Session, user: User) -> Plant | None:
    """Let a demonstration visitor read the shared demonstration plant.

    Read-only on purpose: visitors may run analyses with their own assumptions
    (kept private to their session) but cannot change the plant, its datasets
    or its evidence, which every other visitor sees.
    """
    plant = demo_plant(db)
    if plant is None:
        return None
    present = db.scalar(
        select(PlantPermission.id).where(PlantPermission.plant_id == plant.id, PlantPermission.user_id == user.id)
    )
    if present is None:
        db.add(PlantPermission(plant_id=plant.id, user_id=user.id, role=PlantRole.VIEWER.value))
    return plant
