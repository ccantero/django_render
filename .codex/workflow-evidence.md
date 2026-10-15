# Workflow evidence — Secure Passkeys

task_mode: STANDARD
phases_completed: planner, implementer, tester, documentator
planner_artifacts_read: AGENTS.md, README.md, PLAN.md, docs/ARCHITECTURE.md, docs/DESIGN.md, docs/PROJECT_STATE.md, docs/DATA_CONTRACT.md, docs/CHANGELOG.md, .codex/skills/planning.md, .codex/skills/tdd.md, .codex/skills/documentation.md
baseline: `.venv/bin/pytest -q` — 328 passed, 33 subtests.
tdd_red: Focused entry-point tests ran before implementation: 3 expected failures and 1 pass; login/settings/management routes were missing.
implementation: Optional WebAuthn via django-otp-webauthn; preserve profile.UserProfile, browser password auth, Admin checks, DRF token auth, public currency PWA, and bot data contract.
tests_executed: `.venv/bin/pytest -q` — 353 passed, 1 warning, 33 subtests passed in 32.53s; `manage.py check` — no issues; `manage.py makemigrations --check --dry-run` — no changes; Python compileall passed; `node --check static/profile/passkeys.js` passed; `git diff --check` passed.
warning: DRF pagination emits UnorderedObjectListWarning for an unordered UserProfile queryset in the token-auth regression test.
security_review: Feature disabled by default; production exact HTTPS origin/RP validation; user verification; session-bound one-time challenges; library replay/state handling; 5-minute TTL; password and existing-passkey reauthentication; CSRF; DB-backed HMAC rate limits; scoped revoke; generic errors; inactive-user gate; Admin keeps Django checks.
dependency_audit: `pip-audit` unavailable in environment; package maturity and transitive dependency review documented in IMPLEMENTATION_WORK.md.
manual_checks: Real Safari/iOS, desktop, Windows Hello, and hardware key verification not available in Work Cloud. Reverse-proxy header trust boundary requires deployment verification.
production_actions: none; no production migrations, credentials, deployment, or external state touched.
