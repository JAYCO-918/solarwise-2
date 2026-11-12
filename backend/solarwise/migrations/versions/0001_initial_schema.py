"""Initial schema.

Timestamps are stored in UTC (``DateTime(timezone=True)``; SQLite keeps them as naive UTC).

Revision ID: 0001
Revises: -
Create Date: 2026-11-11 06:29:56.726623
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('economic_reference_values',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('label', sa.String(length=300), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('classification', sa.String(length=40), nullable=False),
    sa.Column('amount', sa.Float(), nullable=True),
    sa.Column('currency', sa.String(length=3), nullable=True),
    sa.Column('unit', sa.String(length=40), nullable=True),
    sa.Column('source_title', sa.String(length=500), nullable=False),
    sa.Column('source_reference', sa.String(length=500), nullable=False),
    sa.Column('verification_status', sa.String(length=40), nullable=False),
    sa.Column('applicability', sa.Text(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=500), nullable=True),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('is_demo', sa.Boolean(), nullable=False),
    sa.Column('failed_logins', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_email'), ['email'], unique=True)

    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('entity', sa.String(length=40), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('remote_address', sa.String(length=64), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_action'), ['action'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_at'), ['at'], unique=False)

    op.create_table('plants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('capacity_dc_kwp', sa.Float(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('is_demonstration', sa.Boolean(), nullable=False),
    sa.Column('spec', sa.JSON(), nullable=False),
    sa.Column('pvgis_monthly', sa.JSON(), nullable=True),
    sa.Column('pvgis_source', sa.String(length=500), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('plants', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_plants_name'), ['name'], unique=False)

    op.create_table('datasets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plant_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('file_format', sa.String(length=10), nullable=False),
    sa.Column('content_sha256', sa.String(length=64), nullable=False),
    sa.Column('interval_minutes', sa.Integer(), nullable=False),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('rows_plant', sa.Integer(), nullable=False),
    sa.Column('rows_device', sa.Integer(), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('scenario_key', sa.String(length=64), nullable=True),
    sa.Column('declared_metadata', sa.JSON(), nullable=False),
    sa.Column('channels', sa.JSON(), nullable=False),
    sa.Column('device_tag', sa.JSON(), nullable=True),
    sa.Column('validation_report', sa.JSON(), nullable=False),
    sa.Column('default_options', sa.JSON(), nullable=True),
    sa.Column('archived', sa.Boolean(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['plant_id'], ['plants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('plant_id', 'content_sha256', name='uq_dataset_content')
    )
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_datasets_plant_id'), ['plant_id'], unique=False)

    op.create_table('devices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plant_id', sa.Integer(), nullable=False),
    sa.Column('code', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('capacity_kwp', sa.Float(), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.ForeignKeyConstraint(['plant_id'], ['plants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('plant_id', 'code', name='uq_device_code')
    )
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_devices_plant_id'), ['plant_id'], unique=False)

    op.create_table('plant_permissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plant_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['plant_id'], ['plants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('plant_id', 'user_id', name='uq_plant_permission')
    )
    with op.batch_alter_table('plant_permissions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_plant_permissions_plant_id'), ['plant_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_plant_permissions_user_id'), ['user_id'], unique=False)

    op.create_table('analyses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plant_id', sa.Integer(), nullable=False),
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('weather_dataset_id', sa.Integer(), nullable=True),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('engine_version', sa.String(length=20), nullable=False),
    sa.Column('context', sa.String(length=20), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('rule', sa.String(length=20), nullable=False),
    sa.Column('reason_code', sa.String(length=60), nullable=False),
    sa.Column('diagnostic_status', sa.String(length=40), nullable=False),
    sa.Column('simulated', sa.Boolean(), nullable=False),
    sa.Column('operational_authorization', sa.Boolean(), nullable=False),
    sa.Column('gap_pct', sa.Float(), nullable=True),
    sa.Column('window_gap_pct', sa.Float(), nullable=True),
    sa.Column('headline', sa.Text(), nullable=False),
    sa.Column('options', sa.JSON(), nullable=False),
    sa.Column('result', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['plant_id'], ['plants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['weather_dataset_id'], ['datasets.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('analyses', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_analyses_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_analyses_dataset_id'), ['dataset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_analyses_decision'), ['decision'], unique=False)
        batch_op.create_index(batch_op.f('ix_analyses_plant_id'), ['plant_id'], unique=False)

    op.create_table('evidence_records',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('plant_id', sa.Integer(), nullable=False),
    sa.Column('dataset_id', sa.Integer(), nullable=True),
    sa.Column('reference', sa.String(length=64), nullable=False),
    sa.Column('evidence_type', sa.String(length=40), nullable=False),
    sa.Column('observed_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('observed_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('record', sa.JSON(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['plant_id'], ['plants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('evidence_records', schema=None) as batch_op:
        batch_op.create_index('ix_evidence_plant_reference', ['plant_id', 'reference'], unique=False)
        batch_op.create_index(batch_op.f('ix_evidence_records_plant_id'), ['plant_id'], unique=False)

    op.create_table('production_observations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('device_code', sa.String(length=64), nullable=False),
    sa.Column('start_utc', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actual_energy_kwh', sa.Float(), nullable=True),
    sa.Column('expected_energy_kwh', sa.Float(), nullable=True),
    sa.Column('baseline_irradiation_kwh_m2', sa.Float(), nullable=True),
    sa.Column('availability_fraction', sa.Float(), nullable=True),
    sa.Column('curtailed_energy_kwh', sa.Float(), nullable=True),
    sa.Column('soiling_ratio', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_id', 'device_code', 'start_utc', name='uq_production_interval')
    )
    with op.batch_alter_table('production_observations', schema=None) as batch_op:
        batch_op.create_index('ix_production_dataset_time', ['dataset_id', 'start_utc'], unique=False)

    op.create_table('weather_observations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('start_utc', sa.DateTime(timezone=True), nullable=False),
    sa.Column('poa_irradiation_kwh_m2', sa.Float(), nullable=True),
    sa.Column('ghi_kwh_m2', sa.Float(), nullable=True),
    sa.Column('ambient_temp_c', sa.Float(), nullable=True),
    sa.Column('module_temp_c', sa.Float(), nullable=True),
    sa.Column('wind_speed_ms', sa.Float(), nullable=True),
    sa.Column('relative_humidity_pct', sa.Float(), nullable=True),
    sa.Column('precipitation_mm', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dataset_id', 'start_utc', name='uq_weather_interval')
    )
    with op.batch_alter_table('weather_observations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_weather_observations_dataset_id'), ['dataset_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('weather_observations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_weather_observations_dataset_id'))

    op.drop_table('weather_observations')
    with op.batch_alter_table('production_observations', schema=None) as batch_op:
        batch_op.drop_index('ix_production_dataset_time')

    op.drop_table('production_observations')
    with op.batch_alter_table('evidence_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_evidence_records_plant_id'))
        batch_op.drop_index('ix_evidence_plant_reference')

    op.drop_table('evidence_records')
    with op.batch_alter_table('analyses', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_analyses_plant_id'))
        batch_op.drop_index(batch_op.f('ix_analyses_decision'))
        batch_op.drop_index(batch_op.f('ix_analyses_dataset_id'))
        batch_op.drop_index(batch_op.f('ix_analyses_created_at'))

    op.drop_table('analyses')
    with op.batch_alter_table('plant_permissions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_plant_permissions_user_id'))
        batch_op.drop_index(batch_op.f('ix_plant_permissions_plant_id'))

    op.drop_table('plant_permissions')
    with op.batch_alter_table('devices', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_devices_plant_id'))

    op.drop_table('devices')
    with op.batch_alter_table('datasets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_datasets_plant_id'))

    op.drop_table('datasets')
    with op.batch_alter_table('plants', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_plants_name'))

    op.drop_table('plants')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_at'))
        batch_op.drop_index(batch_op.f('ix_audit_log_action'))

    op.drop_table('audit_log')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_email'))

    op.drop_table('users')
    op.drop_table('economic_reference_values')
