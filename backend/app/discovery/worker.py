"""Small local index warmer; intentionally exact-search, no premature ANN service."""
from __future__ import annotations

import logging
import time

from app.db.base import SessionLocal
from app.discovery.raman_similarity import warm_features
from app.logging_config import configure_logging, log_event
from app.models.enums import SpectrumState
from app.models.spectrum import Spectrum

logger = logging.getLogger(__name__)


def run_once() -> int:
    db = SessionLocal()
    try:
        ids = [
            spectrum_id
            for (spectrum_id,) in db.query(Spectrum.id)
            .filter(Spectrum.state == SpectrumState.published, Spectrum.moderation_status == "visible")
            .all()
        ]
        warm_features(ids, db)
        return len(ids)
    finally:
        db.close()


def main() -> None:
    configure_logging()
    log_event(logger, "similarity index worker started")
    while True:
        run_once()
        time.sleep(60)


if __name__ == "__main__":
    main()