---
doc_id: workflow-evidence
doc_version: 1.0.1
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-10-31
source_repo: django_render
---

# Workflow evidence — Render/Django security audit (2026-10-31)

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
impact: docs_only
planner: problem: record a sanitized read-only security audit of the Render/Django app and a status-and-size probe, with no fixes; scope: public-host GET/HEAD, full-history secret scanners, production-like check --deploy on local SQLite, pip-audit, audit report, read-only script and mocked tests; out of scope: fixes, rotation, binancebot, VPS content, DB grants document, GitHub issues, merge, deploy; components: docs/security/AUDIT_2026-11.md, scripts/security/check_exposure.py, tests/test_check_exposure.py, README, PLAN, PROJECT_STATE, CHANGELOG; contract impact: none; logging impact: no runtime log change, probe prints status and size only; versioning: patch touched core doc_version and last_verified_at 2026-10-31, audit doc 1.0.0, evidence 1.0.1, VERSION unchanged; schema/DER: none; test strategy: failing import test, then probe tests, then full pytest; risks: copying secrets into the report, guessing the platform hostname, loading a production database URL
implementation: application behavior did not change; added the read-only probe after tests failed on the missing file; no runtime dependency and no settings, view, model, or URL edit
tests_created: tests/test_check_exposure.py covers HTTP 200 as EXPOSURE, HTTP 404 as PASS, timeout and connection error as UNVERIFIED, HTTP 5xx as UNVERIFIED without a second attempt, response bodies never printed, and the redirect handler returning no follow-up request
failing_test_proof: DJANGO_SKIP_ENV_FILE=1 pytest tests/test_check_exposure.py before the script existed failed 6 tests with FileNotFoundError for scripts/security/check_exposure.py; after implementation the file passed
tests_executed: DJANGO_SKIP_ENV_FILE=1 /tmp/django-audit-venv/bin/pytest tests/test_check_exposure.py -q passed 6 before the redirect test was added and the full file is included in the suite; DJANGO_SKIP_ENV_FILE=1 /tmp/django-audit-venv/bin/pytest -q: 468 passed, 3 skipped, 207 warnings, 44 subtests passed in 55.53s; 206 warnings are the absent generated staticfiles directory and 1 is the existing DRF UnorderedObjectListWarning; 0 failed
pending_issues: no critical finding proven; high findings remain unfixed (public profile list, historical database URL); platform hostname, 2022 credential validity, production allowlist values, production diagnostics token configuration, production logs, and unauthenticated profile writes are NEEDS_RUNTIME_VERIFICATION; VPS section is empty; DB grants remain a separate review; unavailable equity fields remain in django_render issue 12
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md, docs/security/AUDIT_2026-11.md
docs_updated: README.md 1.1.43, PLAN.md 1.1.28, docs/PROJECT_STATE.md 1.1.46, docs/CHANGELOG.md 1.1.59, docs/security/AUDIT_2026-11.md 1.0.0, .codex/workflow-evidence.md 1.0.1; last_verified_at 2026-10-31; ARCHITECTURE, DESIGN, DATA_CONTRACT, and KPI_REGISTRY reviewed, no update needed
changelog: updated
schema_der: not_applicable: no schema or DER change
data_contract_sync: not_applicable: docs/DATA_CONTRACT.md reviewed, no semantic change
logging_observability: reviewed, no runtime logging change; the exposure script prints status and size only and does not print bodies or token values; production logs were not available
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available
governance_validation: bash .codex/hooks/docs-sync.sh staged passed with 0 warnings; bash .codex/hooks/pre-commit.sh passed with 0 warnings
protected_infrastructure: no changes to AGENTS.md or .codex/hooks, .codex/lib, .codex/templates
production_actions: unauthenticated GET and HEAD only against the public hostname; no authenticated requests, no production database connection from Django, no rotation, no merge, no deploy

# Workflow evidence — Production stamp_build verification (2026-10-30)

task_mode: DOCUMENTATION
phases_completed: planner, implementer, tester, documentator
impact: docs_only
planner: problem: owner configured stamp_build and verified version/PWA output; scope: six documentation files only, preserve collectstatic and Telegram evidence and existing main requirements, remove out-of-scope additions from 9aff094/e327264; components: README, ARCHITECTURE, PLAN, PROJECT_STATE, CHANGELOG, workflow evidence; no code, tests, runtime configuration, VERSION, contract, logging, KPI, schema or DER impact; versioning: patch core doc_version and last_verified_at 2026-10-30, introduce previously absent evidence version header at 1.0.0, append corrective changelog entry; test strategy: verbatim evidence, historical evidence preservation, main comparison, diff checks, staged hooks, full pytest; steps: inspect docs and version code, update, validate, review, create one commit on existing branch; risk: treating historical build command as current or changing unrelated requirements
implementation: documentation only; application behavior did not change and no new behavior test was created; current command includes stamp_build, historical collectstatic evidence unchanged, historical pending stamp statements superseded by new changelog entry; no application or protected workflow edits
verification_source: owner-reported 2026-10-30 11:52 ART GET /version/ and matching PWA footer, recorded verbatim in all five core docs; no production request performed
checkout_provenance: e32726444d037b8b4e2d8c850e0378d918bcdef5 on cursor/verify-telegram-runtime-8955
pending_issues: unavailable equity fields remain tracked in django_render#12
tests_executed: DJANGO_SKIP_ENV_FILE=1 /tmp/django-docs-venv/bin/pytest -q: 461 passed, 3 PostgreSQL-only skipped, 207 warnings, 44 subtests passed in 41.40s; 206 warnings are absent generated staticfiles directory and one is existing DRF unordered pagination warning; verbatim new evidence and unchanged historical collectstatic evidence assertions passed; current pending-decision note absence verified; git diff --check passed
governance_validation: bash .codex/hooks/docs-sync.sh staged passed with 0 warnings; bash .codex/hooks/pre-commit.sh passed with 0 warnings
tests_created: no new behavior test because application behavior did not change
failing_test_proof: application behavior did not change; no failing behavior test was created
docs_reviewed: README.md, PLAN.md, docs/PROJECT_STATE.md, docs/ARCHITECTURE.md, docs/DATA_CONTRACT.md, docs/DESIGN.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: README.md 1.1.42, PLAN.md 1.1.27, docs/PROJECT_STATE.md 1.1.45, docs/ARCHITECTURE.md 1.1.26, docs/CHANGELOG.md 1.1.58; workflow evidence initial header 1.0.0; last_verified_at 2026-10-30; DESIGN, DATA_CONTRACT and KPI registry reviewed, no update needed
changelog: updated
schema_der: not_applicable: no schema or DER change
data_contract_sync: not_applicable: no contract change
logging_observability: reviewed, unchanged
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available
production_actions: none; no merge, deploy or production modification

# Workflow evidence — Render readiness revalidation on current PR head (2026-10-30)

task_mode: DOCUMENTATION
impact: docs_only
planner: problem: requested base 395953a advanced to 9aff094, which already implements the requested readiness/command changes; scope: preserve existing docs and verbatim owner evidence, clarify deployment provenance, and add exactly one documentation-only commit to the existing branch; components: README, PLAN, PROJECT_STATE, CHANGELOG, workflow evidence; contract impact: none; logging/observability impact: none; versioning: increment touched doc_version patches, keep last_verified_at 2026-10-30, update changelog, leave VERSION unchanged; schema/DER impact: none; strategy: verify command/evidence text, timestamp code, diff, both staged hooks, full pytest; steps: inspect, clarify docs, validate, review docs, commit and publish with expected-head check; risks: confusing the b61f9fc deployment with the current PR head or successful boot with DB least privilege
implementation: documentation only; application behavior did not change and no new behavior test was created; preserved 9aff094 and all owner-provided evidence; no changes to tests, application code, configuration, VERSION, contracts, schema, hooks, or protected workflow infrastructure
checkout_provenance: cloned existing branch cursor/verify-telegram-runtime-8955 at 9aff094e5a073d24893e38d67f60150694adb0f6; its parent is requested base 395953af934ef327fb5e9a5c4216f540ab681a51
verification_source: owner-provided evidence already reproduced verbatim in PLAN.md, docs/PROJECT_STATE.md, and docs/CHANGELOG.md; no production request performed
pending_issues: unavailable equity fields tracked by django_render#12; stamp_build pending-decision wording below is historical and superseded by the latest entry
tests_created: no new behavior test because application behavior did not change
failing_test_proof: application behavior did not change; no failing behavior test was created
phases_completed: planner, implementer, tester, documentator
tests_executed: DJANGO_SKIP_ENV_FILE=1 /tmp/django-docs-venv/bin/pytest -q: 461 passed, 3 PostgreSQL-only skipped, 207 warnings, 44 subtests passed in 43.64s; 206 warnings report the absent generated staticfiles directory in this fresh checkout and one is the existing DRF UnorderedObjectListWarning; exact owner evidence/commands, stamp_build note, status separation, architecture/design alignment, and version-header assertions passed; git diff --check passed
governance_validation: bash .codex/hooks/docs-sync.sh staged passed with 0 warnings; bash .codex/hooks/pre-commit.sh passed with 0 warnings
docs_reviewed: README.md, PLAN.md, docs/PROJECT_STATE.md, docs/ARCHITECTURE.md, docs/DATA_CONTRACT.md, docs/DESIGN.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: README.md 1.1.40 to 1.1.41; PLAN.md 1.1.25 to 1.1.26; docs/PROJECT_STATE.md 1.1.43 to 1.1.44; docs/CHANGELOG.md 1.1.56 to 1.1.57; last_verified_at remains 2026-10-30; ARCHITECTURE.md already has exact production commands, DESIGN.md has no Build Command; DATA_CONTRACT.md and KPI_REGISTRY.md reviewed, no update needed; workflow evidence prepends this task and preserves history
changelog: updated
schema_der: not_applicable: no schema or DER change
data_contract_sync: not_applicable: no shared contract change
logging_observability: reviewed, unchanged; no runtime logging, diagnostics, or operator output changes
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available
protected_infrastructure: no changes to AGENTS.md or .codex/hooks, .codex/lib, .codex/templates
production_actions: none; no production request, runtime configuration change, merge, or deploy

# Workflow evidence — Render command/boot readiness (2026-10-30)

task_mode: DOCUMENTATION
phases_completed: planner, implementer, tester, documentator
impact: docs_only
planner: reconcile documentation with owner-provided production commands, deploy log, and static HEAD evidence; scope limited to README, PLAN, PROJECT_STATE, ARCHITECTURE, CHANGELOG, and workflow evidence; no application, tests, runtime configuration, VERSION, contracts, logging, KPI, schema, DER, merge, or deploy change; bump doc_version patch and last_verified_at to 2026-10-30; validate exact evidence, command, links, headers, staged hooks, and full pytest; risk is confusing historical deployment evidence with current Render settings
implementation: documentation only; application behavior did not change and no new behavior test was created; removed proposed stamp_build command in favor of the owner's pending-decision note; inspected django_render/version.py, VERSION, and test settings before describing behavior
verification_source: owner-provided production evidence reproduced verbatim in PLAN.md, docs/PROJECT_STATE.md, and docs/CHANGELOG.md; no new production request was performed
checkout_provenance: local base b61f9fc5a468ee7433985edd9601bedd36248426; Git fetch failed because the configured proxy was unreachable; GitHub integration confirmed PR #13 head 395953af934ef327fb5e9a5c4216f540ab681a51 and its four documentation-only changed files, fetched at that exact SHA; reconstructed head tree dec66c60545fbcd89cd9fa5ad185d1ba3ec1b34a; validation uses that code plus the documentation edits; publication uses the exact remote head as the sole parent
tests_executed: .venv/bin/python -m pytest -q: 461 passed, 3 PostgreSQL-only skipped, 1 existing DRF UnorderedObjectListWarning, 44 subtests passed (39.27s); DJANGO_SKIP_ENV_FILE=1 .venv/bin/pytest -q also returned 461 passed, 3 skipped, 1 existing DRF warning, 44 subtests passed (39.43s); git diff --check passed; bash .codex/hooks/docs-sync.sh staged passed with 0 warnings; initial pre-commit found the new not_applicable failing_test_proof incompatible with historical behavior evidence in this cumulative file; the field now explicitly states no behavior change without that prefix, retaining all history; final bash .codex/hooks/docs-sync.sh staged and bash .codex/hooks/pre-commit.sh both passed with 0 warnings
pending_issues: unavailable equity fields remain tracked by ccantero/django_render#12; stamp_build pending-decision wording is historical and superseded by the latest entry
tests_created: no new behavior test was created because this is documentation only
failing_test_proof: application behavior did not change; no failing behavior test was created
docs_reviewed: README.md, PLAN.md, docs/PROJECT_STATE.md, docs/ARCHITECTURE.md, docs/DATA_CONTRACT.md, docs/DESIGN.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: README.md 1.1.39 to 1.1.40; PLAN.md 1.1.24 to 1.1.25; docs/PROJECT_STATE.md 1.1.42 to 1.1.43; docs/ARCHITECTURE.md 1.1.24 to 1.1.25; docs/CHANGELOG.md 1.1.55 to 1.1.56; all last_verified_at 2026-10-30; .codex/workflow-evidence.md updated; DESIGN.md has no Build Command and needs no update; DATA_CONTRACT.md and KPI_REGISTRY.md reviewed, no update needed
changelog: updated
schema_der: not_applicable: no schema or DER change
data_contract_sync: not_applicable: reviewed, no shared contract change
logging_observability: reviewed, no runtime logging, healthcheck payload, or operator output change
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available
kpi_registry_notes: reviewed, no update needed; no metric formula, source, status, or output changed
protected_infrastructure: no changes to AGENTS.md or .codex/hooks, .codex/lib, .codex/templates
production_actions: none; no merge, deploy, or runtime configuration change

# Workflow evidence — Telegram portfolio command runtime verification (2026-10-29)

task_mode: DOCUMENTATION
phases_completed: planner, implementer, tester, documentator
impact: docs_only
tests_executed: /tmp/venv/bin/pytest -q returned 461 passed, 3 skipped, 44 subtests passed. No new behavior test was created. bash .codex/hooks/docs-sync.sh staged passed with 0 warnings. bash .codex/hooks/pre-commit.sh passed with 0 warnings.
pending_issues: https://github.com/ccantero/django_render/issues/12 stays open for unavailable equity 7d, equity 30d, and 24h equity drivers. Render command/boot readiness, including collectstatic, remained NEEDS_RUNTIME_VERIFICATION at that time.
tests_created: no new behavior test was created because this task only records an owner-reported documentation fact
failing_test_proof: application behavior did not change, so no failing behavior test was added; the existing suite passed after the documentation edit
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md
docs_updated: PLAN.md 1.1.23 to 1.1.24, docs/PROJECT_STATE.md 1.1.41 to 1.1.42, docs/CHANGELOG.md 1.1.54 to 1.1.55. README.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/DATA_CONTRACT.md, and docs/KPI_REGISTRY.md were reviewed and left unchanged.
changelog: updated
schema_der: not_applicable: no schema or DER change
data_contract_sync: not_applicable: docs/DATA_CONTRACT.md was reviewed and not changed
logging_observability: no runtime logging, healthcheck payload, or operator command output changed
kpi_registry_reviewed: yes
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available
kpi_registry_notes: reviewed, no update needed; no metric formula, source, status, or operator output changed

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
