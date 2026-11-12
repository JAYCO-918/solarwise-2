"""Services: accounts, access to plants, datasets, evidence, analyses, references, demonstration."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from solarwise.core.models import EvidenceRecord, EvidenceType, InspectionFinding
from solarwise.core.pipeline import AnalysisOptions
from solarwise.core.provenance import EvaluationContext, measured
from solarwise.db.base import utcnow
from solarwise.db.models import Analysis, Dataset, DatasetKind, Plant, PlantPermission, PlantRole, Role, User
from solarwise.demo.scenarios import SCENARIO_KEYS
from solarwise.services import analysis as analysis_service
from solarwise.services import datasets as dataset_service
from solarwise.services import demo as demo_service
from solarwise.services import evidence as evidence_service
from solarwise.services import plants as plant_service
from solarwise.services import reference as reference_service
from solarwise.services import users as user_service
from solarwise.services.errors import ConflictError, ForbiddenError, InvalidError, NotFoundError, ServiceError
from tests import support
from tests.builders import PLANT
from tests.conftest import make_settings

PASSWORD = "a long and unusual passphrase"


def make_user(db: Session, email: str, role: Role = Role.ENGINEER) -> User:
    return user_service.create_user(db, email=email, password=PASSWORD, role=role)


def import_csv(db: Session, plant: Plant, user: User, csv_text: str, meta: dict[str, Any] | None = None) -> Dataset:
    checked = dataset_service.check_upload(
        db, plant, data=csv_text.encode(), filename="data.csv", content_type="text/csv",
        metadata_json=json.dumps(meta if meta is not None else support.metadata()),
    )
    assert checked.report.accepted, checked.report.summary
    return dataset_service.import_upload(db, plant, user, checked, "data.csv")


# --------------------------------------------------------------------------- accounts


def test_email_is_normalised_and_unique(db: Session) -> None:
    user = make_user(db, "  Mixed.Case@Example.ORG ")
    assert user.email == "mixed.case@example.org"
    with pytest.raises(ConflictError) as raised:
        make_user(db, "mixed.case@example.org")
    assert raised.value.code == "EMAIL_TAKEN"


@pytest.mark.parametrize("email", ["", "no-at-sign", "two@@example.org", "space in@example.org", "a@b"])
def test_invalid_email_is_refused(db: Session, email: str) -> None:
    with pytest.raises(InvalidError) as raised:
        make_user(db, email)
    assert raised.value.code == "INVALID_EMAIL"


def test_weak_password_is_refused(db: Session) -> None:
    with pytest.raises(InvalidError) as raised:
        user_service.create_user(db, email="x@example.org", password="short")
    assert raised.value.code == "WEAK_PASSWORD"


def test_password_is_never_stored_in_clear(db: Session) -> None:
    user = make_user(db, "x@example.org")
    assert user.password_hash is not None and PASSWORD not in user.password_hash


def test_authentication_succeeds_and_records_the_login(db: Session) -> None:
    make_user(db, "x@example.org")
    user = user_service.authenticate(db, make_settings(), email="X@example.org", password=PASSWORD)
    assert user.last_login_at is not None and user.failed_logins == 0


@pytest.mark.safety
def test_every_failed_sign_in_looks_the_same(db: Session) -> None:
    """Unknown account, wrong password and disabled account must be indistinguishable."""
    make_user(db, "known@example.org")
    disabled = make_user(db, "disabled@example.org")
    disabled.is_active = False
    settings = make_settings()
    outcomes = set()
    for email, password in (
        ("unknown@example.org", PASSWORD), ("known@example.org", "the wrong passphrase"), ("disabled@example.org", PASSWORD),
    ):
        with pytest.raises(ServiceError) as raised:
            user_service.authenticate(db, settings, email=email, password=password)
        outcomes.add((raised.value.status_code, raised.value.code, raised.value.message))
    assert outcomes == {(401, "INVALID_CREDENTIALS", "e-mail address or password is incorrect")}


@pytest.mark.safety
def test_account_locks_after_repeated_failures_even_for_the_right_password(db: Session) -> None:
    make_user(db, "x@example.org")
    settings = make_settings(login_max_attempts=3, login_lockout_seconds=600)
    for _ in range(3):
        with pytest.raises(ServiceError):
            user_service.authenticate(db, settings, email="x@example.org", password="the wrong passphrase")
    with pytest.raises(ServiceError) as raised:
        user_service.authenticate(db, settings, email="x@example.org", password=PASSWORD)
    assert (raised.value.status_code, raised.value.code) == (429, "ACCOUNT_LOCKED")

    user = user_service.get_by_email(db, "x@example.org")
    assert user is not None
    user.locked_until = utcnow() - timedelta(seconds=1)  # the lock expires
    assert user_service.authenticate(db, settings, email="x@example.org", password=PASSWORD).id == user.id


@pytest.mark.safety
def test_a_demonstration_account_cannot_sign_in_with_a_password(db: Session) -> None:
    visitor = user_service.create_demo_session(db)
    assert visitor.is_demo and visitor.password_hash is None
    assert visitor.email.endswith("@solarwise.invalid")
    for password in ("", "password", PASSWORD):
        with pytest.raises(ServiceError):
            user_service.authenticate(db, make_settings(), email=visitor.email, password=password)


@pytest.mark.safety
def test_an_account_created_by_its_own_user_is_an_engineer_and_never_an_administrator(db: Session) -> None:
    user = user_service.register_user(db, email="  New.Person@Example.org ", password=PASSWORD, full_name=" New Person ")
    assert user.role == Role.ENGINEER.value == user_service.SELF_REGISTERED_ROLE.value
    assert user.email == "new.person@example.org" and user.full_name == "New Person"
    assert not user.is_demo and user.is_active and user.last_login_at is not None
    assert user.password_hash is not None and PASSWORD not in user.password_hash
    assert user_service.authenticate(db, make_settings(), email="new.person@example.org", password=PASSWORD).id == user.id
    assert user_service.count_administrators(db) == 0


@pytest.mark.safety
@pytest.mark.parametrize(
    ("email", "password", "code"),
    [
        ("someone@solarwise.invalid", PASSWORD, "INVALID_EMAIL"),  # the domain of demonstration sessions
        ("not-an-address", PASSWORD, "INVALID_EMAIL"),
        ("someone@example.org", "too short", "WEAK_PASSWORD"),
        ("someone@example.org", "aaaaaaaaaaaaaaaa", "WEAK_PASSWORD"),
    ],
)
def test_sign_up_applies_the_rules_of_every_account(db: Session, email: str, password: str, code: str) -> None:
    with pytest.raises(InvalidError) as refused:
        user_service.register_user(db, email=email, password=password, full_name="Someone")
    assert refused.value.code == code
    assert db.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.safety
def test_sign_up_never_takes_over_an_existing_account(db: Session) -> None:
    owner = make_user(db, "owner@example.org")
    before = owner.password_hash
    with pytest.raises(ConflictError) as refused:
        user_service.register_user(db, email="OWNER@example.org", password="another long passphrase", full_name="Impostor")
    assert refused.value.code == "EMAIL_TAKEN"
    assert owner.password_hash == before and owner.full_name == ""


@pytest.mark.safety
def test_the_first_administrator_is_created_although_other_accounts_exist(db: Session) -> None:
    """With sign-up open, people can have accounts before the installation has an administrator."""
    user_service.register_user(db, email="early@example.org", password=PASSWORD, full_name="Early Bird")
    user_service.create_demo_session(db)
    admin = user_service.bootstrap_administrator(db, email="root@example.org", password=PASSWORD)
    assert admin is not None and admin.role == Role.ADMIN.value
    assert user_service.count_administrators(db) == 1


@pytest.mark.safety
def test_the_bootstrap_values_are_ignored_once_an_administrator_exists(db: Session) -> None:
    make_user(db, "first@example.org", Role.ADMIN)
    assert user_service.bootstrap_administrator(db, email="second@example.org", password=PASSWORD) is None
    assert user_service.get_by_email(db, "second@example.org") is None
    # Not even for the same address: the password of an existing administrator is never replaced.
    assert user_service.bootstrap_administrator(db, email="first@example.org", password="a different passphrase") is None
    assert user_service.authenticate(db, make_settings(), email="first@example.org", password=PASSWORD)


@pytest.mark.safety
def test_an_account_that_took_the_administrators_address_is_not_promoted(db: Session) -> None:
    squatter = user_service.register_user(db, email="root@example.org", password=PASSWORD, full_name="Squatter")
    with pytest.raises(ConflictError):
        user_service.bootstrap_administrator(db, email="root@example.org", password="the real administrator's passphrase")
    assert squatter.role == Role.ENGINEER.value
    assert user_service.count_administrators(db) == 0
    assert user_service.authenticate(db, make_settings(), email="root@example.org", password=PASSWORD).id == squatter.id


def test_each_demonstration_visit_gets_its_own_account(db: Session) -> None:
    first, second = user_service.create_demo_session(db), user_service.create_demo_session(db)
    assert first.id != second.id and first.email != second.email
    assert user_service.count_administrators(db) == 0


def test_expired_demonstration_sessions_are_removed_with_what_they_created(db: Session) -> None:
    keeper = make_user(db, "keeper@example.org")
    kept_plant = plant_service.create_plant(db, keeper, PLANT)
    old, fresh = user_service.create_demo_session(db), user_service.create_demo_session(db)
    old_plant = plant_service.create_plant(db, old, PLANT)
    import_csv(db, old_plant, old, support.daily_csv(days=5))
    fresh_plant = plant_service.create_plant(db, fresh, PLANT)
    old.created_at = utcnow() - timedelta(hours=25)
    db.commit()

    assert user_service.purge_demo_sessions(db) == 1
    db.commit()
    remaining_plants = set(db.scalars(select(Plant.id)))
    assert remaining_plants == {kept_plant.id, fresh_plant.id}
    assert db.get(User, old.id) is None and db.get(User, fresh.id) is not None
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0


def test_the_number_of_live_demonstration_sessions_is_bounded(db: Session) -> None:
    visitors = [user_service.create_demo_session(db) for _ in range(5)]
    for age, visitor in enumerate(visitors):
        visitor.created_at = utcnow() - timedelta(minutes=age)  # visitors[0] is the newest
    db.commit()
    assert user_service.purge_demo_sessions(db, keep_at_most=2) == 3
    db.commit()
    assert set(db.scalars(select(User.id))) == {visitors[0].id, visitors[1].id}


# --------------------------------------------------------------------------- plants and access


def test_creator_owns_the_plant_and_others_cannot_see_it(db: Session) -> None:
    owner, other = make_user(db, "owner@example.org"), make_user(db, "other@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    assert plant_service.plant_role(db, owner, plant) == PlantRole.OWNER.value
    assert plant_service.list_plants(db, other) == []
    with pytest.raises(NotFoundError):  # not 'forbidden': existence is not revealed
        plant_service.get_plant(db, other, plant.id)
    with pytest.raises(NotFoundError):
        plant_service.get_plant(db, other, 424242)


def test_administrators_see_every_plant(db: Session) -> None:
    owner, admin = make_user(db, "owner@example.org"), make_user(db, "admin@example.org", Role.ADMIN)
    plant = plant_service.create_plant(db, owner, PLANT)
    assert [p.id for p, _ in plant_service.list_plants(db, admin)] == [plant.id]
    assert plant_service.get_plant(db, admin, plant.id, owner=True).id == plant.id


def test_read_only_accounts_and_roles_cannot_write(db: Session) -> None:
    owner = make_user(db, "owner@example.org")
    viewer_account = make_user(db, "viewer@example.org", Role.VIEWER)
    plant_viewer = make_user(db, "plantviewer@example.org")
    editor = make_user(db, "editor@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    db.add_all([
        PlantPermission(plant_id=plant.id, user_id=viewer_account.id, role=PlantRole.OWNER.value),
        PlantPermission(plant_id=plant.id, user_id=plant_viewer.id, role=PlantRole.VIEWER.value),
        PlantPermission(plant_id=plant.id, user_id=editor.id, role=PlantRole.EDITOR.value),
    ])
    db.flush()
    with pytest.raises(ForbiddenError):  # a read-only account stays read-only whatever its plant role
        plant_service.get_plant(db, viewer_account, plant.id, write=True)
    with pytest.raises(ForbiddenError):
        plant_service.get_plant(db, plant_viewer, plant.id, write=True)
    assert plant_service.get_plant(db, plant_viewer, plant.id).id == plant.id
    assert plant_service.get_plant(db, editor, plant.id, write=True).id == plant.id
    with pytest.raises(ForbiddenError):
        plant_service.get_plant(db, editor, plant.id, owner=True)
    with pytest.raises(ForbiddenError):
        plant_service.create_plant(db, viewer_account, PLANT)


def test_unknown_time_zone_is_refused(db: Session) -> None:
    with pytest.raises(InvalidError) as raised:
        plant_service.create_plant(db, make_user(db, "o@example.org"), PLANT.model_copy(update={"timezone": "Mars/Olympus"}))
    assert raised.value.code == "UNKNOWN_TIMEZONE"


def test_update_validates_the_merged_description(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    plant_service.update_plant(db, owner, plant, {"tilt_deg": 25.0, "name": "Renamed"}, "new description")
    assert (plant.name, plant.spec["tilt_deg"], plant.description) == ("Renamed", 25.0, "new description")
    with pytest.raises(InvalidError):
        plant_service.update_plant(db, owner, plant, {"capacity_dc_kwp": -5}, None)
    assert plant.capacity_dc_kwp == PLANT.capacity_dc_kwp


@pytest.mark.safety
def test_whatever_a_demonstration_visitor_registers_is_a_demonstration_plant(db: Session) -> None:
    visitor = user_service.create_demo_session(db)
    plant = plant_service.create_plant(db, visitor, PLANT.model_copy(update={"is_demonstration": False}))
    assert plant.is_demonstration is True and plant.spec["is_demonstration"] is True
    plant_service.update_plant(db, visitor, plant, {"is_demonstration": False}, None)
    assert plant.is_demonstration is True


@pytest.mark.safety
def test_the_demonstration_flag_is_one_way_even_for_an_administrator(db: Session) -> None:
    admin = make_user(db, "admin@example.org", Role.ADMIN)
    plant = plant_service.create_plant(db, admin, PLANT.model_copy(update={"is_demonstration": True}))
    plant_service.update_plant(db, admin, plant, {"is_demonstration": False}, None)
    assert plant.is_demonstration is True


def test_demonstration_sessions_are_limited_in_what_they_can_store(db: Session) -> None:
    visitor = user_service.create_demo_session(db)
    plants = [plant_service.create_plant(db, visitor, PLANT) for _ in range(plant_service.DEMO_MAX_PLANTS)]
    with pytest.raises(ConflictError) as raised:
        plant_service.create_plant(db, visitor, PLANT)
    assert raised.value.code == "DEMO_LIMIT"
    for index in range(dataset_service.DEMO_MAX_DATASETS):
        import_csv(db, plants[0], visitor, support.daily_csv(days=5), support.metadata(name=f"dataset {index}"))
    with pytest.raises(ConflictError) as raised:
        import_csv(db, plants[0], visitor, support.daily_csv(days=5), support.metadata(name="one too many"))
    assert raised.value.code == "DEMO_LIMIT"


def test_device_codes_are_unique_per_plant(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    plant_service.add_device(db, plant, code=" INV-1 ", capacity_kwp=100.0, kind="INVERTER", description="")
    with pytest.raises(ConflictError):
        plant_service.add_device(db, plant, code="INV-1", capacity_kwp=100.0, kind="INVERTER", description="")
    assert list(plant_service.device_specs(db, plant)) == ["INV-1"]


def test_pvgis_months_must_cover_the_year(db: Session) -> None:
    from solarwise.core.baseline import PvgisMonth

    plant = plant_service.create_plant(db, make_user(db, "o@example.org"), PLANT)
    months = [PvgisMonth(month=m, e_d_kwh_per_kwp=4.0, h_i_d_kwh_m2=5.0) for m in range(1, 12)]
    with pytest.raises(InvalidError):
        plant_service.set_pvgis(db, plant, [*months, months[0]], "test")
    plant_service.set_pvgis(db, plant, [*months, PvgisMonth(month=12, e_d_kwh_per_kwp=3.0, h_i_d_kwh_m2=4.0)], "test")
    assert plant.pvgis_monthly is not None and len(plant.pvgis_monthly) == 12


# --------------------------------------------------------------------------- datasets


def test_checking_an_upload_stores_nothing(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    checked = dataset_service.check_upload(
        db, plant, data=support.daily_csv().encode(), filename="data.csv", content_type="text/csv",
        metadata_json=json.dumps(support.metadata()),
    )
    assert checked.report.accepted and checked.duplicate_of is None
    assert db.scalar(select(func.count()).select_from(Dataset)) == 0


def test_import_is_refused_for_a_duplicate_and_for_a_rejected_file(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    first = import_csv(db, plant, owner, support.daily_csv())
    with pytest.raises(ConflictError) as duplicate:
        import_csv(db, plant, owner, support.daily_csv())
    assert duplicate.value.code == "DUPLICATE_DATASET"
    assert duplicate.value.details == {"dataset_id": first.id}

    # Same bytes, different declarations: a different dataset.
    other = import_csv(db, plant, owner, support.daily_csv(), support.metadata(production="UNKNOWN"))
    assert other.id != first.id and other.content_sha256 != first.content_sha256

    bad = dataset_service.check_upload(
        db, plant, data=b"timestamp,actual_energy_kwh\nnot-a-date,5\n", filename="bad.csv", content_type="text/csv",
        metadata_json=None,
    )
    assert not bad.report.accepted
    with pytest.raises(InvalidError) as rejected:
        dataset_service.import_upload(db, plant, owner, bad, "bad.csv")
    assert rejected.value.code == "VALIDATION_FAILED"


@pytest.mark.parametrize(
    ("raw", "code"),
    [("{not json", "INVALID_METADATA"), ("[1, 2]", "INVALID_METADATA"), ('{"name": "x", "surprise": 1}', "INVALID_METADATA")],
)
def test_malformed_metadata_is_refused(db: Session, raw: str, code: str) -> None:
    plant = plant_service.create_plant(db, make_user(db, "o@example.org"), PLANT)
    with pytest.raises(InvalidError) as raised:
        dataset_service.check_upload(db, plant, data=support.daily_csv().encode(), filename="d.csv",
                                     content_type="text/csv", metadata_json=raw)
    assert raised.value.code == code


def test_unreadable_file_is_refused(db: Session) -> None:
    plant = plant_service.create_plant(db, make_user(db, "o@example.org"), PLANT)
    with pytest.raises(InvalidError) as raised:
        dataset_service.check_upload(db, plant, data=b"\x00\x01\x02binary", filename="d.csv", content_type="text/csv",
                                     metadata_json=None)
    assert raised.value.code == "UNREADABLE_FILE"


@pytest.mark.safety
def test_without_declarations_nothing_is_assumed_about_the_origin(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    checked = dataset_service.check_upload(db, plant, data=support.daily_csv().encode(), filename="d.csv",
                                           content_type="text/csv", metadata_json=None)
    dataset = dataset_service.import_upload(db, plant, owner, checked, "d.csv")
    assert {meta.tag.provenance.value for meta in dataset_service.channels_of(dataset).values()} == {"UNKNOWN"}


def test_weather_only_file_becomes_a_weather_dataset_that_cannot_be_analysed_alone(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    csv_text = "timestamp,ghi_kwh_m2,ambient_temp_c\n" + "".join(f"2026-05-{d:02d},7.1,24.5\n" for d in range(1, 11))
    meta = {"name": "weather", "channels": {
        "ghi": {"provenance": "MODELLED", "source": "reanalysis (test fixture)", "plane": "GHI"},
        "ambient_temp": {"provenance": "MODELLED", "source": "reanalysis (test fixture)"},
    }}
    dataset = import_csv(db, plant, owner, csv_text, meta)
    assert dataset.kind == DatasetKind.WEATHER.value
    loaded = dataset_service.load_observations(db, dataset).observations
    assert len(loaded) == 10 and loaded[0].ghi_kwh_m2 == 7.1 and loaded[0].actual_energy_kwh is None
    with pytest.raises(InvalidError) as raised:
        analysis_service.build_input(db, owner, plant, dataset, AnalysisOptions())
    assert raised.value.code == "NOT_A_PRODUCTION_DATASET"


def test_weather_dataset_fills_only_the_channels_the_production_dataset_lacks(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    production = import_csv(db, plant, owner, support.daily_csv(days=10))
    weather_csv = "timestamp,ghi_kwh_m2\n" + "".join(f"2026-05-{d:02d},{6.0 + d / 10}\n" for d in range(1, 9))
    weather = import_csv(db, plant, owner, weather_csv, {"name": "weather", "channels": {
        "ghi": {"provenance": "MODELLED", "source": "reanalysis (test fixture)", "plane": "GHI"}}})
    inp = analysis_service.build_input(db, owner, plant, production, AnalysisOptions(), weather)
    values = [o.ghi_kwh_m2 for o in inp.observations]
    assert values[:8] == [pytest.approx(6.0 + d / 10) for d in range(1, 9)]
    assert values[8:] == [None, None]  # days the weather dataset does not cover stay missing
    from solarwise.core.models import Metric

    assert inp.channels[Metric.GHI].tag.provenance.value == "MODELLED"
    assert inp.channels[Metric.ACTUAL_ENERGY].tag.provenance.value == "MEASURED"


def test_series_payload_is_column_oriented_in_canonical_units(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    dataset = import_csv(db, plant, owner, support.daily_csv(days=4, blank_actual_days=(1,)))
    payload = dataset_service.series_payload(db, dataset)
    assert set(payload["columns"]) == {"actual_energy_kwh", "expected_energy_kwh", "availability_fraction", "soiling_ratio"}
    assert payload["columns"]["actual_energy_kwh"][1] is None
    assert payload["units"]["actual_energy_kwh"] == "kWh"
    assert len(payload["start_utc"]) == 4 and payload["truncated"] is False


# --------------------------------------------------------------------------- evidence


def _inspection(reference: str = "INSP-1") -> EvidenceRecord:
    return EvidenceRecord(
        reference=reference, evidence_type=EvidenceType.VISUAL_INSPECTION,
        observed_start=datetime(2026, 5, 28, tzinfo=UTC), tag=measured("site visit (test fixture)"),
        description="visual inspection", finding=InspectionFinding.SOILING_HEAVY,
    )


def test_evidence_references_are_unique_per_plant(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    evidence_service.add_evidence(db, plant, owner, _inspection())
    with pytest.raises(ConflictError) as raised:
        evidence_service.add_evidence(db, plant, owner, _inspection())
    assert raised.value.code == "EVIDENCE_REFERENCE_TAKEN"


def test_evidence_attached_to_a_dataset_applies_to_that_dataset_only(db: Session) -> None:
    owner = make_user(db, "o@example.org")
    plant = plant_service.create_plant(db, owner, PLANT)
    first = import_csv(db, plant, owner, support.daily_csv(), support.metadata(name="first"))
    second = import_csv(db, plant, owner, support.daily_csv(), support.metadata(name="second"))
    evidence_service.add_evidence(db, plant, owner, _inspection("PLANT-WIDE"))
    evidence_service.add_evidence(db, plant, None, _inspection("ONLY-FIRST"), first)
    assert {r.reference for r in evidence_service.records_for(db, plant, first)} == {"PLANT-WIDE", "ONLY-FIRST"}
    assert {r.reference for r in evidence_service.records_for(db, plant, second)} == {"PLANT-WIDE"}
    assert len(evidence_service.list_evidence(db, plant, everything=True)) == 2


# --------------------------------------------------------------------------- analyses


@pytest.mark.safety
def test_the_evaluation_context_is_decided_from_the_plant_and_the_account(db: Session) -> None:
    engineer = make_user(db, "e@example.org")
    visitor = user_service.create_demo_session(db)
    real = plant_service.create_plant(db, engineer, PLANT)
    demo = plant_service.create_plant(db, engineer, PLANT.model_copy(update={"is_demonstration": True}))
    assert analysis_service.evaluation_context(engineer, real) is EvaluationContext.OPERATIONAL
    assert analysis_service.evaluation_context(engineer, demo) is EvaluationContext.DEMONSTRATION
    assert analysis_service.evaluation_context(visitor, real) is EvaluationContext.DEMONSTRATION
    assert analysis_service.evaluation_context(None, demo) is EvaluationContext.DEMONSTRATION


def _options() -> AnalysisOptions:
    return AnalysisOptions.model_validate(support.PROFITABLE_OPTIONS)


def test_an_analysis_is_stored_whole_and_can_be_read_back_identically(db: Session) -> None:
    engineer = make_user(db, "e@example.org")
    plant = plant_service.create_plant(db, engineer, PLANT)
    dataset = import_csv(db, plant, engineer, support.daily_csv())
    analysis, result = analysis_service.run_and_store(db, engineer, plant, dataset, _options())
    db.commit()
    db.expire_all()

    stored = db.get(Analysis, analysis.id)
    assert stored is not None
    assert analysis_service.stored_result(stored).model_dump() == result.model_dump()
    assert stored.decision == result.recommendation.decision.value == "CLEAN_NOW"
    assert stored.rule == "R3" and stored.simulated is False and stored.operational_authorization is True
    assert stored.engine_version == result.engine_version
    assert AnalysisOptions.model_validate(stored.options) == _options()
    assert stored.gap_pct == pytest.approx(8.0)


@pytest.mark.safety
def test_the_same_measured_file_in_a_demonstration_session_is_only_a_simulation(db: Session) -> None:
    visitor = user_service.create_demo_session(db)
    plant = plant_service.create_plant(db, visitor, PLANT)
    dataset = import_csv(db, plant, visitor, support.daily_csv())
    analysis, result = analysis_service.run_and_store(db, visitor, plant, dataset, _options())
    assert analysis.decision == "CLEAN_NOW"
    assert analysis.simulated is True and analysis.operational_authorization is False
    assert analysis.headline.startswith("SIMULATED DECISION")
    assert result.context is EvaluationContext.DEMONSTRATION


@pytest.mark.safety
def test_synthetic_production_never_yields_clean_now_on_an_operational_plant(db: Session) -> None:
    engineer = make_user(db, "e@example.org")
    plant = plant_service.create_plant(db, engineer, PLANT)
    meta = support.metadata(
        production="SYNTHETIC",
        synthetic={"generator": "test fixture", "generator_version": "0", "statement": "artificial values for a test"},
    )
    meta["channels"]["actual_energy"]["emulates"] = "MEASURED"
    dataset = import_csv(db, plant, engineer, support.daily_csv(), meta)
    assert dataset.is_synthetic
    analysis, _ = analysis_service.run_and_store(db, engineer, plant, dataset, _options())
    assert (analysis.decision, analysis.rule) == ("INVESTIGATE", "R0")
    assert analysis.reason_code == "NON_MEASURED_PRODUCTION"
    assert analysis.operational_authorization is False


def test_period_outside_the_dataset_is_reported_not_crashed(db: Session) -> None:
    engineer = make_user(db, "e@example.org")
    plant = plant_service.create_plant(db, engineer, PLANT)
    dataset = import_csv(db, plant, engineer, support.daily_csv())
    options = AnalysisOptions.model_validate({"period_start": "2027-01-01", "period_end": "2027-01-31"})
    with pytest.raises(InvalidError) as raised:
        analysis_service.run_and_store(db, engineer, plant, dataset, options)
    assert raised.value.code == "ANALYSIS_NOT_POSSIBLE"
    assert db.scalar(select(func.count()).select_from(Analysis)) == 0


def test_weather_dataset_of_another_plant_or_interval_is_refused(db: Session) -> None:
    engineer = make_user(db, "e@example.org")
    plant = plant_service.create_plant(db, engineer, PLANT)
    other_plant = plant_service.create_plant(db, engineer, PLANT)
    production = import_csv(db, plant, engineer, support.daily_csv())
    foreign = import_csv(db, other_plant, engineer, support.daily_csv())
    with pytest.raises(NotFoundError):
        analysis_service.build_input(db, engineer, plant, production, AnalysisOptions(), foreign)


@pytest.mark.safety
def test_demonstration_visitors_do_not_see_each_others_analyses(db: Session) -> None:
    demo_service.seed_demo(db)
    shared = demo_service.demo_plant(db)
    assert shared is not None
    first, second = user_service.create_demo_session(db), user_service.create_demo_session(db)
    for visitor in (first, second):
        demo_service.grant_demo_access(db, visitor)
    db.flush()
    dataset = dataset_service.list_datasets(db, shared)[0]
    mine, _ = analysis_service.run_and_store(db, first, shared, dataset, AnalysisOptions())
    db.flush()

    seeded = len(SCENARIO_KEYS)
    assert len(analysis_service.list_analyses(db, first, shared, limit=200)) == seeded + 1
    assert len(analysis_service.list_analyses(db, second, shared, limit=200)) == seeded
    assert analysis_service.get_analysis(db, first, mine.id)[0].id == mine.id
    with pytest.raises(NotFoundError):
        analysis_service.get_analysis(db, second, mine.id)
    assert analysis_service.latest_by_dataset(db, first, shared)[dataset.id].id == mine.id
    assert analysis_service.latest_by_dataset(db, second, shared)[dataset.id].id != mine.id
    latest_for_second = analysis_service.latest_for_plant(db, second, shared)
    assert latest_for_second is not None and latest_for_second.created_by_id is None


def test_a_visitors_analyses_on_the_shared_plant_disappear_with_the_session(db: Session) -> None:
    demo_service.seed_demo(db)
    shared = demo_service.demo_plant(db)
    assert shared is not None
    visitor = user_service.create_demo_session(db)
    demo_service.grant_demo_access(db, visitor)
    dataset = dataset_service.list_datasets(db, shared)[0]
    analysis_service.run_and_store(db, visitor, shared, dataset, AnalysisOptions())
    visitor.created_at = utcnow() - timedelta(days=2)
    db.commit()
    assert user_service.purge_demo_sessions(db) == 1
    db.commit()
    assert db.scalar(select(func.count()).select_from(Analysis)) == len(SCENARIO_KEYS)
    assert db.get(Plant, shared.id) is not None  # the shared plant itself is untouched


# --------------------------------------------------------------------------- demonstration seeding


def test_seeding_creates_the_ten_scenarios_once(db: Session) -> None:
    assert demo_service.seed_demo(db) == {"plants": 1, "datasets": 10, "analyses": 10}
    assert demo_service.seed_demo(db) == {"plants": 0, "datasets": 0, "analyses": 0}
    plant = demo_service.demo_plant(db)
    assert plant is not None and plant.is_demonstration and plant.created_by_id is None
    datasets = dataset_service.list_datasets(db, plant)
    assert [d.scenario_key for d in datasets] == list(SCENARIO_KEYS)
    assert all(d.is_synthetic for d in datasets)


@pytest.mark.safety
def test_every_seeded_analysis_is_a_simulation_and_matches_its_scenario(db: Session) -> None:
    demo_service.seed_demo(db)
    plant = demo_service.demo_plant(db)
    assert plant is not None
    by_dataset = {a.dataset_id: a for a in db.scalars(select(Analysis))}
    for dataset in dataset_service.list_datasets(db, plant):
        analysis = by_dataset[dataset.id]
        assert dataset.default_options is not None
        assert analysis.decision == dataset.default_options["expected_decision"], dataset.scenario_key
        assert analysis.rule == dataset.default_options["expected_rule"], dataset.scenario_key
        assert analysis.simulated is True and analysis.operational_authorization is False
        assert analysis.context == "DEMONSTRATION"


def test_visitors_can_read_but_not_change_the_shared_plant(db: Session) -> None:
    demo_service.seed_demo(db)
    visitor = user_service.create_demo_session(db)
    plant = demo_service.grant_demo_access(db, visitor)
    db.flush()
    assert plant is not None
    assert plant_service.plant_role(db, visitor, plant) == PlantRole.VIEWER.value
    assert plant_service.get_plant(db, visitor, plant.id).id == plant.id
    with pytest.raises(ForbiddenError):
        plant_service.get_plant(db, visitor, plant.id, write=True)


def test_a_visitors_plant_with_the_same_name_is_not_mistaken_for_the_shared_one(db: Session) -> None:
    demo_service.seed_demo(db)
    shared = demo_service.demo_plant(db)
    visitor = user_service.create_demo_session(db)
    from solarwise.demo.generator import REFERENCE_PLANT

    plant_service.create_plant(db, visitor, REFERENCE_PLANT)
    db.flush()
    again = demo_service.demo_plant(db)
    assert shared is not None and again is not None and again.id == shared.id


# --------------------------------------------------------------------------- economic references


def test_reference_entries_are_loaded_and_refreshed_by_key(db: Session) -> None:
    count = reference_service.sync_reference_values(db)
    db.flush()
    assert count == len(reference_service.list_references(db)) > 0
    assert reference_service.sync_reference_values(db) == count
    db.flush()
    assert len(reference_service.list_references(db)) == count


@pytest.mark.safety
def test_no_unverified_official_figure_is_shipped(db: Session) -> None:
    reference_service.sync_reference_values(db)
    db.flush()
    entries = reference_service.list_references(db)
    official = [e for e in entries if e.classification == "OFFICIAL_REFERENCE"]
    assert official, "the official sources must be listed, even without figures"
    for entry in official:
        assert entry.source_title and entry.source_reference
        if entry.verification_status != "VERIFIED":
            assert entry.amount is None, f"{entry.key}: an unverified official figure must not be shipped"
    for entry in entries:
        if entry.amount is not None and entry.classification != "OFFICIAL_REFERENCE":
            assert entry.classification in ("DEMONSTRATION_VALUE", "USER_ASSUMPTION", "MARKET_ESTIMATE")


@pytest.mark.safety
def test_the_loader_refuses_an_unverified_official_amount(monkeypatch: pytest.MonkeyPatch) -> None:
    document = reference_service.load_document()
    tampered = json.loads(json.dumps(document))
    target = next(e for e in tampered["entries"] if e["classification"] == "OFFICIAL_REFERENCE")
    target["amount"], target["verification_status"] = 4.0, "PENDING_VERIFICATION"

    class _Resource:
        def joinpath(self, _name: str) -> _Resource:
            return self

        def read_text(self, encoding: str = "utf-8") -> str:
            return json.dumps(tampered)

    monkeypatch.setattr(reference_service.resources, "files", lambda _package: _Resource())
    with pytest.raises(ValueError, match="unverified official reference"):
        reference_service.load_document()
