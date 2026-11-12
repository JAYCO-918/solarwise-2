"""Plants, devices, access and PVGIS typical-year data."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from solarwise.api.deps import CurrentUser, DbSession, client_address
from solarwise.api.errors import ApiError
from solarwise.api.schemas import (
    DeviceIn,
    DeviceOut,
    PermissionIn,
    PermissionOut,
    PlantCreate,
    PlantOut,
    PlantUpdate,
    PvgisManual,
)
from solarwise.db.models import Dataset, Device, Plant, PlantPermission, PlantRole, User
from solarwise.services import analysis as analysis_service
from solarwise.services import audit
from solarwise.services import plants as plant_service
from solarwise.services import users as user_service
from solarwise.services.errors import NotFoundError

router = APIRouter(tags=["plants"])


def _out(db: DbSession, user: User, plant: Plant, role: str) -> PlantOut:
    datasets = db.scalar(
        select(func.count()).select_from(Dataset).where(Dataset.plant_id == plant.id, Dataset.archived.is_(False))
    )
    devices = db.scalar(select(func.count()).select_from(Device).where(Device.plant_id == plant.id))
    return PlantOut.of(
        plant, role, dataset_count=int(datasets or 0), device_count=int(devices or 0),
        latest=analysis_service.latest_for_plant(db, user, plant),
    )


@router.get("/plants", response_model=list[PlantOut], summary="Plants the account may see")
def list_plants(user: CurrentUser, db: DbSession) -> list[PlantOut]:
    return [_out(db, user, plant, role) for plant, role in plant_service.list_plants(db, user)]


@router.post("/plants", response_model=PlantOut, status_code=201, summary="Register a plant")
def create_plant(body: PlantCreate, user: CurrentUser, db: DbSession, request: Request) -> PlantOut:
    plant = plant_service.create_plant(db, user, body.spec, body.description)
    audit.record(db, "PLANT_CREATED", user=user, entity="plant", entity_id=plant.id, remote_address=client_address(request))
    return _out(db, user, plant, PlantRole.OWNER.value)


@router.get("/plants/{plant_id}", response_model=PlantOut, summary="One plant")
def get_plant(plant_id: int, user: CurrentUser, db: DbSession) -> PlantOut:
    plant = plant_service.get_plant(db, user, plant_id)
    return _out(db, user, plant, plant_service.plant_role(db, user, plant) or PlantRole.VIEWER.value)


@router.patch("/plants/{plant_id}", response_model=PlantOut, summary="Change the description of a plant")
def update_plant(plant_id: int, body: PlantUpdate, user: CurrentUser, db: DbSession, request: Request) -> PlantOut:
    plant = plant_service.get_plant(db, user, plant_id, write=True)
    plant_service.update_plant(db, user, plant, body.spec, body.description)
    audit.record(db, "PLANT_UPDATED", user=user, entity="plant", entity_id=plant.id,
                 detail={"fields": sorted(body.spec)}, remote_address=client_address(request))
    db.flush()
    return _out(db, user, plant, plant_service.plant_role(db, user, plant) or PlantRole.VIEWER.value)


@router.delete("/plants/{plant_id}", status_code=204, summary="Delete a plant with its datasets and analyses")
def delete_plant(plant_id: int, user: CurrentUser, db: DbSession, request: Request) -> Response:
    plant = plant_service.get_plant(db, user, plant_id, owner=True)
    audit.record(db, "PLANT_DELETED", user=user, entity="plant", entity_id=plant.id, detail={"name": plant.name},
                 remote_address=client_address(request))
    db.delete(plant)
    return Response(status_code=204)


# --------------------------------------------------------------------------- devices


@router.get("/plants/{plant_id}/devices", response_model=list[DeviceOut], summary="Devices of a plant")
def list_devices(plant_id: int, user: CurrentUser, db: DbSession) -> list[DeviceOut]:
    plant = plant_service.get_plant(db, user, plant_id)
    return [DeviceOut.of(d) for d in plant_service.list_devices(db, plant)]


@router.post("/plants/{plant_id}/devices", response_model=DeviceOut, status_code=201, summary="Register a device")
def add_device(plant_id: int, body: DeviceIn, user: CurrentUser, db: DbSession) -> DeviceOut:
    plant = plant_service.get_plant(db, user, plant_id, write=True)
    device = plant_service.add_device(
        db, plant, code=body.code, capacity_kwp=body.capacity_kwp, kind=body.kind, description=body.description
    )
    return DeviceOut.of(device)


@router.delete("/plants/{plant_id}/devices/{device_id}", status_code=204, summary="Remove a device")
def delete_device(plant_id: int, device_id: int, user: CurrentUser, db: DbSession) -> Response:
    plant = plant_service.get_plant(db, user, plant_id, write=True)
    device = db.get(Device, device_id)
    if device is None or device.plant_id != plant.id:
        raise NotFoundError("device not found")
    db.delete(device)
    return Response(status_code=204)


# --------------------------------------------------------------------------- access


@router.get("/plants/{plant_id}/permissions", response_model=list[PermissionOut], summary="Who may access a plant")
def list_permissions(plant_id: int, user: CurrentUser, db: DbSession) -> list[PermissionOut]:
    plant = plant_service.get_plant(db, user, plant_id, owner=True)
    rows = db.execute(
        select(PlantPermission, User).join(User, User.id == PlantPermission.user_id)
        .where(PlantPermission.plant_id == plant.id).order_by(User.email)
    )
    return [PermissionOut(user_id=u.id, email=u.email, full_name=u.full_name, role=p.role) for p, u in rows]


@router.put("/plants/{plant_id}/permissions", response_model=PermissionOut, summary="Grant or change access")
def set_permission(plant_id: int, body: PermissionIn, user: CurrentUser, db: DbSession, request: Request) -> PermissionOut:
    plant = plant_service.get_plant(db, user, plant_id, owner=True)
    target = user_service.get_by_email(db, body.email)
    if target is None or target.is_demo:
        raise NotFoundError("no account with this e-mail address")
    permission = db.scalar(
        select(PlantPermission).where(PlantPermission.plant_id == plant.id, PlantPermission.user_id == target.id)
    )
    if permission is None:
        permission = PlantPermission(plant_id=plant.id, user_id=target.id, role=body.role)
        db.add(permission)
    else:
        permission.role = body.role
    audit.record(db, "PERMISSION_SET", user=user, entity="plant", entity_id=plant.id,
                 detail={"user_id": target.id, "role": body.role}, remote_address=client_address(request))
    return PermissionOut(user_id=target.id, email=target.email, full_name=target.full_name, role=body.role)


@router.delete("/plants/{plant_id}/permissions/{user_id}", status_code=204, summary="Withdraw access")
def delete_permission(plant_id: int, user_id: int, user: CurrentUser, db: DbSession) -> Response:
    plant = plant_service.get_plant(db, user, plant_id, owner=True)
    permission = db.scalar(
        select(PlantPermission).where(PlantPermission.plant_id == plant.id, PlantPermission.user_id == user_id)
    )
    if permission is None:
        raise NotFoundError("permission not found")
    owners = db.scalar(
        select(func.count()).select_from(PlantPermission)
        .where(PlantPermission.plant_id == plant.id, PlantPermission.role == PlantRole.OWNER.value)
    )
    if permission.role == PlantRole.OWNER.value and int(owners or 0) <= 1:
        raise ApiError(409, "CONFLICT", "a plant must keep at least one owner")
    db.delete(permission)
    return Response(status_code=204)


# --------------------------------------------------------------------------- PVGIS typical year (manual entry)


@router.put("/plants/{plant_id}/pvgis", response_model=PlantOut, summary="Store PVGIS monthly averages entered by hand")
def set_pvgis(plant_id: int, body: PvgisManual, user: CurrentUser, db: DbSession) -> PlantOut:
    plant = plant_service.get_plant(db, user, plant_id, write=True)
    plant_service.set_pvgis(db, plant, body.months, f"{body.source} (entered manually)")
    db.flush()
    return _out(db, user, plant, plant_service.plant_role(db, user, plant) or PlantRole.VIEWER.value)
