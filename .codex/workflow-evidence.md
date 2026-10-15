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
