"""Plants, devices and who may see or change them."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from solarwise.core.baseline import PvgisMonth
from solarwise.core.models import DeviceSpec, PlantSpec
from solarwise.core.timeline import TimelineError, get_zone
from solarwise.db.models import Device, Plant, PlantPermission, PlantRole, Role, User
from solarwise.services.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError

_WRITE_ROLES = {PlantRole.OWNER.value, PlantRole.EDITOR.value}
#: Plants a demonstration session may register.
DEMO_MAX_PLANTS = 3


def plant_role(db: Session, user: User, plant: Plant) -> str | None:
    """The user's role on ``plant`` (administrators own every plant)."""
    if user.role == Role.ADMIN.value:
        return PlantRole.OWNER.value
    return db.scalar(
        select(PlantPermission.role).where(PlantPermission.plant_id == plant.id, PlantPermission.user_id == user.id)
    )


def list_plants(db: Session, user: User) -> list[tuple[Plant, str]]:
    if user.role == Role.ADMIN.value:
        return [(p, PlantRole.OWNER.value) for p in db.scalars(select(Plant).order_by(Plant.name))]
    rows = db.execute(
        select(Plant, PlantPermission.role)
        .join(PlantPermission, PlantPermission.plant_id == Plant.id)
        .where(PlantPermission.user_id == user.id)
        .order_by(Plant.name)
    )
    return [(plant, role) for plant, role in rows]


def get_plant(db: Session, user: User, plant_id: int, *, write: bool = False, owner: bool = False) -> Plant:
    """Fetch a plant the user may access.  Unknown and inaccessible plants are indistinguishable."""
    plant = db.get(Plant, plant_id)
    role = plant_role(db, user, plant) if plant is not None else None
    if plant is None or role is None:
        raise NotFoundError("plant not found")
    if write or owner:
        if user.role == Role.VIEWER.value:
            raise ForbiddenError("your account is read-only")
        if owner and role != PlantRole.OWNER.value:
            raise ForbiddenError("only an owner of the plant may do this")
        if role not in _WRITE_ROLES:
            raise ForbiddenError("you have read-only access to this plant")
    return plant


def spec_of(plant: Plant) -> PlantSpec:
    return PlantSpec.model_validate(plant.spec)


def _check_spec(spec: PlantSpec) -> None:
    try:
        get_zone(spec.timezone)
    except TimelineError as exc:
        raise InvalidError(str(exc), code="UNKNOWN_TIMEZONE") from exc


def _apply_spec(plant: Plant, spec: PlantSpec) -> None:
    plant.name = spec.name
    plant.capacity_dc_kwp = spec.capacity_dc_kwp
    plant.latitude = spec.latitude
    plant.longitude = spec.longitude
    plant.timezone = spec.timezone
    plant.is_demonstration = spec.is_demonstration
    plant.spec = spec.model_dump(mode="json")


def create_plant(db: Session, user: User, spec: PlantSpec, description: str = "") -> Plant:
    if user.role == Role.VIEWER.value:
        raise ForbiddenError("your account is read-only")
    if user.is_demo:
        # Whatever a demonstration visitor creates is a demonstration object.
        spec = spec.model_copy(update={"is_demonstration": True})
        owned = db.scalar(select(func.count()).select_from(Plant).where(Plant.created_by_id == user.id))
        if int(owned or 0) >= DEMO_MAX_PLANTS:
            raise ConflictError(
                f"a demonstration session may register at most {DEMO_MAX_PLANTS} plants", code="DEMO_LIMIT"
            )
    _check_spec(spec)
    plant = Plant(description=description, created_by_id=user.id, spec={}, name="", capacity_dc_kwp=0.0,
                  latitude=0.0, longitude=0.0, timezone="UTC")
    _apply_spec(plant, spec)
    db.add(plant)
    db.flush()
    db.add(PlantPermission(plant_id=plant.id, user_id=user.id, role=PlantRole.OWNER.value))
    db.flush()
    return plant


def update_plant(db: Session, user: User, plant: Plant, changes: dict[str, Any], description: str | None) -> Plant:
    merged = {**plant.spec, **changes}
    if user.is_demo or plant.is_demonstration:
        merged["is_demonstration"] = True  # one-way: a demonstration plant never becomes an operational one
    try:
        spec = PlantSpec.model_validate(merged)
    except ValidationError as exc:
        raise InvalidError("invalid plant description", details=exc.errors(include_url=False, include_context=False)) from exc
    _check_spec(spec)
    _apply_spec(plant, spec)
    if description is not None:
        plant.description = description
    return plant


def set_pvgis(db: Session, plant: Plant, months: list[PvgisMonth], source: str) -> None:
    if sorted(m.month for m in months) != list(range(1, 13)):
        raise InvalidError("PVGIS monthly averages must cover each of the 12 months exactly once")
    plant.pvgis_monthly = [m.model_dump(mode="json") for m in months]
    plant.pvgis_source = source[:500]


# --------------------------------------------------------------------------- devices


def list_devices(db: Session, plant: Plant) -> list[Device]:
    return list(db.scalars(select(Device).where(Device.plant_id == plant.id).order_by(Device.code)))


def device_specs(db: Session, plant: Plant) -> dict[str, DeviceSpec]:
    return {d.code: DeviceSpec(code=d.code, capacity_kwp=d.capacity_kwp, kind=d.kind) for d in list_devices(db, plant)}


def add_device(db: Session, plant: Plant, *, code: str, capacity_kwp: float, kind: str, description: str) -> Device:
    code = code.strip()
    if not code:
        raise InvalidError("the device code is empty")
    if db.scalar(select(Device.id).where(Device.plant_id == plant.id, Device.code == code)) is not None:
        raise ConflictError(f"device '{code}' already exists for this plant", code="DEVICE_EXISTS")
    device = Device(plant_id=plant.id, code=code, capacity_kwp=capacity_kwp, kind=kind, description=description)
    db.add(device)
    db.flush()
    return device
