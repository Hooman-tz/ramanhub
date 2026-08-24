"""Getting data back out.

An open-access repository that can't export is a roach motel, and the
architecture doc's whole case for Cloudflare R2 — zero egress fees, because
"people repeatedly downloading/viewing shared spectra is the whole point" —
assumes this layer exists.

Three concerns, three modules:

- `tabular` / `jcampdx` — the spectrum itself, in formats a spectroscopist
  can open. JCAMP-DX is the IUPAC interchange format their existing software
  already reads; CSV is what everyone actually pastes into Origin or Python.
- `citation` — BibTeX/RIS/plain text, built from the accession, DOI, ORCID
  and license. This is what makes the data *creditable*, which is the
  incentive that makes anyone publish here at all.
- `bundle` — a ZIP of everything, including the processing ledger, so a
  download is reproducible rather than just a pile of numbers.

Every exporter takes plain arrays and metadata, never a database session, so
they're testable without Postgres and reusable from any caller.
"""
