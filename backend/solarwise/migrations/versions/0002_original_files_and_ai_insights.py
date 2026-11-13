"""Original uploaded files and stored AI insights.

``dataset_files`` keeps the file a dataset was imported from, byte for byte.
``ai_insights`` keeps every interpretation written for an analysis, with the model that wrote it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13 12:00:00.000000
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('dataset_files',
    sa.Column('dataset_id', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size_bytes', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('encoding', sa.String(length=10), nullable=False),
    sa.Column('content', sa.LargeBinary(), nullable=False),
    sa.Column('rejected_rows', sa.LargeBinary(), nullable=True),
    sa.Column('rejections', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['dataset_id'], ['datasets.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dataset_id')
    )
    op.create_index(op.f('ix_dataset_files_sha256'), 'dataset_files', ['sha256'], unique=False)
    op.create_table('ai_insights',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('analysis_id', sa.Integer(), nullable=False),
    sa.Column('created_by_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('generated_by', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=60), nullable=True),
    sa.Column('model', sa.String(length=200), nullable=True),
    sa.Column('prompt_version', sa.String(length=20), nullable=False),
    sa.Column('packet_sha256', sa.String(length=64), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('fallback_reason', sa.Text(), nullable=True),
    sa.Column('checks', sa.JSON(), nullable=False),
    sa.Column('content', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_insights_analysis_id'), 'ai_insights', ['analysis_id'], unique=False)
    op.create_index(op.f('ix_ai_insights_created_at'), 'ai_insights', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ai_insights_created_at'), table_name='ai_insights')
    op.drop_index(op.f('ix_ai_insights_analysis_id'), table_name='ai_insights')
    op.drop_table('ai_insights')
    op.drop_index(op.f('ix_dataset_files_sha256'), table_name='dataset_files')
    op.drop_table('dataset_files')
