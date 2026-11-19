# Contributing

Thanks for helping. Small, reviewable changes are the best kind.

## Good first contributions
- Improve a `data-dictionary.md` (units, grain, a missing-value convention you noticed).
- Add a tricky case to a fixture (`fixtures/make_fixture.py`) and a test that covers it.
- Verify the setup on Windows PowerShell or macOS and fix any instruction that didn't work.
- Re-verify a source and update `last_source_check` in its `pack.json`.

## Set up
```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
python scripts/run_pack_tests.py
```

## Add a dataset to Discover (no code)
1. Create `catalog/records/<provider>.<id>.json`. Copy a similar record, e.g. `socrata-chicago.85ca-t3if.json`.
2. Fill only what you can back with a link. Every claim (formats, access, license, coverage, each field) has a `status`: `provider-reported` with an `evidence` URL, or `unknown` with a `note` saying what's missing. Never guess.
3. Tag fields with concepts (`latlon`, `timestamp`, `target_label`, `join_key`, `geo_boundary`) and a `level`: `record` (on every row), `input` (an API parameter) or `grid`. Set `schemaStatus` to `complete` only if the full column list is documented, because that's what lets the search say a field is confirmed missing.
4. Run `python scripts/validate_catalog.py` and `python scripts/search_benchmark.py`. If your dataset should answer a real search, add a case to `catalog/benchmark.json`.

Improving match quality: add synonyms or phrases to `backend/app/discovery/vocab.py` when a benchmark query misses, and keep requirement checks deterministic.

## Add a pack
1. `cp -r pack-template packs/<provider>-<short-name>` (lowercase, hyphens).
2. Fill in `pack.json`. It feeds the README catalog, the web app and CI, so keep it accurate.
3. Write `load_data.py` with **sample** and **real** modes: timeouts, a clear `DataError` with a recovery hint, a cache in `data/raw/`, and `source.json` provenance.
4. Write `fixtures/make_fixture.py` to generate small invented data with the real schema, including the dataset's tricky cases. Commit the generated files.
5. Write `analysis.py`, which produces `results.json` with `headline`, `metrics`, `tables`, `charts`, `checks` and `notes`. The `checks` entry for your pack's trap is the heart of it.
6. Build `starter.ipynb` with the same steps, explained in Markdown cells: load → validate → explore → baseline → evaluate → limitations. Keep `MODE = "sample"` as the default.
7. Add `tests/test_pack.py` with a schema test, a missing-file/column test, and **one regression test for the signature trap**.
8. Link it from a catalog record: add `"packId": "<slug>"` to the dataset's `catalog/records/*.json` (create one if needed).
9. Add `assets/preview.png` (a chart you have reviewed) and `requirements.txt` with pinned versions.
10. Run:
   ```bash
   python scripts/validate_catalog.py --write
   python scripts/run_pack_tests.py --isolated --notebooks <slug>
   ruff check .
   ```

## Rules that keep packs reproducible
- A pack must not import from outside its own folder. CI copies each pack out of the repo and runs it alone.
- Never commit downloaded data, credentials, or large generated outputs.
- Document the dataset's license in the README dataset card and in `DATA_SOURCES.md`. If redistribution is not allowed, the loader must fetch or import, never bundle.
- Sample results must always be identifiable as sample results.
- Run the real-data path at least once by hand and record the runtime in `expected_runtime`.

## Pull requests
CI runs lint, metadata validation, every pack's tests and notebook (sample mode, on Ubuntu and Windows), the API tests and the frontend build. It needs no credentials and no network access to the data providers. Source availability is checked separately each week, so an upstream outage never blocks your PR.
