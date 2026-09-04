"""Small local index warmer; intentionally exact-search, no premature ANN service."""
from __future__ import annotations

import logging
import time

from sqlalchemy import or_

from app.db.base import SessionLocal
from app.discovery.peak_index import warm_peak_indexes
from app.discovery.raman_similarity import FEATURE_VERSION, warm_features
from app.logging_config import configure_logging, log_event
from app.models.enums import SpectrumState
from app.models.similarity import SimilarityFeature
from app.models.spectrum import Spectrum
from app.models.spectrum_peaks import SpectrumPeaks
from app.processing.peaks import PEAK_INDEX_VERSION

logger = logging.getLogger(__name__)

#: Cap per sweep so a cold start on a large corpus makes steady progress
#: instead of holding one transaction open for the whole library.
BATCH_LIMIT = 500


def _unindexed_ids(db, model, version_column, version_value, limit: int) -> list:
    """Published spectra with no index row, or one built by an older version.

    A LEFT JOIN rather than "every published spectrum": the warmers commit per
    item even on a cache hit, so re-scanning the whole corpus every 60 seconds
    would mean thousands of pointless commits a minute once a reference library
    is seeded. This is the cold-start-only warmer the docstring always claimed.
    """
    return [
        spectrum_id
        for (spectrum_id,) in db.query(Spectrum.id)
        .outerjoin(model, model.spectrum_id == Spectrum.id)
        .filter(
            Spectrum.state == SpectrumState.published,
            Spectrum.moderation_status == "visible",
            or_(model.id.is_(None), version_column != version_value),
        )
        .limit(limit)
        .all()
    ]


def run_once() -> int:
    db = SessionLocal()
    try:
        feature_ids = _unindexed_ids(
            db, SimilarityFeature, SimilarityFeature.feature_version, FEATURE_VERSION, BATCH_LIMIT
        )
        if feature_ids:
            warm_features(feature_ids, db)

        peak_ids = _unindexed_ids(
            db, SpectrumPeaks, SpectrumPeaks.peak_index_version, PEAK_INDEX_VERSION, BATCH_LIMIT
        )
        if peak_ids:
            warm_peak_indexes(peak_ids, db)

        return len(set(feature_ids) | set(peak_ids))
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
