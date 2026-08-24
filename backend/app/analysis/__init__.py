"""Analysis (Module 4c): operations that *describe* a spectrum rather than
transform it — peak detection, PCA, hierarchical clustering.

Deliberately a sibling of `app.processing`, not part of it. A processing
algorithm's contract is "arrays in, arrays out, recorded as a replayable
ledger step"; peak picking and PCA return a *result object* and never change
the underlying data, so registering them in
`app.processing.algorithms.registry` would break that contract and put
non-transforming entries into every ledger.

What they share with processing is the self-describing convention: each
module declares module-level `VERSION` and `PARAM_SCHEMA` constants next to
its implementation, so a result recorded on a Finding stays reproducible and
the frontend can render parameter inputs from the schema instead of
hardcoding them.
"""
