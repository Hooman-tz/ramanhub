"""FastAPI app factory: wires up CORS and all module routers."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    auth,
    ingestion_jobs,
    ledgers,
    licenses,
    raw_files,
    routines,
    spectra,
    users,
)

app = FastAPI(title="RamanHub API", version="0.1.0")

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
app.include_router(routines.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "environment": settings.ENVIRONMENT}
