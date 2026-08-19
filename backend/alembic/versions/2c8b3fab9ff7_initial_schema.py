"""initial schema

Revision ID: 2c8b3fab9ff7
Revises:
Create Date: 2026-08-18 19:41:09.759592

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '2c8b3fab9ff7'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Native Postgres ENUM types, each shared by multiple tables/columns below.
# They're created explicitly once here (rather than left to each
# `op.create_table`'s implicit auto-create/auto-drop, which errors when the
# same enum name is reused across several tables — the first `DROP TABLE`
# would try to `DROP TYPE` while other tables still reference it) and
# referenced everywhere else via `create_type=False`.
modality_enum = postgresql.ENUM(
    'raman', 'mass_spec', 'nmr', name='modality', create_type=False
)
upload_status_enum = postgresql.ENUM(
    'uploaded', 'parsing', 'parsed', 'failed', name='upload_status', create_type=False
)
ingestion_status_enum = postgresql.ENUM(
    'pending', 'running', 'succeeded', 'failed', name='ingestion_status', create_type=False
)
parse_source_enum = postgresql.ENUM(
    'deterministic', 'llm', name='parse_source', create_type=False
)
spectrum_state_enum = postgresql.ENUM(
    'draft', 'published', 'embargoed', name='spectrum_state', create_type=False
)
field_data_type_enum = postgresql.ENUM(
    'number', 'string', 'enum', 'boolean', 'date', name='field_data_type', create_type=False
)

ALL_ENUMS = [
    modality_enum,
    upload_status_enum,
    ingestion_status_enum,
    parse_source_enum,
    spectrum_state_enum,
    field_data_type_enum,
]


def upgrade() -> None:
    """Upgrade schema."""
    op.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')

    bind = op.get_bind()
    for pg_enum in ALL_ENUMS:
        pg_enum.create(bind, checkfirst=True)

    op.create_table('ledger_step_definitions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('modality', modality_enum, nullable=False),
    sa.Column('step_type', sa.String(), nullable=False),
    sa.Column('algorithm_version', sa.String(), nullable=False),
    sa.Column('param_schema', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('modality', 'step_type', 'algorithm_version', name='uq_ledger_step_modality_type_version')
    )
    op.create_table('licenses',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('url', sa.String(), nullable=False),
    sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('metadata_field_definitions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('modality', modality_enum, nullable=False),
    sa.Column('field_key', sa.String(), nullable=False),
    sa.Column('data_type', field_data_type_enum, nullable=False),
    sa.Column('required', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('min_value', sa.Numeric(), nullable=True),
    sa.Column('max_value', sa.Numeric(), nullable=True),
    sa.Column('allowed_values', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('unit', sa.String(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('modality', 'field_key', name='uq_metadata_field_modality_key')
    )
    op.create_table('users',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('google_sub', sa.String(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('display_name', sa.String(), nullable=True),
    sa.Column('avatar_url', sa.String(), nullable=True),
    sa.Column('orcid_id', sa.String(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('google_sub')
    )
    op.create_table('vendor_parse_cache',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('header_hash', sa.String(), nullable=False),
    sa.Column('modality', modality_enum, nullable=False),
    sa.Column('vendor_format', sa.String(), nullable=True),
    sa.Column('parser_version', sa.String(), nullable=False),
    sa.Column('source', parse_source_enum, nullable=False),
    sa.Column('parsed_template', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('hit_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_vendor_parse_cache_header_hash'), 'vendor_parse_cache', ['header_hash'], unique=True)
    op.create_table('processing_routines',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('modality', modality_enum, nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('steps_template', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('raw_files',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('modality', modality_enum, server_default='raman', nullable=False),
    sa.Column('storage_bucket', sa.String(), nullable=False),
    sa.Column('storage_key', sa.String(), nullable=False),
    sa.Column('original_filename', sa.String(), nullable=False),
    sa.Column('content_hash', sa.String(), nullable=False),
    sa.Column('file_size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('vendor_format', sa.String(), nullable=True),
    sa.Column('upload_status', upload_status_enum, server_default='uploaded', nullable=False),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_raw_files_content_hash'), 'raw_files', ['content_hash'], unique=False)
    op.create_table('ingestion_jobs',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('raw_file_id', sa.UUID(), nullable=False),
    sa.Column('status', ingestion_status_enum, server_default='pending', nullable=False),
    sa.Column('parser_used', sa.String(), nullable=True),
    sa.Column('header_hash', sa.String(), nullable=True),
    sa.Column('extracted_metadata_raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('sanity_check_flags', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('extracted_metadata_confirmed', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['raw_file_id'], ['raw_files.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('processing_ledgers',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('raw_file_id', sa.UUID(), nullable=False),
    sa.Column('modality', modality_enum, nullable=False),
    sa.Column('schema_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
    sa.Column('steps', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('ledger_hash', sa.String(), nullable=False),
    sa.Column('derived_from_routine_id', sa.UUID(), nullable=True),
    sa.Column('created_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['derived_from_routine_id'], ['processing_routines.id'], ),
    sa.ForeignKeyConstraint(['raw_file_id'], ['raw_files.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_processing_ledgers_ledger_hash'), 'processing_ledgers', ['ledger_hash'], unique=True)
    op.create_table('processed_cache',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('cache_key', sa.String(), nullable=False),
    sa.Column('raw_file_id', sa.UUID(), nullable=False),
    sa.Column('ledger_id', sa.UUID(), nullable=False),
    sa.Column('storage_bucket', sa.String(), nullable=False),
    sa.Column('storage_key', sa.String(), nullable=False),
    sa.Column('hit_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('compute_duration_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_accessed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['ledger_id'], ['processing_ledgers.id'], ),
    sa.ForeignKeyConstraint(['raw_file_id'], ['raw_files.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_processed_cache_cache_key'), 'processed_cache', ['cache_key'], unique=True)
    op.create_table('spectra',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('raw_file_id', sa.UUID(), nullable=False),
    sa.Column('owner_id', sa.UUID(), nullable=False),
    sa.Column('modality', modality_enum, nullable=False),
    sa.Column('title', sa.String(), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('confirmed_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('current_ledger_id', sa.UUID(), nullable=True),
    sa.Column('license_id', sa.String(), nullable=True),
    sa.Column('state', spectrum_state_enum, server_default='draft', nullable=False),
    sa.Column('embargo_release_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('doi', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['current_ledger_id'], ['processing_ledgers.id'], ),
    sa.ForeignKeyConstraint(['license_id'], ['licenses.id'], ),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['raw_file_id'], ['raw_files.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('spectra')
    op.drop_index(op.f('ix_processed_cache_cache_key'), table_name='processed_cache')
    op.drop_table('processed_cache')
    op.drop_index(op.f('ix_processing_ledgers_ledger_hash'), table_name='processing_ledgers')
    op.drop_table('processing_ledgers')
    op.drop_table('ingestion_jobs')
    op.drop_index(op.f('ix_raw_files_content_hash'), table_name='raw_files')
    op.drop_table('raw_files')
    op.drop_table('processing_routines')
    op.drop_index(op.f('ix_vendor_parse_cache_header_hash'), table_name='vendor_parse_cache')
    op.drop_table('vendor_parse_cache')
    op.drop_table('users')
    op.drop_table('metadata_field_definitions')
    op.drop_table('licenses')
    op.drop_table('ledger_step_definitions')
    # ### end Alembic commands ###

    bind = op.get_bind()
    for pg_enum in ALL_ENUMS:
        pg_enum.drop(bind, checkfirst=True)

    op.execute('DROP EXTENSION IF EXISTS pgcrypto')
