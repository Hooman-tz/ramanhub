"""Local, durable executor for analysis runs.

Hosted executors can implement the same signed AnalysisRun contract without
changing artifact semantics; this worker is intentionally the free default.
"""
from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.engine import AnalysisCancelled, execute_run
from app.db.base import SessionLocal
from app.logging_config import configure_logging, log_event
from app.models.analysis import AnalysisRun

logger = logging.getLogger(__name__)


def claim_next_run(db: Session) -> AnalysisRun | None:
    run = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.status == "pending", AnalysisRun.execution_backend == "local")
        .order_by(AnalysisRun.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if run is None:
        return None
    if run.cancel_requested:
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        db.commit()
        return None
    run.status = "running"
    run.attempt_count += 1
    run.started_at = datetime.now(UTC)
    db.commit()
    db.refresh(run)
    return run


def _is_cancelled(db: Session, run_id) -> bool:
    """Fetch fresh durable state; a worker's ORM instance may be stale."""
    return bool(
        db.execute(select(AnalysisRun.cancel_requested).where(AnalysisRun.id == run_id)).scalar_one()
    )


def run_once() -> bool:
    db = SessionLocal()
    try:
        run = claim_next_run(db)
        if run is None:
            return False
        try:
            run_id = run.id
            output, checks, digest = execute_run(
                run,
                db,
                cancelled=lambda: _is_cancelled(db, run_id),
            )
            if _is_cancelled(db, run_id):
                raise AnalysisCancelled()
            from app.analysis.engine import build_citation

            citation = build_citation(run, digest)
            updated = (
                db.query(AnalysisRun)
                .filter(
                    AnalysisRun.id == run_id,
                    AnalysisRun.status == "running",
                    AnalysisRun.cancel_requested.is_(False),
                )
                .update(
                    {
                        "output": output,
                        "quality_checks": checks,
                        "output_hash": digest,
                        "citation": citation,
                        "status": "succeeded",
                        "finished_at": datetime.now(UTC),
                    },
                    synchronize_session=False,
                )
            )
            if updated != 1:
                raise AnalysisCancelled()
            db.commit()
            log_event(logger, "analysis_run.succeeded", analysis_run_id=str(run_id), output_hash=digest)
        except AnalysisCancelled:
            db.query(AnalysisRun).filter(AnalysisRun.id == run_id, AnalysisRun.status == "running").update(
                {"status": "cancelled", "finished_at": datetime.now(UTC)},
                synchronize_session=False,
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - every worker error must become durable state
            if _is_cancelled(db, run_id):
                db.query(AnalysisRun).filter(AnalysisRun.id == run_id).update(
                    {"status": "cancelled", "finished_at": datetime.now(UTC)},
                    synchronize_session=False,
                )
            else:
                latest = db.get(AnalysisRun, run_id)
                values = {"error_message": str(exc)[:2000]}
                if latest is not None and latest.attempt_count < latest.max_attempts:
                    values["status"] = "pending"
                else:
                    values["status"] = "failed"
                    values["finished_at"] = datetime.now(UTC)
                db.query(AnalysisRun).filter(AnalysisRun.id == run_id).update(values, synchronize_session=False)
            db.commit()
            log_event(logger, "analysis_run.failed", analysis_run_id=str(run_id), error=str(exc))
        return True
    finally:
        db.close()


def main() -> None:
    configure_logging()
    log_event(logger, "analysis worker started")
    while True:
        if not run_once():
            time.sleep(1)


if __name__ == "__main__":
    main()