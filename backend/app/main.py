"""FastAPI app factory: wires up structured logging, error tracking, CORS,
and all module routers."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging, log_event

# Structured JSON logging is configured once, at import time, before
# anything else in the app has a chance to log — see app/logging_config.py.
configure_logging()
logger = logging.getLogger(__name__)

# Sentry error tracking (Module 5) — a true no-op when SENTRY_DSN is unset
# (the default/current state, since there's no Sentry account yet): no
# import errors, no behavior change. See docs/OPERATIONS.md for setup.
if settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        # No performance tracing by default — this is error tracking only,
        # matching the doc's "captures stack traces and request context"
        # framing rather than a full APM product.
        traces_sample_rate=0.0,
    )

from app.routers import (
    analysis,
    auth,
    comments,
    doi,
    export,
    feed,
    findings,
    ingestion_jobs,
    ledgers,
    library,
    licenses,
    processing,
    raw_files,
    routines,
    search,
    spectra,
    spectrum_data,
    trending,
    users,
    votes,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_event(logger, "app.startup", environment=settings.ENVIRONMENT)
    yield


app = FastAPI(title="RamanHub API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(licenses.router)
app.include_router(raw_files.router)
app.include_router(ingestion_jobs.router)
app.include_router(spectra.router)
app.include_router(ledgers.router)
app.include_router(processing.router)
app.include_router(routines.router)
app.include_router(spectrum_data.router)
app.include_router(analysis.router)
app.include_router(export.router)
app.include_router(findings.router)
app.include_router(feed.router)
app.include_router(doi.router)
app.include_router(search.router)
app.include_router(library.router)
app.include_router(votes.router)
app.include_router(comments.router)
app.include_router(trending.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.ENVIRONMENT}
