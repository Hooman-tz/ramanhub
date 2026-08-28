"""Guard ingestion lease ownership and one-draft-per-raw-file.

Revision ID: d83a6b1e5c7f
Revises: c61d7f4a2b9e
Create Date: 2026-08-26
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d83a6b1e5c7f"
down_revision: str | Sequence[str] | None = "c61d7f4a2b9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ingestion_jobs", sa.Column("lease_token", sa.String(), nullable=True))
    # Old request-bound workers had no lease token or expiry. Any job that
    # happened to be running during this migration must be made claimable by
    # the new durable worker instead of remaining permanently "running".
    op.execute(
        """
        UPDATE ingestion_jobs
        SET
            status = 'pending'::ingestion_status,
            run_after = now(),
            lease_token = NULL,
            lease_expires_at = NULL,
            last_heartbeat_at = now(),
            error_message = 'Worker restarted during durable queue migration; safely queued for retry.'
        WHERE status = 'running'::ingestion_status
        """
    )
    # Earlier releases allowed multiple Spectrum rows to reference one raw
    # object. Preserve every row by giving later records their own immutable
    # raw-file record and copied completed-ingestion evidence before enforcing
    # the one-spectrum-per-raw-file invariant. A processing ledger includes
    # the raw-file identity in its reproducibility contract, so it is
    # deliberately detached from the cloned spectrum instead of relabeling a
    # ledger with an invalid hash.
    op.execute(
        """
        DO $$
        DECLARE
            duplicate_spectrum RECORD;
            cloned_raw_file_id UUID;
        BEGIN
            FOR duplicate_spectrum IN
                SELECT id, raw_file_id
                FROM (
                    SELECT
                        id,
                        raw_file_id,
                        ROW_NUMBER() OVER (
                            PARTITION BY raw_file_id ORDER BY created_at ASC, id ASC
                        ) AS position
                    FROM spectra
                ) ranked_spectra
                WHERE position > 1
            LOOP
                INSERT INTO raw_files (
                    id, owner_id, modality, storage_bucket, storage_key,
                    original_filename, content_hash, dedupe_hash,
                    storage_version, checksum_verified_at, file_size_bytes,
                    vendor_format, upload_status, uploaded_at
                )
                SELECT
                    gen_random_uuid(), owner_id, modality, storage_bucket, storage_key,
                    original_filename, content_hash, NULL,
                    storage_version, checksum_verified_at, file_size_bytes,
                    vendor_format, upload_status, uploaded_at
                FROM raw_files
                WHERE id = duplicate_spectrum.raw_file_id
                RETURNING id INTO cloned_raw_file_id;

                INSERT INTO ingestion_jobs (
                    id, raw_file_id, status, parser_used, parser_version,
                    parser_confidence, canonicalization_version, header_hash,
                    extracted_metadata_raw, sanity_check_flags,
                    extracted_metadata_confirmed, error_message, attempt_count,
                    max_attempts, run_after, lease_token, lease_expires_at,
                    last_heartbeat_at, draft_spectrum_id, created_at, started_at,
                    finished_at, confirmed_at
                )
                SELECT
                    gen_random_uuid(), cloned_raw_file_id,
                    CASE
                        WHEN status = 'running' THEN 'pending'::ingestion_status
                        ELSE status
                    END,
                    parser_used, parser_version, parser_confidence,
                    canonicalization_version, header_hash, extracted_metadata_raw,
                    sanity_check_flags, extracted_metadata_confirmed, error_message,
                    attempt_count, max_attempts,
                    CASE WHEN status = 'running' THEN now() ELSE run_after END,
                    NULL, NULL, last_heartbeat_at, duplicate_spectrum.id,
                    created_at, started_at, finished_at, confirmed_at
                FROM ingestion_jobs
                WHERE raw_file_id = duplicate_spectrum.raw_file_id;

                UPDATE spectra
                SET raw_file_id = cloned_raw_file_id,
                    current_ledger_id = NULL
                WHERE id = duplicate_spectrum.id;
            END LOOP;
        END $$;
        """
    )
    op.create_unique_constraint("uq_spectra_raw_file_id", "spectra", ["raw_file_id"])


def downgrade() -> None:
    op.drop_constraint("uq_spectra_raw_file_id", "spectra", type_="unique")
    op.drop_column("ingestion_jobs", "lease_token")