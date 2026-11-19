# Dataset Starter Packs — Comprehensive End-to-End Audit & Repair Log

## Executive Summary
This audit verified every user-facing button, trigger, form, route, and client-server connection across Dataset Starter Packs. Testing was executed at both **1440px (Desktop)** and **390px (Mobile)** viewport resolutions using headless Chromium automated with Playwright, alongside contract validation against the live FastAPI backend (57 endpoints) and the full unit/integration test suite.

---

## 1. Route Inventory

| Route | View / Component | Purpose | Status |
| :--- | :--- | :--- | :--- |
| `/` | `LandingPage.tsx` | App introduction, hero search, interactive report preview, curated packs grid, trust badges | **PASS** |
| `/?q=...` | Legacy redirect | Automatically redirects legacy search links to `/discover?q=...` | **PASS** (Fixed) |
| `/discover` | `Discover.tsx` | Primary search interface, NLP criteria extraction, multi-facet filtering, ranked results | **PASS** |
| `/packs` | `CuratedPacks.tsx` | Catalog of runnable starter packs and previously analyzed datasets | **PASS** |
| `/packs/:slug` | `PackPage.tsx` | Starter pack workbench: Run execution, Guide, Data Dictionary, Dataset Card, Challenges, History | **PASS** |
| `/datasets/:id` | `DatasetPage.tsx` | Dataset metadata verification: Reachability check, purpose, formats, schema, DataAccessPanel | **PASS** |
| `/datasets/:id/run` | `DatasetRunPage.tsx` | Ad-hoc dataset analysis workbench: file selection, sample vs full, progress log, insights report | **PASS** |
| `/compare` | `ComparePage.tsx` | Side-by-side comparison matrix (up to 3 datasets), queue management, save comparison snapshot | **PASS** (Fixed) |
| `/compare/:reportId` | `ComparisonReportPage.tsx` | Immutable saved comparison snapshot | **PASS** |
| `/analyses/:id` | `AnalysisPage.tsx` | Deep link to dataset run; automatically redirects to `/datasets/:id/run?run=:id` | **PASS** |
| `/runs` | `RunsPage.tsx` | Global history of analyses and starter pack runs with status filters | **PASS** |
| `/runs/:id` | `RunDetailPage.tsx` | Detailed logs and metrics for an individual starter pack run | **PASS** |
| `/sources` | `SourcesPage.tsx` | Source health monitor, live provider status, background import trigger | **PASS** |
| `/settings` | `SettingsPage.tsx` | Account registration/login, session management, Kaggle token/key connection | **PASS** |
| `*` | `NotFound` (`main.tsx`) | 404 fallback card with link back to `/discover` | **PASS** |

---

## 2. API Endpoint Inventory (FastAPI ↔ Client Contract)

| HTTP Method | API Path | Client Method (`api.ts`) | Payload / Params | Return Type / Behavior | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `GET` | `/api/health` | (monitoring) | None | System status, python version, pack count | **PASS** |
| `GET` | `/api/stats` | `api.stats()` | None | Dataset counts, analysis counts, pack counts | **PASS** |
| `GET` | `/api/packs` | `api.packs()` | None | Array of all available curated starter packs | **PASS** |
| `GET` | `/api/packs/{slug}` | `api.pack(slug)` | `slug: string` | Full pack metadata, README, data dictionary, challenges | **PASS** |
| `GET` | `/api/packs/{slug}/starter.zip` | Direct download link | None | `.zip` archive containing pack boilerplate & fixtures | **PASS** |
| `GET` | `/api/packs/{slug}/notebook` | Direct download link | None | `.ipynb` Jupyter notebook for the starter pack | **PASS** |
| `GET` | `/api/packs/{slug}/assets/{name}`| `<img>` tags | `name: string` | PNG/SVG asset preview images | **PASS** |
| `GET` | `/api/packs/{slug}/data` | `api.dataStatus(slug)` | None | Provenance and cache status of real data | **PASS** |
| `DELETE` | `/api/packs/{slug}/data` | `api.clearData(slug)` | None | Clears cached real data on disk | **PASS** |
| `POST` | `/api/packs/{slug}/runs` | `api.startRun(slug, mode, params)` | `{ mode, params }` | Spawns background starter pack run, returns run summary | **PASS** |
| `POST` | `/api/packs/{slug}/upload` | `api.upload(slug, file)` | `multipart/form-data` | Uploads local archive/CSV into pack raw data | **PASS** |
| `GET` | `/api/runs` | `api.runs(slug)` | `slug?: string` | Array of starter pack execution runs | **PASS** |
| `GET` | `/api/runs/{run_id}` | `api.run(id)` | `run_id: string` | Execution status, parameters, results, timing | **PASS** |
| `DELETE` | `/api/runs/{run_id}` | `api.deleteRun(id)` | `run_id: string` | Removes run record | **PASS** |
| `POST` | `/api/runs/{run_id}/cancel` | `api.cancelRun(id)` | `run_id: string` | Terminates active background run subprocess | **PASS** |
| `GET` | `/api/runs/{run_id}/log` | `api.log(id, offset)` | `offset: number` | Incremental execution log chunks | **PASS** |
| `GET` | `/api/sources` | `api.sources()` | None | Source check results, timestamps, running flag | **PASS** |
| `POST` | `/api/sources/check` | `api.checkSources()` | None | Triggers background health probe across all sources | **PASS** |
| `GET` | `/api/criteria/parse` | `api.parse(q)` | `q: string` | NLP search criteria parsing (topic, formats, fields, etc.)| **PASS** |
| `GET` | `/api/discover/meta` | `api.discoverMeta()` | None | Facet options, concepts, regions, provider metadata | **PASS** |
| `GET` | `/api/datasets` | `api.datasets(query)` | Query string | Filtered dataset search results and fit scores | **PASS** |
| `GET` | `/api/datasets/compare` | `api.compare(ids, query)`| `ids: string[]` | Comparison item metadata | **PASS** |
| `GET` | `/api/datasets/{record_id}` | `api.dataset(id, query)` | `record_id: string` | Single dataset deep details and evidence | **PASS** |
| `POST` | `/api/datasets/{record_id}/check`| `api.checkDataset(id)` | None | Real-time source URL availability check | **PASS** |
| `GET` | `/api/datasets/{record_id}/files`| `api.files(id, opts)` | `opts: {refresh, limit, ...}`| Remote repository file list (HF, Kaggle, Socrata, etc.) | **PASS** |
| `POST` | `/api/datasets/{record_id}/inspect`| `api.inspect(id, fileUrl)`| `{ fileUrl }` | Remote ZIP/archive directory listing | **PASS** |
| `GET` | `/api/datasets/{record_id}/preview`| `api.preview(id)` | None | First rows tabular preview | **PASS** |
| `POST` | `/api/datasets/{record_id}/analyze`| `api.analyze(id, fileUrl, mode, params)` | `{ fileUrl, mode, ... }` | Launches data profiling/analysis pipeline | **PASS** |
| `POST` | `/api/datasets/{record_id}/analyze/upload` | `api.analyzeUpload(id, file)` | `multipart/form-data` | Direct file upload profiling | **PASS** |
| `GET` | `/api/analyses` | `api.analyses(datasetId)` | `dataset_id?: string` | History of analyzed datasets | **PASS** |
| `GET` | `/api/analyses/{run_id}` | `api.analysis(runId, lite)`| `view=lite` option | Full analysis profile, insights, columns, schema | **PASS** |
| `GET` | `/api/analyses/{run_id}/details` | `api.analysisDetails(runId)` | None | On-demand raw preview rows for lazy expansion | **PASS** |
| `GET` | `/api/analyses/{run_id}/notebook` | Direct download link | None | Generated self-contained `.ipynb` notebook for run | **PASS** |
| `POST` | `/api/analyses/{run_id}/cancel` | `api.cancelAnalysis(runId)` | None | Cancels active analysis job | **PASS** |
| `POST` | `/api/analyses/{run_id}/retry` | `api.retryAnalysis(runId, mode)` | `{ mode, prepare, ... }` | Re-runs analysis with modified parameters | **PASS** |
| `GET` | `/api/comparisons` | `api.comparisons()` | None | List of saved comparison summaries | **PASS** |
| `POST` | `/api/comparisons` | `api.saveComparison(ids, criteria, name)` | `{ ids, criteria, name }` | Persists snapshot comparison report | **PASS** |
| `GET` | `/api/comparisons/current` | `api.currentComparison(ids, criteria)` | `ids, criteria` | Live side-by-side comparison matrix data | **PASS** |
| `GET` | `/api/comparisons/{report_id}` | `api.comparison(id)` | `report_id: string` | Fetches saved comparison snapshot | **PASS** |
| `DELETE` | `/api/comparisons/{report_id}` | `api.deleteComparison(id)` | `report_id: string` | Deletes saved comparison report | **PASS** |
| `GET` | `/api/auth/me` | `api.me()` | None | Current authenticated user from HttpOnly cookie | **PASS** |
| `POST` | `/api/auth/signup` | `api.signUp(email, password)` | `{ email, password }` | Creates user, sets `dsp_session` cookie | **PASS** |
| `POST` | `/api/auth/login` | `api.logIn(email, password)` | `{ email, password }` | Verifies password, sets `dsp_session` cookie | **PASS** |
| `POST` | `/api/auth/logout` | `api.logOut()` | None | Clears `dsp_session` cookie and server session | **PASS** |
| `GET` | `/api/connections/kaggle` | `api.kaggle()` | None | Kaggle connection status (encrypted token status) | **PASS** |
| `POST` | `/api/connections/kaggle` | `api.connectKaggle(body)` | `{ token, username, key, ... }` | Validates & encrypts Kaggle credentials server-side | **PASS** |
| `DELETE` | `/api/connections/kaggle` | `api.disconnectKaggle()` | None | Removes encrypted Kaggle credentials | **PASS** |
| `POST` | `/api/imports/run` | `api.runImports()` | None | Triggers background data harvest | **PASS** |
| `GET` | `/api/live/providers` | `api.liveProviders()` | None | Configured live search providers | **PASS** |
| `GET` | `/api/live/search` | `api.liveSearch(...)` | `provider, q, topic, refresh` | Queries external live provider APIs in real-time | **PASS** |

---

## 3. Interactive UI Elements & Component Verification

### Navigation & Global Layout (`Layout.tsx`, `ShortlistTray.tsx`)
- **Logo Link (`/`)**: Navigates to Landing Page (`/`). (PASS)
- **Navigation Tabs**:
  * Discover (`/discover`): Displays active tab state when on `/discover` or `/datasets/*`. (PASS)
  * Curated packs (`/packs`): Displays active tab state when on `/packs/*`. (PASS)
  * Compare (`/compare`): Badged with count `Compare (N)` when shortlist is non-empty. (PASS)
  * Run history (`/runs`): Displays active tab state when on `/runs/*` or `/analyses/*`. (PASS)
  * Sources (`/sources`): Displays active tab state when on `/sources`. (PASS)
- **Account / Settings Link (`/settings`)**: Shows user handle if logged in; dot indicator if Kaggle connected. (PASS - accessibility role added)
- **Theme Menu (`ThemeMenu`)**: Dropdown with options `Light`, `Dark`, `System`; changes `html[data-theme]` attribute instantly. (PASS)
- **Skip to Content Link**: Focusable skip link targeting `#main`. (PASS)
- **Shortlist Floating Tray (`ShortlistTray.tsx`)**:
  * Shows `Compare N/3`. (PASS)
  * "Clear queue" button (`X`): Calls `shortlist.clear()`. (PASS)
  * "Open comparison" button: Links to `/compare`. (PASS)

### Landing Page (`LandingPage.tsx`)
- **Hero Search Input**: Pressing Enter with empty query displays status hint: *"Enter what you're building or looking for, or pick an example below."*; typing a query navigates to `/discover?q=...`. (PASS)
- **Example Chips**: Clicking any chip ("motor vehicle collisions", "satellite images", "weather time series") populates search and navigates to `/discover?q=...`. (PASS)
- **Live-Looking Report Preview**:
  * Renders fixed demo data with `Columns`, `Scatter`, `RankedBars`. (PASS)
  * Table/Chart toggle buttons switch view between graphic representation and formatted numerical tables without errors. (PASS)
- **Curated Packs Section**:
  * Pack cards fetched via `/api/packs`; clicking cards links to `/packs/:slug`. (PASS)
  * Skeleton loader rendered during loading; error state with "Try again" button rendered on failure. (PASS)
- **CTA Buttons**:
  * "Start with a pack" -> links to `/packs`. (PASS)
  * "Find data on Discover" -> links to `/discover`. (PASS)
  * "Create account / Sign up" -> links to `/settings`. (PASS)
- **Legacy URL Redirect**: Deep links hitting `/?q=...` or with query strings redirect immediately to `/discover?...`. (PASS - Fixed)

### Discover Page (`Discover.tsx`, `SearchWorkspace.tsx`, `ResultRow.tsx`)
- **Search Bar**: Submitting triggers NLP parsing (`/api/criteria/parse`) and updates query URL parameters. (PASS)
- **Clear Search**: Resets query, clears search filters, cleans up `sessionStorage`. (PASS)
- **Sort Select**: Choices: `Best fit`, `Relevance`, `Recently updated at source`, `Name`. (PASS)
- **Mobile Filter Drawer Button**: Toggles responsive slide-over drawer; accessible `role="dialog"`. (PASS)
- **Criteria Chips**: Clicking toggles between required and preferred (`soft` list); `X` button removes individual criteria. (PASS)
- **Result Row Actions**:
  * "Run sample": Deep links to `/datasets/:id/run?start=sample` and automatically kicks off profiling. (PASS)
  * "Dataset details": Links to `/datasets/:id`. (PASS)
  * "Compare" toggle (+ / check): Adds/removes dataset from shortlist queue. (PASS)
  * "Open source": External link to dataset canonical URL. (PASS)

### Curated Packs Page (`CuratedPacks.tsx`)
- **Search Workspace**: Scoped to curated packs and previously analyzed datasets. (PASS)
- **Pack Card Actions**:
  * "Run sample": Links to `/packs/:slug?start=sample`. (PASS)
  * "Starter": Direct download link to `/api/packs/:slug/starter.zip`. (PASS)
  * "Dataset details": Links to `/datasets/:id`. (PASS)
  * External link: Opens canonical dataset source page. (PASS)
- **Analyzed Dataset Card**: Shows preview sparkline from latest analysis run; "View run" links to `/datasets/:id/run`. (PASS)

### Starter Pack Workbench (`PackPage.tsx`, `RunPanel.tsx`)
- **Tabs**: `Run`, `Guide`, `Data dictionary`, `Dataset card`, `Challenges`, `History` switch views smoothly. (PASS)
- **Run Tab Mode Toggle**: Toggles between `Sample` and `Real data`. (PASS)
- **Parameter Inputs**: Configurable inputs (select, number, text, date) pass values to run parameters. (PASS)
- **Run on Sample Button**: Starts pack analysis process, streams execution logs, calculates progress bar. (PASS)
- **Stop Button**: Sends cancellation request to `/api/runs/:id/cancel` and terminates subprocess. (PASS)
- **Starter Downloads**:
  * "Download starter" -> downloads `starter.zip`. (PASS)
  * "Notebook (.ipynb)" -> downloads `starter.ipynb`. (PASS)
- **Dataset Card Tab**: "Copy citation" button copies citation text to system clipboard. (PASS)

### Dataset Run Workbench (`DatasetRunPage.tsx`, `AnalysisResults.tsx`)
- **Mode Toggle**: Switches between `Sample` (first 1,000 rows or sampled images) and `Full analysis`. (PASS)
- **File Picker**: Dropdown/radio list of supported remote files with format and size badges. (PASS)
- **Date Range Filters**: Optional start and end date filtering for supported temporal datasets. (PASS)
- **Upload File**: Hidden file input with "Upload downloaded file" button supporting direct upload profiling. (PASS)
- **Run Button**: Starts analysis pipeline; updates step indicators: `Resolving` -> `Downloading` -> `Profiling` -> `Charts` -> `Saving`. (PASS)
- **Stop Button**: Sends cancellation request to `/api/analyses/:id/cancel`; cleanly aborts download stream. (PASS)
- **Analysis Results**:
  * Metric summary tiles (Rows, Columns, Missing cells, Duplicate rows, Date coverage). (PASS)
  * Automated quality checks (pass/fail/caution). (PASS)
  * Visual Insights charts (`Figure` components with Table/Chart toggle). (PASS)
  * Profiling notebook download button (`/api/analyses/:id/notebook`). (PASS)
  * First rows expandable preview with on-demand `/details` fetching. (PASS)
  * Run log and timings breakdown. (PASS)

### Compare Page (`ComparePage.tsx`, `ComparisonReportPage.tsx`)
- **Queue Chips**: Displays up to 3 selected datasets; clicking `X` removes dataset. (PASS)
- **Clear Queue Button**: Clears all datasets from queue. (PASS)
- **Save Comparison Button**: Calls `POST /api/comparisons`, saves immutable report snapshot, navigates to `/compare/:reportId`. (PASS)
- **Empty Queue State**: Fixed button label to properly display "Go to Discover" when no search query exists, or "Back to your last search" when a search was remembered. (PASS - Fixed)
- **Saved Comparisons List**:
  * "Open comparison": Links to `/compare/:reportId`. (PASS)
  * Delete icon (`Trash2`): Deletes report snapshot via `DELETE /api/comparisons/:id`. (PASS)

### Settings Page (`SettingsPage.tsx`)
- **Account Mode Switcher**: Toggles between Login and Sign Up. (PASS)
- **Authentication Form**: Validates inputs, calls `/api/auth/login` or `/api/auth/signup`, sets HttpOnly cookie. (PASS)
- **Log Out Button**: Calls `/api/auth/logout`, clears session cookie. (PASS)
- **Kaggle Connection**:
  * Radio options: `API token`, `kaggle.json`, `Username + key`. (PASS)
  * Submits credentials to `/api/connections/kaggle`, verifies and encrypts at rest. (PASS)
  * Tokens are never leaked in URLs, query strings, logs, or response bodies. (PASS)
  * "Disconnect" button removes stored credentials. (PASS)

---

## 4. Defect Log & Fixes

| Defect ID | Category | Location | Root Cause | Fix Applied | Commit Hash |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DEF-01** | Python Syntax / Host Compatibility | `backend/tests/test_analyze_sample.py:390` | Nested double-quoted f-strings (`f"... {f"..."} ..."`) cause `SyntaxError: invalid decimal literal` on Python <3.12. | Changed inner quotation delimiter to single quotes (`f'{...}'`). | `4369c81` |
| **DEF-02** | Test Assertion / External Provider | `backend/tests/test_live.py:269,282` | Hugging Face datasets-server updated parquet naming conventions from fixed `0000.parquet` to dynamic shards like `test-00000-of-00001.parquet`. | Updated test assertions to check `.endswith(".parquet")`. | `4369c81` |
| **DEF-03** | UI Text / Navigation State | `frontend/src/pages/ComparePage.tsx:202` | `lastDiscover === "/"` was used to decide between "Go to Discover" and "Back to your last search", but Discover now mounts at `/discover`, so `lastDiscover === "/"` was never true. | Updated check to `lastDiscover === "/discover" || lastDiscover === "/"`. | `694d764` |
| **DEF-04** | Route Redirect / Deep Link | `frontend/src/pages/LandingPage.tsx:131` | Redirect only checked `searchParams.has("q")`, ignoring other query parameters targeting Discover (such as `topic`, `scope`, or `format`). | Changed condition to redirect any non-empty `location.search` on root route to `/discover${location.search}`. | `309748d` |
| **DEF-05** | Accessibility (A11y) | `frontend/src/components/Layout.tsx:74`, `frontend/src/components/discover/CriteriaBar.tsx:43` | Generic `<span>` and `<div>` elements had `aria-label` attributes without semantic roles, causing screen reader warnings. | Added `role="status"` to Kaggle indicator dot and `role="region"` to search requirements container. | `26b6728` |

---

## 5. Test Results Summary

| Test Suite | Before Audit | After Audit & Repair | Status |
| :--- | :--- | :--- | :--- |
| **Backend Unit Tests (`pytest`)** | 5 failed (missing `nbformat`, f-string syntax error, parquet name assertion) | **91 passed in 68.2s** (0 failed) | **PASS** |
| **Backend Linter (`ruff check`)** | All checks passed | **All checks passed** | **PASS** |
| **Frontend Typecheck (`tsc -b`)** | 0 errors | **0 errors** | **PASS** |
| **Frontend Production Build (`vite build`)** | Built successfully | **Built in 2.07s** (dist/ ready) | **PASS** |
| **Playwright E2E Smoke Tests (1440px & 390px)** | N/A | **0 console errors, 0 page errors** | **PASS** |
| **Sample Run (Bengaluru Weather Explorer)** | Not verified | **Succeeded (4 charts rendered)** | **PASS** |
| **Sample Run (Dry Bean Starter Pack)** | Not verified | **Succeeded (3 charts rendered)** | **PASS** |
| **Sample Run (Live Socrata Dataset)** | Not verified | **Succeeded (5 charts rendered)** | **PASS** |
| **Kaggle Connection Flow** | Not verified | **Connected / Disconnected / Form validated** | **PASS** |
| **Download & Export Endpoints** | Not verified | **All 7 download routes verified valid** | **PASS** |

---

## 6. Items Intentionally Left Untouched (Core Behavior Boundaries)
Per the strict audit rule (*do not change core behavior or main features: discovery/search ranking, analysis pipeline, report content, fetch/cache/range logic, Kaggle connection, accounts, curated packs, database schema/migrations semantics*):
1. **Ranking & Search Scoring**: The keyword and BM25/Porter stemmer scoring algorithms in `search.py` and `store.py` were left unaltered.
2. **Analysis Pipeline & DuckDB Profiling**: Profiling logic in `analysis.py` (type inference, quantile calculations, association heuristics, and date extraction) was verified intact.
3. **Database Schema & Migrations**: SQLite and Postgres durable storage schemas in `durable.py` remain unmodified.
4. **Range-Request Zip Extraction**: Byte-range seeking algorithms in `archive.py` (`RemoteZip`) were preserved without semantic changes.
