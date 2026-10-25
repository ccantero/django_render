---
doc_id: changelog
doc_version: 1.1.51
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-10-25
source_repo: django_render
---

# Changelog

## 2026-10-25 - Refresh PR #3 against main 1b8b103

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Main advanced after the prior merge to include Analytics fixes, deploy-version
  visibility, and pause/resume UX. Reconciled four documentation conflicts,
  keeping complete entries from both parents and incrementing doc versions.
- Diagnostics source and tests remain unchanged; main's other files are retained.
- The PR API initially reported base 60bdcc6 while the main ref and branch API
  reported 1b8b103. Remote refs, not that stale PR base field, identify the target.

Validation:
- Diagnostics: 16 passed, 11 subtests. Full suite: 437 passed, 3 existing
  PostgreSQL-only skips, 44 subtests. Django check: no issues. JavaScript: 11 passed.
- Conflict-marker scan clean; only the nine original PR paths differ from main.
- No new runtime behavior, tests, schema, contract, logging, or KPI changes.
- No deployment or merge to main performed.

## 2026-10-25 - Reconcile Diagnostics API PR #3 with main

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Reconciled documentation metadata, both diagnostics API changelog entries,
  the static-file cleanup entry, and historical workflow evidence.
- Preserved the diagnostics implementation and tests byte-for-byte, including
  the dedicated Bearer Token, fixed routes, and read-only evidence semantics.
- Retained main's Passkey UX, authentication safeguards, security dependency
  floors, PostgreSQL test isolation, and static source/storage changes.
- No trading, accounting, schema, shared-contract, KPI, or logging changes.

Operator impact:
- PR #3 includes current main; this task does not merge the PR or deploy it.
  Render deployment and Work Cloud connectivity verification remain separate.

Validation:
- `.venv/bin/pytest dashboard/test_bot_diagnostics_api.py -q --create-db`:
  16 passed, 11 subtests passed.
- `.venv/bin/pytest -q --create-db`: 392 passed, 3 skipped (existing
  PostgreSQL-only concurrency tests), 44 subtests passed.
- `python manage.py check` with synthetic local settings: no issues.
- `node --test tests/passkeys_frontend.test.cjs`: 3 passed; `pip check`: clean.
- API routes/authentication/read-only behavior are covered by the API suite;
  all other files outside the original nine PR paths match main.
- Warnings: absent untracked local `staticfiles/` output and an unordered
  UserProfile queryset in the existing DRF pagination regression test.
- No production credentials, database access, migrations, or deployment used.

## 2026-10-17 - Correct Bot Diagnostics Evidence Semantics

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Renamed the Spot quantity/timestamp fields to `observed_spot_quantity` and
  `detected_at`; the age field is `observation_recency`, and the observation
  still explicitly sets `current_exchange_truth: false`.
- Stale capacity numbers now appear only under `historical_global`; partial,
  unavailable, and current-as-of-healthcheck states are explicit.
- Marked portfolio-versus-lot comparisons as not synchronized and the
  multi-query inventory response as non-atomic. No read transaction was added.
- Reviewed the bot repository: complete non-zero Binance balances are fetched
  into runtime memory; no complete Spot-balance snapshot is persisted. The
  bot's comparison CLI reads Binance, FIFO lots, and generations without
  persisting the exchange snapshot. Django remains without an active-generation
  read model.
- No Binance client, persistence, KPI formula, database schema, or bot behavior
  changed. `docs/DATA_CONTRACT.md` and `docs/KPI_REGISTRY.md` were reviewed; no
  semantic update was needed for these API response corrections. The Django
  copies are behind current `ccantero/binancebot` main headers
  (`DATA_CONTRACT.md` 1.0.62 vs 1.0.79; `KPI_REGISTRY.md` 1.0.36 vs 1.0.48);
  a full paired-document sync is a separate follow-up and was not mixed into
  this API correction.
- Documented that custom GPT Actions are distinct from native ChatGPT Work
  connectivity, and recorded the security and deployment limitations.

Operator impact:
- An old Spot event can no longer be mistaken for a current exchange balance;
  stale BUY slot counts are visibly historical and unavailable as current
  capacity.

Validation:
- Focused API tests: 16 passed, 11 subtests passed. Django system check: no
  issues. Full suite on PR branch: 344 passed, 44 subtests passed.
- Full suite on base `82e32fd`: 328 passed, 33 subtests passed. The earlier
  report of five `dust_signal_reviews` failures did not reproduce on either
  branch with the repository's pytest setup; the exact earlier invocation was
  not recorded.
- PostgreSQL execution validation was not possible: this runner has no
  PostgreSQL server/client or container runtime, and package installation was
  blocked by runner permissions. No production database was accessed.
- ChatGPT Work Cloud Action/connector compatibility remains **UNVERIFIED**.

## 2026-10-17 - Add Read-only Bot Diagnostics API PoC

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Added authenticated GET-only health and fixed ETHUSDT inventory diagnostics
  backed by existing managed=False bot read models, including the latest
  timestamped `bot.dust_detections` Spot quantity observation.
- Required a dedicated environment bearer secret; user tokens, raw healthcheck
  details, Binance calls, mutations, and general query/action interfaces are
  excluded.
- Exposed persisted freshness and unavailable states so DB projections and
  lots are not confused with live Binance Spot truth.
- Included the bot-persisted `effective_positions_count` alongside the other
  available BUY capacity details; per-symbol active-generation occupancy is
  not recomputed by Django.
- Documented from bot repository code that complete per-asset Binance Spot
  balances are not periodically persisted; the one-off comparison CLI fetches
  live balances without persisting the snapshot.
- Recorded direct ChatGPT Work Cloud access as unverified because no connector
  or cloud-safe credential delivery is configured by this application.
- Reviewed `docs/KPI_REGISTRY.md`: no KPI/metric definitions or formulas
  changed; the API exposes existing healthcheck fields with their existing
  source semantics. No database schema or data-contract changes were made.

Operator impact:
- An authorized client can retrieve bounded, sanitized persisted ETHUSDT
  evidence without database or SSH access once the endpoint is deployed and
  provisioned with a dedicated secret.

Validation:
- Focused API tests verify authentication, read-only access, missing/stale
  evidence, malformed valuation, bounded ORM operations, and safe output.
- Focused API suite: 10/10 passed. Full project test run: 333 passed, 5
  failed because the SQLite test database does not contain
  `dust_signal_reviews`.

## 2026-10-25 - Do not replay an uncertain pause or resume

Type: behavior
Runtime version: 2.0.0
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- The dashboard script no longer calls `form.submit()` when `fetch` fails or the response is unusable. That path shows "Resultado incierto. No se reenvió el pedido.", re-reads `GET /bot/status/`, updates the card from that saved desired state, and posts again only through "Reintentar el pedido".
- A second submit while a request is in flight is ignored. Pause and resume controls are disabled until the current request finishes. An older response sequence cannot overwrite a newer card.
- Pause confirmation is now universal. JSON pause requires `confirm=yes` or JSON `confirm` of `"yes"` or `true`. Without it the response is HTTP 400 `confirmation_required` and nothing is written. HTML without confirmation still redirects with the same Spanish error and does not write. Resume still does not require confirmation.
- This repository has no Telegram handler, script, or other caller of `/bot/stop/`, `/bot/resume/`, or `/bot/status/` besides the dashboard, tests, and docs. There is no compatibility exception.
- The success JSON object is unchanged. `*/*` and a missing Accept still receive JSON once a pause is confirmed. Login, CSRF, redirect checks, and the non-staff permission are unchanged. The `core_botcontrol` table and columns are unchanged. Copy still says the state is requested, not confirmed by the bot.
- The `1.1.0` changelog entry below said JSON clients do not need confirmation. That sentence described `1.1.0` only. `2.0.0` replaces it.
- `VERSION` is `2.0.0` (MAJOR: an unconfirmed pause POST that `1.0.0` and `1.1.0` accepted now returns 400).
- Reviewed `docs/KPI_REGISTRY.md`; no metric was added or redefined. `docs/DATA_CONTRACT.md` was reviewed and left unchanged. No new logs. No schema or DER change.

Operator impact:
- From the phone, a lost response no longer sends a second pause or resume by itself. The card says the result is uncertain, then shows whatever row is saved. The operator can retry with the button.
- Without JavaScript, the form still posts once and the browser follows the safe redirect.
- A programmatic pause must now send confirmation. Resume payloads stay the same.

Validation:
- `node --test tests/bot_control_frontend.test.cjs tests/passkeys_frontend.test.cjs`: 11 passed (8 bot-control, 3 passkey).
- `pytest core/test_bot_control.py tests/test_deploy_version.py`: 36 passed.
- Full `pytest`: 421 passed, 3 skipped, 33 subtests passed.

## 2026-10-25 - Keep pause and resume inside the dashboard

Type: behavior
Runtime version: 1.1.0
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- HTML form posts to `/bot/stop/` and `/bot/resume/` now redirect to a same-origin page and show "Pausa solicitada" or "Reanudación solicitada". They no longer return raw JSON to a phone browser.
- A pause request from the HTML form requires confirmation and can include a reason. Resume can include a reason and does not require the same confirmation.
- The dashboard control card shows the desired state ("Estado solicitado"), the row time in America/Buenos_Aires (ART), who recorded it, and the reason. The copy does not say the bot has stopped or resumed. There is no acknowledgement from the bot.
- Clients that send `Accept: application/json`, or that do not advertise `text/html`, still receive the existing JSON payload and do not need the confirmation field.
- The write is unchanged: `core_botcontrol.is_paused`, `reason`, `updated_by`, and `updated_at`. Login, POST-only, and CSRF rules are unchanged.
- `VERSION` is `1.1.0` (MINOR: operator-visible request flow, JSON payload preserved).
- Reviewed `docs/KPI_REGISTRY.md`; no metric was added or redefined. `docs/DATA_CONTRACT.md` was reviewed and left unchanged.

Operator impact:
- From the phone, requesting a pause or resume stays on the dashboard. The flash and the card describe a requested state, not an effective bot state.
- Without JavaScript, the form posts and the browser follows the redirect. With JavaScript, the card updates in place and falls back to that redirect if the request fails.
- Programmatic clients that already posted without a browser `Accept: text/html` header still get JSON.

Validation:
- `pytest core/test_bot_control.py tests/test_deploy_version.py`: 35 passed.
- Full `pytest`: 420 passed, 3 skipped, 33 subtests passed.

## 2026-10-25 - Keep the deploy clock explicit

Type: behavior
Runtime version: 1.0.0
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md
- AGENTS.md

Summary:
- `/version/` and the footer show a clock time only from `DEPLOYED_AT` or from `build_info.json` written by `python manage.py stamp_build`.
- `deployed_at` is null and `timestamp_source` is `unknown` when neither source is valid. File modification time and process start are not reported as a deploy time.
- `timestamp_source` is `explicit` or `build_stamp` when a time is present. The same display string is used in the footer.
- `1.0.0` remains the initial SemVer baseline. The MAJOR/MINOR/PATCH rules apply to behavior changes after it. This correction does not bump `VERSION`.
- Version tests use temporary directories and scoped environment patches.

Operator impact:
- No Render change is required. The short commit still shows whether a new commit is deployed.
- To show an exact build time, append `&& python manage.py stamp_build` to the Render Build Command. A later restart keeps that stamp until the next build. Optional `DEPLOYED_AT` overrides the stamp.
- Without that step, the footer time stays `unknown` instead of showing a file or process time.

Validation:
- `tests/test_deploy_version.py` failed first because `resolve_timestamp` did not exist, then 16 passed.
- Full `pytest`: 401 passed, 3 skipped, 33 subtests passed. The existing DRF unordered-pagination warning remains.

## 2026-10-25 - Show the deployed SemVer on the site and at /version/

Type: behavior
Runtime version: 1.0.0
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md
- AGENTS.md

Summary:
- Added root `VERSION` (`1.0.0`) as the only app SemVer source. Document `doc_version` headers are unchanged in meaning.
- The shared base footer shows `v1.0.0+<short sha>` and a `America/Buenos_Aires` timestamp, including the calculator standalone view that hides navigation. `GET /version/` returns `version`, `commit`, `deployed_at`, and `display` with `Cache-Control: no-store`.
- Missing `RENDER_GIT_COMMIT` uses `dev`. Missing deploy time uses `unknown` / `null`. Render service IDs, branches, and secrets are not exposed. `/health/` stays `{"status":"ok"}`.
- The currency-converter service worker fetches navigations and `/version/` with `cache: 'no-store'`, does not cache its own script, and drops older caches on activate.
- No Render dashboard change is required for the commit label. The timestamp rule in this entry was corrected by the entry above: file mtime and process start are not a deploy time.

Operator impact:
- After a deploy, the phone PWA and the website footer show the new short commit and Buenos Aires time without opening Render. `curl /version/` returns the same facts.
- The short SHA is the commit identity. The clock-time rule in the original summary was corrected by the entry above.

Validation:
- `tests/test_deploy_version.py` failed first with `ModuleNotFoundError: No module named 'django_render.version'`, then passed (11 tests).
- Full `pytest`: 396 passed, 3 skipped, 33 subtests passed. The existing DRF unordered-pagination warning remains.

## 2026-10-25 - Tighten analytics cache equivalence and failure handling

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/ARCHITECTURE.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Cold and warm `/dashboard/analytics/` renders now have regression coverage for the fee cards, KPI values, symbol table, and day table. The analytics template reads dict and scalar fields only. It does not call model methods, properties, or relations. The pickle-safe snapshot still copies concrete fields from cached bot rows and drops `save`, `delete`, and relations such as `updated_by`.
- Cache read, write, and delete now catch cache-boundary errors only: pickle errors, `LookupError`, `AttributeError`, `TypeError`, `ValueError`, `OSError`, and `DatabaseError`. Building the read model stays outside that handler. The bypass log includes the cache key, error type, and error text.
- The cache key is `dashboard:analytics_context:v2`, so a deploy does not read payloads stored under `v1`.
- Reviewed `docs/KPI_REGISTRY.md`. No KPI name, formula, source of truth, status, or null behavior changed.

Operator impact:
- Repeat analytics requests inside 60 seconds should show the same fees, KPIs, and tables as the first request.
- A cache backend failure still renders the freshly built page, including the shared-database error banner when that read failed.
- A bug while building the read model still raises instead of being reported as a cache miss.
- After deploy, open `/dashboard/analytics/` twice. Both responses should succeed with the same numbers, and logs should not show `LookupError: No installed app with label 'trading_read'`.

Validation:
- `tests/test_analytics_cache.py` failed first because the key was still `v1`, cache warnings omitted the error text, and a non-cache `RuntimeError` from `cache.get` was swallowed. After the change, 9 passed.
- Full `pytest`: 385 passed, 3 skipped, 33 subtests passed. The existing DRF unordered-pagination warning remains.

## 2026-10-25 - Analytics cache no longer 500s on bot rows

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/ARCHITECTURE.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- `/dashboard/analytics/` cached the full read-model context, including unmanaged `bot.*` model instances whose `app_label` is `trading_read`.
- Django cache backends pickle cached values. The following request unpickled those rows through `apps.get_model("trading_read", ...)`, which raises `LookupError` because `trading_read` is not an installed app. Django turned that into HTTP 500. The homepage does not use this cache, so it could keep loading.
- The analytics cache now stores a pickle-safe snapshot. Model rows are copied to plain attribute objects before `cache.set`. An unreadable cache entry is deleted and the page is rebuilt.
- Reviewed `docs/KPI_REGISTRY.md`. No KPI name, formula, source of truth, status, or null behavior changed.
- Checked the merged static-file cleanup (PR #6). Analytics uses the shared base template and does not add a static reference. Current non-debug storage is `CompressedStaticFilesStorage`, which does not raise while rendering `{% static %}`. That change does not explain this 500.

Operator impact:
- Authenticated `/dashboard/analytics/` keeps loading on repeat requests inside the 60-second cache window when healthcheck or trade rows are present.
- A shared-database read failure still renders the existing data-error banner. Empty KPI inputs stay empty or N/A.
- A warning is logged only when the analytics cache cannot be read, deleted, or stored. The line includes `event`, `component`, `error_type`, and unknown version fields. It does not include row payloads or secrets.

Validation:
- `tests/test_analytics_cache.py` failed first with `LookupError: No installed app with label 'trading_read'` on the cached request. After the change, 2 passed.
- Full `pytest`: 378 passed, 3 skipped, 33 subtests passed. The existing DRF unordered-pagination warning remains.

## 2026-10-25 - Stop tracking collected static files

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Removed generated `staticfiles/` output, the copied `static/admin/` tree, and `static/staticfiles.json` from Git.
- Kept project source assets under `static/core`, `static/currencyconverter`, `static/profile`, and `static/favicon.ico`.
- Django 5.2 ignores the legacy `STATICFILES_STORAGE` setting, so non-debug settings now select WhiteNoise `CompressedStaticFilesStorage` through `STORAGES["staticfiles"]`.
- Restored this changelog from the last text revision (`d2621aae`, doc_version 1.1.43). The file on the previous branch tip was binary and did not contain those text entries.

Operator impact:
- Before merging, confirm the Render web service Build Command runs `python manage.py collectstatic --noinput` after installing requirements. Append that command if it is missing. Leave any existing migrate or other build steps in place.
- Local `runserver` with `CC_DEBUG=true` still serves source assets through Django's static finders. Production WhiteNoise serves `STATIC_ROOT` (`staticfiles/`) created at build time.
- Django admin static files now come from the installed Django package instead of the older copy previously committed under `static/admin/`.

Validation:
- `pytest` — 376 passed, 3 skipped, 33 subtests passed.
- `CC_DEBUG=false python manage.py collectstatic --noinput` from a clean tree copied 170 files and gzip-compressed 158.

## 2026-10-15 - Scale Telegram BUY Rows to Configured Capacity

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Replaced the fixed eight-row material exposure cap with the configured
  `MAX_POSITIONS` capacity; the existing persisted-healthcheck/runtime-config
  resolution remains the source of that value.
- Kept Telegram's 4096-character limit as the safety bound. Its compact fallback
  retains capacity, material exposure, full-position PnL, latest BUY, and status,
  and reports omitted material rows. PnL aggregation remains independent of the
  visible rows.
- Kept dust, unknown-value, and unavailable-valuation symbol lists on separate
  compact display policies.
- Confirmed `bot.bot_healthcheck.details` remains authoritative for current
  classification counts and BUY capacity; `bot.portfolio` only enriches the
  persisted material/dust buckets with projection values. No independent
  reclassification or accounting source change was made.
- Reviewed `docs/KPI_REGISTRY.md`; no metric formula, source, or meaning changed.

Operator impact:
- Configured portfolios can show every material position when the Telegram
  message fits, including capacities above 15. Oversized messages retain key
  operating fields and state how many material rows are not displayed.

Validation:
- Focused BUY-status/PnL tests: 59 passed.
- Full `python -m pytest -q`: 328 passed, 33 subtests passed.

## 2026-10-14 - Harden Telegram BUY Status

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Use the bot-persisted healthcheck classification as the authoritative source
  for `/buy_status` counts and capacity; use `bot.portfolio` only to enrich
  valuation for persisted material/dust symbol buckets.
- Mark stale BUY diagnostics as historical, suppress stale BUY errors from
  current-state interpretation, and avoid current capacity claims from stale
  classifications.
- Reject non-finite valuation inputs and keep Telegram output within 4096
  characters with a prioritized compact fallback and escaped multiline text.
- Reviewed `docs/KPI_REGISTRY.md`; no metric formula, source, or meaning changed.

Operator impact:
- Missing classification is shown as unavailable; a stale heartbeat cannot
  make an old BUY rejection/error look current.
- Exposure values remain approximate projection data while their material/dust
  category stays aligned with the bot-persisted snapshot.
- Overlong diagnostic payloads retain capacity, positions, PnL, latest BUY, and
  status fields before omitting secondary details.

Validation:
- Focused BUY-status regression tests: 50 passed.
- `python -m pytest -q`: 324 passed, 33 subtests passed.
- `git diff --check` passed.

## 2026-09-27 - Synchronize Shared Data Contract

Type: contract
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/DATA_CONTRACT.md
- docs/CHANGELOG.md

Summary:
- Synchronized the Django copy with root `DATA_CONTRACT.md` through version
  1.0.62.
- Added verified BUY sizing evidence and Dynamic HOLD V1 contract details.

Operator impact:
- No Django runtime behavior, schema, accounting, or trading behavior changed.

Validation:
- Compared the synchronized contract sections with root `DATA_CONTRACT.md`.
- Documentation governance checks and `git diff --check` passed.

## 2026-09-27 - Reconcile Django Roadmap

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- PLAN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Classified existing Django roadmap items against current repository code,
  tests, and documentation.
- Marked `/portfolio_status` and `/last_operations` implemented but requiring
  deployed runtime verification, and retained the bot/Django boundary.
- Consolidated partial Position Status / Sell Explainability work and added
  bounded authentication/Passkey and authenticated-PWA roadmap items.

Operator impact:
- No runtime, trading, authentication, PWA, schema, or shared-contract
  behavior changed.
- The roadmap now prioritizes broken-surface verification before new UX work.

Validation:
- Reviewed command dispatch, handlers, bounded read paths, tests, Exit Status,
  authentication configuration, PWA scope, and required documentation.
- `git diff --check` passed after the documentation edits.

## 2026-09-24 - Clarify Missing SELL Closure Accounting

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md

Summary:
- `/last_operations` now displays unavailable realized PnL when a FILLED SELL has no canonical FIFO closure rows.
- The summary marks realized PnL incomplete without treating missing accounting evidence as zero.

Validation:
- Focused Django tests added.
- Python syntax compilation and `git diff --check` passed.
- Django test execution remains environment-blocked when Django is unavailable.


## 2026-09-24 - Telegram Last SELL Operations

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/PROJECT_STATE.md
- core/views.py

Summary:
- Added allowlisted read-only `/last_operations [N]` Telegram diagnostics for recent FILLED SELL operations.
- Aggregates realized PnL from linked FIFO lot closures and displays each physical SELL operation once.

Operator impact:
- Operators can inspect the newest 1–50 completed SELL operations with normalized reason and summary counts.

Validation:
- Python syntax compilation passed.
- Django tests could not run because Django is not installed in the environment.


## 2026-09-20 - Copy Documentation Backups Only When Changed

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md

Summary:
- Updated `bkpdocs.sh` to preserve existing backup files when their content is
  already identical to the source.
- Added a regression test covering identical, changed, and missing backups.

Operator impact:
- Running the documentation backup script no longer rewrites unchanged files.

Validation:
- `bash tests/test_bkpdocs.sh`
- `bash -n bkpdocs.sh`
- `git diff --check`

## 2026-09-20 - Plan Position Status Sell Explainability

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- PLAN.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Documented a material-first Position Status / Sell Explainability capability
  for the future authenticated PWA.
- Defined the bot-evidence ownership boundary, status classes, freshness
  requirements, partial data availability, and future acceptance criteria.

Operator impact:
- No runtime, trading, schema, production, or Telegram behavior changed.
- The roadmap now distinguishes normal strategy holds from blocked SELL
  lifecycle/execution/accounting states and stale valuation evidence.

Validation:
- Reviewed the existing Exit Status, `/why_not_sell`, shared data-contract,
  architecture, design, project-state, and KPI documentation paths.
- Confirmed no runtime files were changed.

## 2026-09-16 - Synchronize Shared Data Contract

Type: contract
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/DATA_CONTRACT.md
- docs/CHANGELOG.md

Summary:
- Synchronized the dashboard data-contract copy with the newer bot contract.
- Added the documented position-generation, BUY-decision lifecycle retention,
  read-only accounting-repair evidence/recovery/apply controls, supplemental
  repair baseline, and dust-retention invariant sections.

Operator impact:
- Dashboard consumers now have the current upstream contract and its explicit
  read-only/recovery safety boundaries.

Validation:
- Compared the dashboard copy against the root bot contract and confirmed
  both files are byte-for-byte synchronized.

## 2026-09-01 - Show Calculator Input Values

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Added the current official USD and UVA values to the Calculadora UVA PWA
  results area.

Operator impact:
- Users can see which stored quotes are being used for the displayed
  calculation.

Validation:
- Added a focused regression test; execution is pending a Django-enabled
  environment.

## 2026-09-01 - Make BUY Status Classification Coherent

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- `/buy_status` now uses one current portfolio classification for position
  counts, capacity, and material exposure rows instead of mixing stale
  healthcheck counts with current exposure.

Operator impact:
- BUY status consistently reports material, dust, unknown, effective positions,
  remaining slots, and material symbols from the same read-only snapshot.

Validation:
- Focused Telegram BUY-status tests passed, including the stale-healthcheck
  regression and unknown/dust capacity coverage.

## 2026-08-29 - Improve Standalone Calculator PWA UX

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Added the standard viewport declaration to the shared base template.
- Added a calculator-scoped responsive layout with touch-sized controls and a
  single-column small-screen presentation.
- Hid the shared website navbar only for the calculator in standalone display
  mode and added iOS safe-area padding.

Operator impact:
- Installed calculator PWAs focus on the calculator without the website
  navigation; regular browser pages retain their existing navigation.

Validation:
- Focused currencyconverter template tests and the Django test suite passed.

## 2026-08-28 - Synchronize Shared Data Contract Copy

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- DATA_CONTRACT.md
- docs/DATA_CONTRACT.md
- docs/CHANGELOG.md

Summary:
- Synchronized `docs/DATA_CONTRACT.md` byte-for-byte with the canonical bot
  contract at `../binanceBot/docs/DATA_CONTRACT.md`.
- Preserved contract version `1.0.40` and verification date `2026-08-26`.

Operator impact:
- No runtime, database schema, or trading behavior changed.
- Dashboard consumers now have the same documented contract semantics as the
  bot repository.

Validation:
- Verified byte-for-byte equality with the paired contract.

## 2026-08-28 - Add Calculadora UVA PWA

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Added a PWA manifest and service worker scoped to `/currencyconverter/`.
- Kept the authenticated `/dashboard/` route outside the PWA scope and cache.

Operator impact:
- Users may install the calculator/converter independently from the dashboard.

Validation:
- Added focused PWA endpoint and template tests.
- Test execution is blocked in the current environment because pytest is unavailable.


## 2026-08-28 - Use Browser PWA Installation Control

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md

Summary:
- Removed the in-page PWA installation button.
- Kept installation available through the browser address-bar control.

Validation:
- Focused currencyconverter tests passed in `.venv`.

## 2026-07-17 - Harden Telegram Webhook Recovery Path

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/ARCHITECTURE.md
- docs/PROJECT_STATE.md
- docs/CHANGELOG.md

Summary:
- Made allowlisted `/help` a static lightweight path independent of diagnostic
  imports and non-critical Telegram audit persistence.
- Added safe malformed/non-text update handling, duplicate message suppression,
  lazy diagnostics, bounded outbound Telegram delivery, and a cap on portfolio
  snapshot materialization.
- The snapshot cap now selects the newest matching snapshots at SQL level and
  restores ascending chronological order before history/chart processing, so
  fresh snapshots are retained when the 35-day window exceeds the cap.
- Added a conservative one-worker/two-thread Gunicorn `Procfile` for the 512
  MB Render service.

Operator impact:
- Render recovery must be verified with webhook and outbound delivery evidence;
  a generic service-recovered event remains insufficient proof.

Validation:
- Added a `/help` audit-persistence-failure regression test that forces the
  actual `TelegramMessage.objects.create(...)` call to raise `DatabaseError`,
  then verified focused webhook and existing Telegram command tests.
- Added portfolio snapshot-cap regression tests for newest-row selection,
  deterministic equal-timestamp ordering, chronological presentation, and
  fresh-history availability above the cap.
- Python compile validation and whitespace validation passed.

## 2026-07-10 - Synchronize Shared Data Contract Copies

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- DATA_CONTRACT.md
- docs/DATA_CONTRACT.md
- docs/CHANGELOG.md

Summary:
- Merged the newer shared-contract additions into the dashboard documentation
  copy and synchronized both copies at data-contract version 1.0.25.
- Clarified bot-produced VPS disk-health payload semantics and optional
  per-symbol snapshot valuation evidence.

Operator impact:
- No runtime, database schema, or trading behavior changed.

Validation:
- Verified both contract copies are byte-identical.
- Ran Markdown/reference and whitespace validation.

## 2026-07-09 - Bot Healthcheck VPS Disk Usage

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Changed dashboard and Telegram `/health` Disk Usage to read latest
  `bot.bot_healthcheck.details.disk_usage`.
- Missing or malformed bot-persisted disk data now renders `Unavailable`.
- Django no longer measures `shutil.disk_usage("/")` for this operator surface
  and must not label Django/Render host disk usage as VPS health.

Operator impact:
- Disk Usage now represents bot VPS health only when the bot healthcheck
  persisted a valid payload.
- Public `/health/` remains Django liveness only and unchanged.

Validation:
- Added failing tests first for dashboard VPS disk rendering, Telegram VPS disk
  rendering, missing/malformed disk payloads, and public `/health/` liveness.
- Python compile validation passed for edited `dashboard` and `core` modules.
- Django test execution is blocked in this environment because Django is not
  installed in the available Python interpreter.

## 2026-07-08 - Telegram Health Disk Usage

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md

Summary:
- Added a `Disk Usage` section to Telegram `/health`.
- Reused the dashboard Disk Usage helper so filesystem `/`, used percent, free
  GB, and OK/warning/critical thresholds stay identical to the dashboard.
- Disk collection failure renders `Unavailable` and the rest of the `/health`
  message continues rendering.
- No shell command, cron, Celery task, persistence, database schema change,
  Binance integration, trading behavior, dashboard behavior, or new endpoint
  was added.

Operator impact:
- Operators can now check Django host disk pressure from Telegram on mobile.
- `/health` still reports bot health when disk information is unavailable, and
  still reports Disk Usage when the latest bot healthcheck row is missing.

Validation:
- Added failing Telegram `/health` tests first for OK, warning, critical,
  unavailable, and missing-healthcheck disk rendering.
- Focused Telegram `/health` disk tests passed.
- `core.tests` passed.
- `git diff --check` passed.

## 2026-07-08 - Dashboard Disk Usage Health

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md

Summary:
- Added an authenticated dashboard Disk Usage card for the Django host
  filesystem `/`, collected on demand through `shutil.disk_usage()`.
- The card shows filesystem, used percent, free GB, and status.
- Disk status is OK below 70% used, warning from 70% through 85%, critical
  above 85%, and `Unavailable` when collection fails.
- No shell command, background job, persistence, database table, bot runtime
  change, or shared healthcheck payload change was added.

Operator impact:
- Operators can see host disk pressure in the normal dashboard health view
  before artifact growth becomes an operational problem.
- If filesystem information cannot be collected, the dashboard keeps loading
  and the disk section reports `Unavailable`.

Validation:
- Added failing tests first for OK/warning/critical classification,
  unavailable fallback, and dashboard rendering.
- Focused disk usage tests passed.
- `core.tests.DashboardEndpointTests` passed.

## 2026-06-29 - Portfolio Status 24h Equity Drivers

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Added a compact `24h equity drivers` section to Telegram `/portfolio_status`
  after `Portfolio equity` and before `Today's trading (UTC)`.
- Kept the section on the graceful fallback state, `unavailable`, because no
  verified Django snapshot read path for symbol-level 24h attribution is wired
  in this patch.
- Renamed the former current unrealized contributor block to
  `Current unrealized contributors` so it is not confused with 24h equity
  attribution.
- Reserved the observational line label `Open-position contribution` for any
  future verified attribution payload, avoiding the stronger `Explained`
  wording.

Operator impact:
- Operators no longer see current unrealized contributors presented as 24h
  movement drivers.
- Symbol-level 24h attribution remains unavailable rather than fabricated;
  Django does not add snapshot-column dependencies, infer SELL coverage, call
  Binance, trade, or mutate bot-owned tables.

Validation:
- Added failing formatter/read-model tests first for unavailable attribution,
  no `Snapshot.portfolio` model-field dependency, observational contribution
  wording, unchanged 24h/7d/30d equity windows, current-unrealized label
  separation, and read-only manager behavior.
- Focused Telegram Portfolio Status tests passed.

## 2026-06-29 - KPI Registry Copy Merge

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/KPI_REGISTRY.md

Summary:
- Merged the incoming root `KPI_REGISTRY.md` copy into the canonical
  `docs/KPI_REGISTRY.md` registry.
- Added bot-local Portfolio Status history, bot cycle timing, cooldown
  recommendation, stop-loss outcome, and Portfolio Status PnL-context metric
  taxonomy from the incoming version.
- Preserved the registry as documentation and observability governance only;
  no Django runtime output, trading behavior, schema, logging, or shared data
  contract changed.

Operator impact:
- Operators and future Codex tasks have a more complete canonical KPI naming
  reference while Django behavior remains unchanged.

Validation:
- Verified the merged registry body matches the incoming root registry copy;
  only the local `doc_version` and `last_verified_at` header values differ.
- Ran `git diff --check -- docs/KPI_REGISTRY.md docs/CHANGELOG.md`.
- Verified the expected merged KPI sections are present.
- Confirmed this is documentation-only and does not require behavior tests or
  schema/DER generation.

## 2026-06-26 - Portfolio Status Performance Sections

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Reorganized the Telegram `/portfolio_status` text after `Total` into a
  `Performance` section with `Portfolio equity`, `Today's trading (UTC)`, and
  `Open positions` subsections.
- Renamed the realized line from `Realized today (UTC)` to
  `Realized closed trades` and the current unrealized line from `Unrealized`
  to `Unrealized now`.
- Preserved the existing accounting, open-position valuation, snapshot-backed
  24h/7d/30d equity changes, HTML formatting, and equity PNG chart behavior.

Operator impact:
- Operators can more easily see that 24h/7d/30d equity movement, current UTC
  closed-trade realization, and current open-position unrealized PnL are
  separate windows/snapshots and should not be summed.

Validation:
- Added failing formatter expectations first for the new `Performance`
  structure, replacement labels, old-label absence, 24h/7d/30d retention, and
  unavailable-state rendering.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

## 2026-06-25 - Codex Task Mode Governance

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- AGENTS.md
- .codex/hooks/README.md
- docs/CHANGELOG.md

Summary:
- Compared the dashboard workflow instructions with the bot project workflow
  reference.
- Added explicit `STANDARD`, `INVESTIGATION`, `PLANNING`, and `DOCUMENTATION`
  task modes to `AGENTS.md`.
- Preserved `STANDARD` as the required fallback for implementation, mixed
  tasks, uncertain scope, and protected workflow infrastructure changes.
- Clarified that hook validation applies to project-state changes and that
  read-only modes must stop without mutating files.

Operator impact:
- Future Codex work can use narrower read-only modes for investigations or
  plans without weakening the protected workflow path for real changes.
- Protected workflow infrastructure changes still require explicit approval,
  separate planning, validation, diff summary, and manual review before commit.

Validation:
- Planned as a protected workflow infrastructure update.
- Confirmed no application behavior, runtime logging, schema, contract, KPI,
  or operator-output semantics changed.

## 2026-06-25 - Portfolio Status Equity Chart Readability

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md

Summary:
- Improved the Telegram `/portfolio_status` equity PNG by downsampling the
  visual 7-day series to a bounded bucketed set of points.
- Kept the last valid point in each time bucket and excluded chart-only equity
  jumps above 25% from the previously accepted visual point.
- Removed visible point markers and added a simple `Equity history` title with
  softer grid styling.

Operator impact:
- The Telegram chart should read as a cleaner equity curve on mobile while the
  Equity, Free USDT, Open value, PnL, Change, PnL context, and Top contributor
  text values remain unchanged.
- Snapshot source rules remain unchanged: only `source = "bot_cycle"` rows with
  valid positive `notes.portfolio_equity_usdt` can feed history, and
  `open_value_usdt` is still not a fallback.

Validation:
- Added failing chart tests first for source isolation, missing canonical
  equity rejection, bucketed max-point downsampling, last-point-per-bucket
  retention, chart-only outlier filtering, textual change preservation, and
  skipping PNG rendering when the visual series has fewer than two points.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

## 2026-06-24 - Portfolio Status PnL Context Label

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md
- PLAN.md

Summary:
- Renamed the Telegram `/portfolio_status` section from `24h drivers` to
  `PnL context`.
- Preserved the existing `Realized:` and `Unrealized:` lines and their
  `none` versus `unavailable` behavior.
- Left historical per-symbol attribution for the snapshot-backed 24h equity
  delta out of scope as a separate follow-up.

Operator impact:
- Operators no longer see wording that implies the current UTC-day realized
  PnL and current unrealized contributor fully explain the 24h snapshot delta.

Validation:
- Added failing formatter expectations first for the new title, old-title
  absence, preserved realized/unrealized rows, preserved empty/unavailable
  states, and Change block separation.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

## 2026-06-24 - Portfolio Status Driver Empty State

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md

Summary:
- Updated `/portfolio_status` realized 24h driver rendering to distinguish
  missing evidence from a successful empty contributor result.
- `realized_drivers is None` still renders `unavailable`; an empty list now
  renders `none`.

Operator impact:
- Operators can tell the difference between a read/evidence gap and a clean
  current UTC-day result with no realized driver to report.

Validation:
- Added focused failing tests first for `None`, empty list, contributor list,
  and existing section preservation.
- Focused Telegram Portfolio Status tests passed.

## 2026-06-24 - Portfolio Status 24h Drivers

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Added a compact `24h drivers` section to Telegram `/portfolio_status`.
- Realized drivers use read-only `bot.trade_operations` day-window evidence
  and linked `bot.lot_closures` PnL grouped by symbol.
- Unrealized drivers use current open-lot PnL from `position_lots` plus
  `portfolio.current_price` as an approximate current contributor, not exact
  historical attribution.

Operator impact:
- Operators can see the main realized and current unrealized symbol driver
  near the existing 24h portfolio change without Binance calls, trading logic
  changes, bot-owned writes, or schema changes.
- Missing or incomplete evidence renders `unavailable` instead of invented
  attribution.

Validation:
- Added failing tests first for realized loss driver output, current
  unrealized worst-driver output, unavailable degradation, existing section
  preservation, UTC-day realized grouping, and read-only behavior.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

## 2026-06-20 - Data Contract Copy Merge

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- DATA_CONTRACT.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md

Summary:
- Merged the root and `docs/` data-contract copies so both carry the same
  `portfolio_snapshots` contract text.
- Preserved bot-side physical-column and canonical metadata notes while keeping
  the current dashboard rule that Portfolio Status history reads only
  `source = "bot_cycle"` rows with valid `notes.portfolio_equity_usdt`.
- Removed stale paired-dashboard follow-up wording because the inspected Django
  reader already filters `bot_cycle` snapshots and avoids open-value fallback.

Operator impact:
- No runtime behavior, schema, logging, Telegram, dashboard output, or trading
  behavior changed.

Validation:
- Compared both contract copies before the merge.
- Inspected current `Snapshot` mapping and Portfolio Status snapshot reader for
  consistency with the merged wording.

## 2026-06-20 - Portfolio Status Bot-Cycle History

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Updated `/portfolio_status` historical change and chart reads to use only
  `bot.portfolio_snapshots` rows with `source = "bot_cycle"` and valid
  `notes.portfolio_equity_usdt`.
- Preserved rejection of missing/invalid canonical equity and
  `open_value_usdt` fallback behavior.
- Added the read-only Django model mapping for the existing
  `portfolio_snapshots.source` column; no migration or bot-owned write path was
  introduced.

Operator impact:
- Legacy or API-sync snapshots with `source = "portfolio_sync_from_api"` no
  longer influence 24h/7d/30d changes or the Telegram equity chart, preventing
  mixed-valuation history.
- Historical windows remain `unavailable` until enough valid bot-cycle
  snapshots exist in the configured tolerance windows.

Validation:
- Added focused failing tests first for bot-cycle acceptance, API-sync
  rejection, missing canonical equity rejection, no `open_value_usdt` fallback,
  24h availability with sufficient bot-cycle history, and chart source
  isolation.
- Focused Telegram Portfolio Status tests passed.
- `core.tests` passed.

Known follow-up:
- Verify and synchronize the paired bot repository `docs/DATA_CONTRACT.md` and
  `docs/KPI_REGISTRY.md` copies when that repository is available.

## 2026-06-19 - Portfolio Status Canonical Equity Snapshots

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Updated `/portfolio_status` history and chart reads to use
  `bot.portfolio_snapshots.notes.portfolio_equity_usdt` as the only canonical
  historical equity source.
- Ignored snapshots without valid positive `portfolio_equity_usdt`, including
  legacy `data.portfolio_equity_usdt` and `open_value_usdt`-only payloads.
- Preserved the existing 24h/7d/30d tolerance windows and in-memory Telegram
  chart rendering; no backfill, Binance calls, or bot-owned writes were added.

Operator impact:
- 24h change becomes available once production has a valid canonical snapshot
  inside the 18-30h window and a fresh latest canonical snapshot.
- 7d/30d remain unavailable until enough canonical history exists.
- Chart rendering becomes available with at least two valid canonical 7-day
  points.

Validation:
- Added focused failing tests first for canonical `notes.portfolio_equity_usdt`,
  missing/invalid canonical equity, legacy `data` rejection,
  `open_value_usdt` rejection, 24h availability, chart availability, and 7d/30d
  insufficient-history behavior.
- Focused Telegram Portfolio Status tests passed.
- `core/tests.py` passed.

Known follow-up:
- Verify and synchronize the paired bot repository `docs/DATA_CONTRACT.md` and
  `docs/KPI_REGISTRY.md` copies when that repository is available.

## 2026-06-16 - Portfolio Status Open Value Naming

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/KPI_REGISTRY.md

Summary:
- Renamed the internal `/portfolio_status` open-position valuation field to
  `open_value_usdt`, replacing the previous invested-capital wording.
- Updated the KPI registry canonical metric to
  `portfolio_status_open_value_usdt`.
- Preserved the existing `Open value` Telegram label and valuation formula.

Operator impact:
- Runtime output, calculations, snapshot history, chart generation, Telegram
  delivery, SQL queries, and source-of-truth rules are unchanged.

Validation:
- Focused tests were updated first and failed against the old implementation
  with the expected missing `open_value_usdt` key before the service rename.

## 2026-06-16 - Portfolio Status Snapshot Tolerance

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md

Summary:
- Tightened `/portfolio_status` historical change matching so horizon
  snapshots must fall inside deterministic age windows: 18-30h for 24h, 6-8d
  for 7d, and 28-32d for 30d.
- Replaced arbitrary "latest point at or before target" matching with closest
  in-window snapshot selection.
- Preserved chart generation and Telegram delivery behavior; chart availability
  still depends on two usable 7-day points, not on every change horizon being
  available.

Operator impact:
- Historical change values now render `unavailable` when evidence is too old,
  too recent, missing, or incomplete instead of reusing stale snapshots.
- No Binance calls, trading behavior, accounting writes, schema changes, or
  generated image persistence were introduced.

Validation:
- Added failing regression tests for valid, offset-valid, stale, too-recent,
  and insufficient snapshot evidence across 24h, 7d, and 30d horizons.
- Added coverage proving chart availability is independent from complete
  horizon-change availability.
- Focused portfolio-status and broader Telegram diagnostics tests passed.

## 2026-06-16 - Telegram Portfolio Status V2

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DATA_CONTRACT.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Added snapshot-backed 24h/7d/30d portfolio change calculations for
  `/portfolio_status`, using only explicit reliable equity/account-value USDT
  fields from `bot.snapshots.data`.
- Added a dependency-free, transport-agnostic in-memory PNG renderer for the
  initial 7-day equity chart.
- Updated Telegram delivery so `/portfolio_status` sends the PNG as a photo
  with the text summary as caption when enough history exists, falls back to
  text if image delivery fails, and sends text only with a compact unavailable
  note when history is insufficient.
- Preserved the read-only dashboard boundary: no Binance calls, no trades, no
  bot-owned accounting mutations, no generated image persistence, and no
  historical values inferred from missing data.

Operator impact:
- Operators can see historical portfolio deltas and a compact 7-day equity
  chart when the bot has produced usable snapshots.
- Missing, stale, incomplete, or ambiguous snapshot history still renders as
  unavailable instead of zero.

Validation:
- Added failing tests first for 24h available, 7d available, 30d unavailable,
  no snapshots, stale/incomplete snapshots, valid PNG bytes, Telegram photo
  delivery, image-send fallback, and text-only fallback.
- Focused portfolio-status tests passed.
- Broader Telegram diagnostics tests passed, including existing `/buy_status`
  coverage.
- `core/tests.py` passed.

Known follow-up:
- Formalize and synchronize the canonical bot-side `bot.snapshots` equity
  payload/freshness rule and paired KPI registry copy when that repository is
  available.

## 2026-06-15 - Telegram Portfolio Status

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Added the allowlisted read-only `/portfolio_status` Telegram command and
  command-guide entry.
- Added a dedicated portfolio summary service that uses open FIFO lots for
  quantity and cost basis, portfolio projection prices for valuation, latest
  healthcheck details for free USDT, and UTC-day linked lot closures for
  realized PnL.
- Added current valued open-lot exposure and projection equity, plus
  material-only aggregate unrealized PnL and best/worst contributors with
  conservative unavailable handling.
- Applied the existing healthcheck stale threshold to free USDT and portfolio
  projection timestamps so old or timestamp-less live values are unavailable.
- Left 24h/7d/30d changes unavailable because the shared snapshot contract does
  not yet define a verified equity payload or freshness rule.
- Recorded dynamic on-demand 7d PNG chart delivery as a follow-up; no generated
  images are persisted.

Operator impact:
- Operators can review portfolio performance separately from BUY capacity.
- The current valuation of open positions is labeled `Open value` to avoid
  implying historical invested capital or cost basis.
- Missing prices, missing entry data, and unavailable history are visible and
  are not silently treated as zero.
- The command performs no Binance calls and no bot-owned table mutations.

Validation:
- Added failing tests before implementation for routing, help, empty state,
  positive/negative unrealized PnL, missing valuation inputs, UTC realized PnL
  wiring, contributor selection, unavailable history, and read-only behavior.
- Focused portfolio-status tests passed.
- Full pytest suite: 241 passed plus 12 subtests.
- Python compilation and `git diff --check` passed.

Known follow-up:
- Synchronize the new dashboard portfolio-status KPI entries into the canonical
  bot repository `docs/KPI_REGISTRY.md`; that paired file is outside this
  workspace's writable scope.

## 2026-06-13 - Telegram BUY Status PnL Summary

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Added a compact `/buy_status` PnL section separating open-position
  projection PnL from accounting-realized PnL for the current UTC calendar
  day.
- Reused the existing `bot.portfolio` projection formula for open PnL.
- Aggregated open PnL across all material positions independently of the
  eight-row mobile display cap, and rendered it as unavailable if any material
  valuation or entry price is unavailable.
- Sourced realized PnL from `bot.lot_closures.realized_pnl`, using linked
  `trade_operations.executed_at` with `created_at` fallback only when execution
  time is null, inside the UTC interval `[00:00, next 00:00)`.
- Labeled the Telegram value `Realized today (UTC)` and corrected the KPI
  registry's stale closure-date wording.
- Added direct regressions proving the summary includes a ninth material row
  while the visible list remains capped at eight, and that the realized label
  explicitly names UTC.

Operator impact:
- Operators can distinguish open projection performance from realized trading
  results without treating either value as Binance's proprietary "Today's
  PNL."
- The Telegram value matches Analytics UTC calendar-day grouping and is
  explicitly distinct from Daily Audit's rolling previous-24h window.
- BUY capacity, dust/material classification, cooldowns, synchronization,
  accounting mutation, and trade execution are unchanged.

Validation:
- Added failing regression proof for an eight-row-only summary and for a
  realized label without the explicit UTC qualifier.
- Covered positive, negative, zero, mixed, empty, over-eight-position,
  unavailable-input, compact-layout, and exact UTC operation-timestamp boundary
  behavior.
- Ran focused PnL tests: 13 passed plus 5 boundary subtests.
- Ran `core/tests.py`: 195 passed plus 12 subtests.
- Ran the full pytest suite: 228 passed plus 12 subtests.

## 2026-06-11 - BUY Status Dust Exposure Classification

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Fixed Telegram `/buy_status` material-exposure rendering so display rows are
  defensively classified by `quantity * current_price >= DUST_MIN_NOTIONAL_USDT`.
- Added nested `healthcheck.details.position_classification` support while
  preserving existing flat healthcheck classification compatibility.
- Added regressions for WLDUSDT-like tiny residuals, material positions above
  threshold, unknown valuation rows, and stale material-symbol display data.

Operator impact:
- Tiny residuals such as `0.0884 WLDUSDT * 0.4367 = 0.03860428 USDT` can no
  longer appear under Material Exposure in `/buy_status`.
- Unknown-price positive rows remain visible as unknown value and continue to
  consume effective capacity.

Validation:
- Added failing BUY-status formatter regression before the fix.
- Ran focused Telegram BUY-status tests.

## 2026-06-10 - Pre-commit Evidence Function Fix

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md

Summary:
- Fixed protected pre-commit workflow validation so it no longer calls removed
  or undefined evidence helpers.
- Aligned pre-commit evidence checks with the documented high/medium/low risk
  model: high-risk changes require common and conditional evidence, medium-risk
  changes require common evidence with secondary warnings, and low-risk changes
  warn instead of failing solely for missing workflow evidence.
- Updated the hook self-check fixtures so behavior and KPI scenarios include
  the documentator evidence required by current governance.

Protected workflow files changed:
- `.codex/hooks/pre-commit.sh`
- `.codex/hooks/self-check.sh`

Operator impact:
- Commits no longer abort with `require_workflow_order: command not found`.
- Protected workflow infrastructure changes remain blocked unless
  `ALLOW_WORKFLOW_INFRA_CHANGE=1` is intentionally set for reviewed commits.

Validation:
- Reproduced the failure with `.codex/hooks/self-check.sh` before the fix.
- Ran shell syntax validation for touched hook scripts and related helper
  libraries.
- Ran `.codex/hooks/self-check.sh`: passed.

## 2026-06-10 - Render Python Runtime Pin

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/CHANGELOG.md
- docs/PROJECT_STATE.md

Summary:
- Documented that Django 5.2 requires Python 3.10 or newer and that Render
  native Python deployments should use the repository `.python-version` file.
- Recorded the Render precedence caveat: a service-level `PYTHON_VERSION`
  environment variable overrides `.python-version` and can keep deployments on
  an incompatible old Python runtime.
- Updated stale README stack text from the previous Django 3.2 reference to the
  current Django 5.2 LTS dependency line.

Operator impact:
- Render deploys should stop failing with `No matching distribution found for
  Django<5.3,>=5.2` after the compatible Python runtime pin is committed and no
  older `PYTHON_VERSION` override remains configured.

Validation:
- Verified local `python3 --version` reports Python 3.13.7.
- Verified `.python-version` is present locally with `3.12.9`, which is
  compatible with Django 5.2.
- Verified no application behavior, logging, data contract, or schema changed.

## 2026-06-09 - Telegram BUY Status Material PnL

Type: behavior
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/KPI_REGISTRY.md
- docs/PROJECT_STATE.md

Summary:
- Extended Telegram `/buy_status` material exposure rows with display-only
  unrealized PnL in USDT and percent, computed only from `bot.portfolio`
  projection fields already used by the BUY-status exposure view.
- Kept BUY capacity semantics unchanged: effective positions, material/dust/
  unknown counts, and remaining capacity were not recalculated.
- Kept dust PnL out of the message and preserved the existing material row cap
  for mobile message size.
- Updated local dependencies to the Django 5.2 LTS line and declared
  `pytest`/`pytest-django` in `requirements.txt` so tests run under Python
  3.13.

Operator impact:
- Operators can now see approximate current PnL beside each displayed material
  position in `/buy_status`.
- Rows with missing, invalid, or non-positive `entry_price` show
  `PnL unavailable` rather than a misleading zero.

Validation:
- Added failing formatter/test expectations before the final implementation.
- Ran focused Telegram BUY-status test.
- Ran `core/tests.py`.
- Ran full pytest suite: 208 passed, 1 Django 6.0 deprecation warning from DRF
  format suffix registration.

## 2026-05-25 - BUY Re-entry Cooldown Diagnostics Rendering

Type: contract
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md

Summary:
- Updated Telegram `/buy_status` and the dashboard BUY/Cooldown card to render
  extended bot-persisted cooldown diagnostics from latest healthcheck details.
- Added null-safe and Decimal-safe display for latest SELL operation, symbol,
  executed timestamp, nullable reason, reason source, realized PnL, cooldown
  type, classification source, elapsed minutes, and remaining minutes.
- Preserved legacy payload compatibility for `latest_sell_timestamp`,
  `cooldown_type = sell`, and `cooldown_type = generic_sell`.
- Normalized legacy `cooldown_type = sell` and bot-side
  `cooldown_type = generic_sell` to the same operator label, `recent sell`,
  so old and new payloads render compatibly.

Operator impact:
- BUY cooldown pages no longer show ambiguous `N/A` when the bot persisted
  usable cooldown context.
- Django remains a read-only observer and does not infer cooldowns or write to
  bot-owned trading tables.

Validation:
- Added failing tests first for full metadata, partial/null metadata, legacy
  payload compatibility, classification rendering, and dashboard fallback
  behavior.
- Added final review tests for `generic_sell` compatibility and stable
  realized-PnL formatting across null, zero, positive, negative, Decimal-string,
  scientific-notation, and invalid values.
- Ran `.venv/bin/python -m pytest core/tests.py`.
- Verified `docs/DATA_CONTRACT.md` is synchronized with
  `/home/cristhian/Dev/binanceBot/docs/DATA_CONTRACT.md`.

## 2026-05-25 - Codex Hook Symlink Execution Fix

Type: operations
Runtime version: unknown
Schema version: unknown
Docs affected:
- docs/CHANGELOG.md

Summary:
- Fixed the Git pre-commit hook path resolution when `.git/hooks/pre-commit`
  is installed as a symlink to `.codex/hooks/pre-commit.sh`.
- Added self-check coverage for invoking the hook through the installed Git
  hook symlink.

Operator impact:
- Commits no longer fail before validation with a missing `.git/lib/common.sh`
  error.
- Protected workflow infrastructure changes still require manual review and
  `ALLOW_WORKFLOW_INFRA_CHANGE=1` when committing.

Validation:
- Reproduced the original missing helper-library failure before implementation.
- Ran hook syntax checks, `.codex/hooks/self-check.sh`, and the installed Git
  pre-commit hook after the fix.

## 2026-05-21 - Capital Efficiency Documentation Merge

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md

Summary:
- Merged the downloaded 2026-05-21 Django documentation update fragments into
  the existing documentation without replacing richer current content.
- Moved historical/evolutionary notes toward changelog coverage and kept README
  focused on operator usage and boundary rules.
- Recorded planned trapped-capital analytics, capital-days / holding-efficiency
  metrics, and time-based exit dry-run observability as future read-only
  dashboard surfaces.
- Reaffirmed that Django should consume bot-owned or shared-contract analytics
  outputs instead of reconstructing accounting truth independently.

Operator impact:
- No application behavior changed.
- No database schema changed.
- No shared data-contract semantics changed.

Validation:
- Confirmed the incoming update set did not include a `DATA_CONTRACT.md`
  fragment.
- Confirmed the Django `docs/DATA_CONTRACT.md` copy remains byte-for-byte
  synchronized with `/home/cristhian/Dev/binanceBot/docs/DATA_CONTRACT.md`.
- Confirmed no generated DER/schema artifacts were needed because no schema or
  contract change occurred.

## 2026-05-20 - Documentation Governance Merge

Type: docs
Runtime version: unknown
Schema version: unknown
Docs affected:
- README.md
- PLAN.md
- docs/ARCHITECTURE.md
- docs/CHANGELOG.md
- docs/DESIGN.md
- docs/PROJECT_STATE.md
- docs/DATA_CONTRACT.md

Summary:
- Merged the downloaded 2026-05-20 documentation-governance additions into the
  existing Django dashboard docs without replacing richer existing content.
- Added lightweight version headers to touched core documentation files.
- Recorded planned schema/DER visibility, docs freshness validation, and
  runtime/version logging governance as planned operational work.
- Verified that the Django `docs/DATA_CONTRACT.md` copy and the bot project
  `/home/cristhian/Dev/binanceBot/docs/DATA_CONTRACT.md` copy were identical at
  merge time.

Operator impact:
- No application behavior changed.
- No database schema changed.
- Operators now have changelog coverage for documentation-governance changes.

Validation:
- Confirmed the incoming `DJANGO_DATA_CONTRACT.md` governance content was
  already represented in the synchronized shared contract.
- Confirmed no generated DER/schema artifacts were created because no schema
  change occurred.
