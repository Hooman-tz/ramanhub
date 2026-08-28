"""Database ingestion worker entry point.

Run with `python -m app.ingestion.worker`. It intentionally has no HTTP
server; the API process only enqueues jobs and this worker owns parsing/LLM
workloads.
"""
from __future__ import annotations

import logging
import time

from app.ingestion.jobs import claim_next_ingestion_job, run_ingestion_job
from app.logging_config import configure_logging

POLL_INTERVAL_SECONDS = 1.0


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    logger.info("ingestion worker started")
    while True:
        claim = claim_next_ingestion_job()
        if claim is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        run_ingestion_job(
            claim.job_id,
            already_claimed=True,
            lease_token=claim.lease_token,
        )


if __name__ == "__main__":
    main()