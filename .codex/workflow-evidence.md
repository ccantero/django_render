# Workflow evidence — Position generation schema verification (2026-10-27)

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
impact: contract
tests_executed: focused pytest core/test_telegram_position_modes.py 24 passed after test_mapping_is_unmanaged_read_only failed because symbol.null was true; full pytest 461 passed, 3 skipped, 44 subtests; manage.py check no issues; makemigrations --check --dry-run no changes; disposable PostgreSQL 16.15 database position_mode_scratch applied 17 bot SQL files with no failures and Django format_position_modes plus format_position_mode completed
pending_issues: production SELECT grant remains a deployment blocker. Operator must run SELECT has_table_privilege(current_user,'bot.position_generations','SELECT'), has_column_privilege(current_user,'bot.position_lots','generation_id','SELECT'); tracking issue https://github.com/ccantero/binancebot/issues/10. Existing position_lots and portfolio numeric fields stay max_digits 36 while bot SQL 012 uses NUMERIC(38,18). Diagnostics API active_generation payload left unavailable. Paired binancebot repository was not modified. No generated DER.
tests_created: extended test_mapping_is_unmanaged_read_only for phase and provenance choices, VARCHAR lengths, and NOT NULL columns from bot SQL 103 and 105
failing_test_proof: before the model edit, test_mapping_is_unmanaged_read_only failed with AssertionError True is not false on symbol.null
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: docs/DATA_CONTRACT.md 1.0.65, docs/PROJECT_STATE.md 1.1.41, docs/CHANGELOG.md 1.1.54. README.md, PLAN.md, DESIGN.md, ARCHITECTURE.md, and KPI_REGISTRY.md were reviewed and left unchanged because operator formulas and command wording did not change.
changelog: updated
schema_der: follow_up: unmanaged read-only mapping; scratch database was disposable and not a generated docs/db snapshot
data_contract_sync: follow_up: dashboard DATA_CONTRACT.md updated from the supplied SQL; ccantero/binancebot was not modified
logging_observability: unchanged. Generation read errors and failed chunk sends keep their existing fields.
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available

# Workflow evidence — Position mode review corrections (2026-10-27)

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
impact: behavior, contract
tests_executed: focused pytest core/test_telegram_position_modes.py 24 passed after a red run (overlong line stayed one chunk, overlong /position_mode field was 4833 characters, /position_modes issued no lot query, detail still said Consistency); full pytest 461 passed, 3 skipped, 44 subtests; manage.py check no issues; makemigrations --check --dry-run no changes
pending_issues: DEPLOYMENT BLOCKER remains. ccantero/binancebot returned HTTP 404, so src/sql/103, 105, 106, and 108 were not read and were not applied to disposable Postgres. Docker is not installed. Production SELECT was not granted and was not queried. Operator must run SELECT has_table_privilege(current_user,'bot.position_generations','SELECT'), has_column_privilege(current_user,'bot.position_lots','generation_id','SELECT'); tracking issue https://github.com/ccantero/binancebot/issues/10. Diagnostics API active_generation payload left unavailable. Paired binancebot docs were not updated. No generated DER. AGENTS.md was not edited.
tests_created: core/test_telegram_position_modes.py adds overlong HTML line split, multi-chunk /position_mode with 40 CLOSED generations, mixed assigned and unassigned summary qualifier, and MATCH with closed or missing generation associations
failing_test_proof: before the fix, test_overlong_line_is_split_outside_entities_and_tags returned one chunk, test_position_mode_overlong_field_and_large_closed_history_is_split failed because a chunk was 4833 characters, test_summary_qualifies_mixed_assigned_and_unassigned_lots found 0 lot queries, and test_quantity_comparison_reports_bad_associations_when_totals_match still rendered Consistency MISMATCH
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: docs/DESIGN.md 1.1.36, docs/DATA_CONTRACT.md 1.0.64, docs/PROJECT_STATE.md 1.1.40, docs/ARCHITECTURE.md 1.1.24, docs/CHANGELOG.md 1.1.53, docs/KPI_REGISTRY.md 1.0.38. README.md and PLAN.md were reviewed and left unchanged because they do not describe chunk boundaries or the comparison label.
changelog: updated
schema_der: follow_up: no schema change and no bot SQL files were reachable, so docs/db snapshots were not generated
data_contract_sync: follow_up: dashboard DATA_CONTRACT.md updated; ccantero/binancebot was not readable and was not modified
logging_observability: no new log fields. Existing generation read errors and failed chunk sends keep stage, command, chat_id, and exception_class. Replies still omit SQL and secrets. app_version remains unknown on this path, matching other Telegram diagnostics.
kpi_registry_reviewed: yes
kpi_registry_updated: yes
kpi_registry_sync_checked: not-available

# Workflow evidence — Telegram position generation modes (2026-10-27)

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
impact: behavior, contract, logging
tests_executed: focused pytest core/test_telegram_position_modes.py 20 passed after a red run (3 failed, 17 errors: PositionGeneration missing, commands unregistered, chunk send not logged); full pytest 457 passed, 3 skipped, 44 subtests; manage.py check no issues; makemigrations --check --dry-run no changes
pending_issues: SELECT grant on bot.position_generations is unverified and fails safe; diagnostics API active_generation payload left unavailable; paired binancebot DATA_CONTRACT and KPI registry were not updated because that repo is out of scope; no generated DER because no bot database was connected; AGENTS.md still says VERSION 2.0.0 and was not edited because it is protected workflow infrastructure
tests_created: core/test_telegram_position_modes.py covers HOLD, TRADING, mixed, inconsistent, unrecognized phase, CLOSED historical, unknown, generationless lots, quantity mismatch, invalid symbols, message split, DatabaseError, permission denied, authorization, stale and missing healthcheck, chunk send failure, and existing command regression
failing_test_proof: initial pytest of the new file failed before implementation with ImportError for PositionGeneration, AssertionError that /position_modes was not registered, unauthorized returning None, and no WARNING log for chunk delivery
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: README.md 1.1.39, PLAN.md 1.1.23, docs/PROJECT_STATE.md 1.1.39, docs/ARCHITECTURE.md 1.1.23, docs/DESIGN.md 1.1.35, docs/DATA_CONTRACT.md 1.0.63, docs/CHANGELOG.md 1.1.52, docs/KPI_REGISTRY.md 1.0.37
changelog: updated
schema_der: follow_up: unmanaged read-only mapping only; makemigrations --check clean; no live bot database, so docs/db snapshots were not generated
data_contract_sync: follow_up: dashboard DATA_CONTRACT.md documents the new read model; ccantero/binancebot was not modified
logging_observability: generation read failures log stage, command, chat_id, and exception_class via logger.exception; chunk delivery failure logs stage outbound_chunk, delivered false, and existing webhook context; replies omit SQL and secrets; app_version remains unknown on this path, matching other Telegram diagnostics
kpi_registry_reviewed: yes
kpi_registry_updated: yes
kpi_registry_sync_checked: not-available

# Follow-up merge resolution against 1b8b103 (2026-10-25)

phases_completed: planner, implementer, tester, documentator
impact: operations, docs_only
tests_executed: diagnostics 16 passed and 11 subtests; full suite 437 passed, 3 PostgreSQL-only skips and 44 subtests; Django check clean; Node 11 passed; conflict scan clean; original nine-file PR delta only
pending_issues: remote verification performed after publication and reported in PR description; no new behavioral regression
planner: merge latest remote main into existing branch; reconcile docs and keep API/main behavior; no schema, DER, contract, logging or KPI impact; existing suites protect preservation; risk is losing adjacent documentation changes
tests_created: existing suites retained, no new behavior introduced
failing_test_proof: not needed for merge-only preservation; initial merge reported four documentation conflicts
docs_reviewed: README.md, PLAN.md, docs/PROJECT_STATE.md, docs/ARCHITECTURE.md, docs/DATA_CONTRACT.md, docs/DESIGN.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: README.md 1.1.38, ARCHITECTURE.md 1.1.22, PROJECT_STATE.md 1.1.38, CHANGELOG.md 1.1.51
changelog: updated
schema_der: not_applicable: no new schema changes
data_contract_sync: not_applicable: no shared contract changes
logging_observability: unchanged
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available

---

# Workflow evidence — PR #3 merge-conflict resolution (2026-10-25)

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
impact: operations, docs_only
tests_executed: API pytest 16 passed and 11 subtests; full pytest 392 passed, 3 existing PostgreSQL-only skips and 44 subtests; manage.py check clean with synthetic local settings; Node Passkey tests 3 passed; pip check clean; conflict-marker scan and exact file-preservation comparison passed
pending_issues: no merge-resolution regression; deployment and Work Cloud connectivity verification remain separate; PostgreSQL concurrency tests not exercised by SQLite
planner: reconcile existing PR head 5626e6f with main 60bdcc6, preserving both behaviors; scope limited to conflicts and verification; no new dependencies, auth mechanisms, bot mutations, schema, contract, logging, or DER changes; update conflicting docs metadata/changelog; validate API, full suite, checks, and main preservation; risk is lost documentation or authentication/static setup during merge
implementation: merged main into existing feature/bot-operational-diagnostics-api; resolved five documentation/evidence conflicts using both contents; runtime API and API tests unchanged; no new application behavior introduced by resolution
tests_created: existing API regression suite and main test suites retained byte-for-byte; no new tests needed for merge-only preservation
failing_test_proof: no new behavior change; not a TDD implementation; initial git merge reported five content conflicts, resolved and validated with existing behavioral tests
docs_reviewed: README.md, PLAN.md, docs/PROJECT_STATE.md, docs/ARCHITECTURE.md, docs/DATA_CONTRACT.md, docs/DESIGN.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: README.md 1.1.34, docs/ARCHITECTURE.md 1.1.16, docs/PROJECT_STATE.md 1.1.32, docs/CHANGELOG.md 1.1.46; verification date 2026-10-25
changelog: updated
data_contract_sync: not_applicable: no shared contract change; retained pre-existing paired-document follow-up in API changelog
logging_observability: unchanged; existing sources, freshness, no-store and Bearer semantics retained
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available
kpi_registry_notes: reviewed, no update needed; no metric formula, source or meaning changed
schema_der: not_applicable: no new schema or migration change; main migrations retained unchanged
governance_validation: docs-sync against origin/main passed with zero warnings; pre-commit on detached main worktree with the exact nine-file PR delta passed with zero warnings (inherited main protected files excluded from task delta)
protected_infrastructure: no resolution edits; AGENTS.md and protected hook/lib/template files match main byte-for-byte
warnings: local untracked staticfiles directory absent; existing unordered UserProfile pagination warning
production_actions: none

---

# Historical workflow evidence — Diagnostics API PR #3

phases_completed: planner, implementer, tester, documentator
impact: behavior, contract, operations
tests_executed: .venv/bin/pytest dashboard/test_bot_diagnostics_api.py -q --disable-warnings (16 passed, 11 subtests); .venv/bin/pytest -q --disable-warnings --create-db (344 passed, 44 subtests); base 82e32fd same full-suite command (328 passed, 33 subtests); CC_DEBUG=True with disposable local settings .venv/bin/python manage.py check; git diff --check
pending_issues: PostgreSQL execution unavailable in runner; ChatGPT Work Cloud access unverified; no application-level rate limiter; paired bot DATA_CONTRACT and KPI_REGISTRY copies are behind current bot main and follow-up is recorded

tests_created: API regression cases cover recent/stale/missing/malformed Spot observations; fresh/stale/absent/partial capacity; unsynchronized sources; malformed/missing auth and no-query rejection; write methods
failing_test_proof: Initial focused run failed on the intended missing response fields (observed_spot_quantity, observation_recency, consistency); one new test fixture initially returned the expected 404 because it supplied no inventory evidence and was corrected before final test runs.
docs_reviewed: README.md, PLAN.md, docs/PROJECT_STATE.md, docs/ARCHITECTURE.md, docs/DATA_CONTRACT.md, docs/DESIGN.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: README.md, docs/ARCHITECTURE.md, docs/PROJECT_STATE.md, docs/CHANGELOG.md
changelog: updated
data_contract_sync: not_applicable: no bot-owned table, column, or shared database contract changed; paired source copy lag recorded as a follow-up
logging_observability: reviewed; response semantics changed, no runtime logging or KPI formula changed
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: no
kpi_registry_notes: No KPI definition or formula changed. Current bot main header 1.0.48 differs from dashboard copy 1.0.36; follow-up recorded in changelog.
schema_der: not_applicable: no schema change; disposable PostgreSQL execution was unavailable and no generated schema claim is made

---

# Workflow evidence — Secure Passkeys

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
planner_artifacts_read: AGENTS.md, README.md, PLAN.md, docs/ARCHITECTURE.md, docs/DESIGN.md, docs/PROJECT_STATE.md, docs/DATA_CONTRACT.md, docs/CHANGELOG.md, .codex/skills/planning.md, .codex/skills/tdd.md, .codex/skills/documentation.md
baseline: `.venv/bin/pytest -q` — 328 passed, 33 subtests.
tdd_red: Review-fix tests first failed because dedicated step-up URL names were missing (3 expected NoReverseMatch failures, 17 tests passed before maxfail); added coverage for existing-key proof, identity/session preservation, cross-user credentials, replay/expiry, first-key bootstrap, stale-session proof consumption, CSRF/authentication, and fail-closed rate limiting.
implementation: Added dedicated current-user WebAuthn enrollment step-up endpoints; no login()/OTP login call and no identity/session-key change. Proofs and step-up challenge state are persisted, HMAC-keyed/bound, expired, and atomically consumed under row locks. Added profile migrations 0004/0005. Rate limiter row updates use select_for_update in a transaction; expiry cleanup runs at most once per worker per five minutes.
tests_executed: `pytest tests/test_passkey_auth.py` — 38 passed, 1 warning; `.venv/bin/pytest -q` — 366 passed, 1 warning, 33 subtests passed in 64.60s; Django check — no issues; `makemigrations --check --dry-run` — no changes; Python compileall passed; JavaScript `node --check` passed; `git diff --check` passed; `pip check` reported no broken requirements.
warning: DRF pagination emits UnorderedObjectListWarning for an unordered UserProfile queryset in the token-auth regression test.
security_review: Feature disabled by default; production exact HTTPS origin/RP validation; user verification; dedicated step-up separate from login; current-user credential association; database-enforced one-use challenge/proof consumption; 5-minute TTL; password plus passkey proof for subsequent keys; CSRF; DB-backed transactional HMAC rate limits; fail-closed enforcement; throttled best-effort cleanup; scoped revoke; inactive-user gate; Admin keeps Django checks.
dependency_audit: `pip-audit` unavailable (`python -m pip_audit`: no module). `pip check` passes but does not audit vulnerabilities; full transitive dependency audit remains a rollout gate.
manual_checks: Real Safari/iOS, desktop, Windows Hello, and hardware key verification not available in Work Cloud. Reverse-proxy header overwrite/direct-reachability boundary requires deployment verification.
production_actions: none; no production migrations, credentials, deployment, or external state touched.

## Disposable PostgreSQL passkey harness

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
impact: behavior,docs_only,logging,operations
tests_executed: bash -n scripts/run_passkey_postgres_disposable_test.sh; Python py_compile for guarded settings; synthetic guarded DEBUG=False settings import; in-memory JUnit testsuite/testsuites parser fixtures; git diff --check
tests_created: no new runtime test created: the operator explicitly restricted this task to static validation and prohibited database test execution
failing_test_proof: unavailable: implementation occurred under the operator's explicit static-only restriction, so no failing runtime test was run
pending_issues: authorized operator must execute the harness to obtain PostgreSQL migration, concurrency, full-suite, security-check, version, warning, and cleanup results; docs/CHANGELOG.md is binary data and was not modified
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md (binary data confirmed with file)
docs_updated: README.md, IMPLEMENTATION_CODEX.md
changelog: not_applicable: docs/CHANGELOG.md is binary data in the existing working tree; the report records this blocker without altering the file
logging_observability: no application logging or operator diagnostics changed; the disposable harness emits only non-secret lifecycle and verification status markers
kpi_registry_reviewed: not-needed
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available
kpi_registry_rationale: dashboard/dust_read_model.py change only preserves PostgreSQL transaction usability after an already-handled bot read failure; it adds no KPI, metric, formula, source of truth, dashboard output, or operator diagnostic.

## Pre-merge isolated validation follow-up

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
impact: docs_only plus PostgreSQL test coverage; no production application behavior changed
planner: reviewed README, PLAN, PROJECT_STATE, ARCHITECTURE, DATA_CONTRACT, CHANGELOG, AGENTS, and planning/TDD/documentation workflow; isolated DB and production state explicitly excluded
implementation: added guarded loopback-only `django_render.postgres_test_settings`, PostgreSQL-only threaded tests for proof/challenge/rate-limit concurrency, and a local Safari/iPhone HTTPS runbook
tester: `pip-audit -r requirements.txt --desc` — no known vulnerabilities; local environment audit clean after pip 25.0.1 → 26.2.1; `pytest -q` — 366 passed, 3 PostgreSQL-only skips, 1 existing DRF warning, 33 subtests; disposable SQLite migrations all applied; migration drift check clean; `check --deploy` clean on base and PR
postgresql_blocker: PostgreSQL 16 package service setup was blocked by unavailable setgroups/setuid; `runuser` failed and `initdb` refuses root. No remote DB used. PostgreSQL migration, full suite, and concurrency execution remain unverified.
documentation: README, CHANGELOG, and IMPLEMENTATION_WORK updated; architecture, design, plan, project state, and bot data contract unchanged because no runtime behavior/schema changed in this follow-up
production_actions: none
