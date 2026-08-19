#!/bin/sh
# Idempotent MinIO bucket bootstrap, run once by the `minio-init` compose
# service against the `minio` service. Safe to re-run: `mc mb --ignore-existing`
# no-ops if the bucket already exists.
set -eu

mc alias set local http://minio:9000 minioadmin minioadmin
mc mb --ignore-existing local/raw-spectra
mc mb --ignore-existing local/processed-spectra

echo "MinIO buckets ready: raw-spectra, processed-spectra"
