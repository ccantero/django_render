# Secure Passkeys Implementation Work

Date: 2026-10-15  
Branch: `feat/secure-passkey-auth-20261015`  
Status: review blockers addressed in the existing PR branch; regression suite passed.

## 1. Architecture before and after

Before: `profile.UserProfile` is the configured custom email-based user model.
Browser login is Django password authentication using `ModelBackend`,
`AuthenticationMiddleware`, and ordinary sessions. `/admin/` uses Django's
admin authentication and staff/superuser checks. `/api/login/` uses DRF's
`ObtainAuthToken`; profile API routes retain DRF token authentication. No
alternate browser token-login route was found.

After: `django-otp-webauthn` stores one or more passkey credentials and
WebAuthn user handles related to the existing user. Its WebAuthn helper and
`py_webauthn` perform protocol verification. The existing login page has a
progressive-enhancement passkey option; successful verification creates an
ordinary Django session and rotates it. Authenticated users manage credentials
at `/security/passkeys/`. Password login, custom user model, APIs, and Admin
authorization stay in place. Allauth/social login and the authenticated PWA
were not added.

Additional credential enrollment now has a dedicated authenticated step-up
ceremony. It verifies a credential from the current user using
`authenticate_complete(user=request.user, ...)`, never calls Django `login()`
or OTP login, and does not change the identity or session key. Short-lived
proof records are HMAC-keyed and bound to the user, auth hash, and session.
Registration begin consumes password and, where a passkey already exists,
passkey proof rows together under database row locks. A separate challenge
row makes the step-up WebAuthn challenge one-use even when concurrent requests
reuse a stale session snapshot. First-passkey bootstrap remains password-only.

## 2. Library selection and alternatives

Selected `django-otp-webauthn>=0.10.3,<0.11`, with Django OTP and
`py_webauthn`. It supports Django 5.2/Python 3.12, Django session integration,
credential foreign keys, multiple credentials, named credentials, last-use
metadata, authentication and revocation, and explicit RP ID/origin settings.
The helper owns challenge generation and cryptographic assertion/attestation
verification. The project's custom helper only requires discoverable
credentials and user verification.

`django-allauth[mfa]` was evaluated; it offers broader account/MFA workflows
and would add an account integration surface not needed here. `django-passkeys`
was evaluated but offers less confidence in maintenance continuity for this
project. The selected package is also relatively young; no claim of a formal
third-party security audit is made. Its dependency risk must be monitored and
the package should receive independent review. The initial implementation
environment lacked `pip-audit`; section 11 records the follow-up audit results.

## 3. Exact files changed

- `requirements.txt`
- `django_render/settings.py`, `django_render/urls.py`
- `core/urls.py`, `core/templates/base.html`, `core/templates/login.html`
- `profile/models.py`, `profile/passkeys.py`
- `profile/migrations/0002_passkey_rate_limit.py`,
  `profile/migrations/0003_passkey_rate_limit_window_index.py`,
  `profile/migrations/0004_passkeyenrollmentproof.py`,
  `profile/migrations/0005_passkeyenrollmentchallenge.py`
- `profile/templates/profile/passkeys.html`
- `templates/admin/passkey_login.html`
- `static/profile/passkeys.js`
- `tests/test_passkey_auth.py`
- `README.md`, `PLAN.md`, `docs/ARCHITECTURE.md`, `docs/DESIGN.md`,
  `docs/PROJECT_STATE.md`, `docs/CHANGELOG.md`
- `IMPLEMENTATION_WORK.md`

## 4. User/account preservation evidence

`AUTH_USER_MODEL` remains `profile.UserProfile`; migration `0001_initial` and
all existing user rows are untouched. The new profile migrations create only
Django-owned rate-limit, expiring enrollment-proof, and step-up challenge
tables/indexes. The selected library's migrations add credential and
user-handle tables related to the existing user model. No migration
rewrites users, passwords, group/permission links, or bot-owned tables.
`test_existing_identity_and_permissions_are_preserved` verifies user primary
key, email, password hash, staff/superuser state, group membership and
permissions across credential operations. The test suite also confirms DRF
token authentication continues to work.

## 5. Django Admin integration

Admin remains Django's `AdminSite` with its native password login form and
normal staff/superuser authorization checks. The customized login template
adds a link to the dashboard's passkey login. A passkey creates a normal Django
session, then Admin makes its ordinary staff authorization decision. Tests
verify an authorized superuser can reach Admin after passkey authentication
and a nonstaff account cannot. Password login remains the tested recovery
path. No claim is made that `/admin/` itself performs a WebAuthn ceremony.

## 6. Security controls

- Feature defaults off; production enablement requires explicit RP ID and
  exact HTTPS origins, validated against one another.
- WebAuthn user verification is required. Challenges are session-bound,
  consumed once by the library, and expire after at most five minutes.
- Registration and revocation require current password; further enrollment
  also verifies a previously registered passkey. The dedicated step-up
  endpoints are authenticated and CSRF-protected and never call the login
  backend or rotate the authenticated user's identity.
- Password and passkey proofs are HMAC-tokenized, tied to the current user's
  session key/auth hash, expire after five minutes, and are atomically consumed
  under row locks. Step-up challenge state is server-side and atomically
  consumed before assertion verification; a stale session snapshot cannot
  replay it.
- Registration enforces name bounds and credential uniqueness via the library;
  credentials are scoped to the current user for management and revocation.
- Authentication checks origin/RP hash/credential ownership via the chosen
  verifier, rejects inactive users, rotates sessions, and uses generic errors.
- DB-backed HMAC-keyed fixed-window rate limits cover login, registration,
  reauthentication, step-up, and revocation. Updates use `select_for_update`
  inside transactions; database failures fail closed. Expired-row cleanup is
  throttled to once per process every five minutes, with cleanup errors treated
  as best-effort maintenance failures.
- Error logging from the WebAuthn package is disabled; challenge/assertion data
  and credential material are not logged or returned by management pages.
- Existing secure session/CSRF cookies and HTTPS redirect remain. Production
  proxy configuration trusts `X-Forwarded-Proto`; deployment must verify that
  the trusted proxy overwrites that header and the application server is not
  directly reachable.
- No browser service worker/PWA scope, bot accounting model, trading logic,
  external identity service, or production state was changed.

## 7. Tests and results

- Baseline before implementation: `pytest -q` — 328 passed, 33 subtests.
- Initial focused entry-point tests failed before route/template implementation
  (three expected failures, one pass), confirming the test detected missing
  behavior before implementation.
- New focused passkey suite after review fixes: **38 passed, 1 warning**.
- Final full suite: `.venv/bin/pytest -q` — **366 passed, 1 warning, 33
  subtests passed in 64.60s**. Warning: DRF pagination on an unordered
  `UserProfile` queryset in the token-auth regression test.
- `manage.py check` — no issues.
- `manage.py makemigrations --check --dry-run` — no changes detected.
- `python -m compileall -q core django_render profile tests` — passed.
- `node --check static/profile/passkeys.js` — passed.
- `git diff --check` — passed.
- `.venv/bin/python -m pip check` — no broken requirements found.
- Package-level tests use a fake ceremony helper to test application flow;
  these do not prove browser/hardware interoperability. Direct verifier tests
  exercise the selected library's rejection of wrong origin/RP hash.
- The earlier passkey implementation run did not have `pip-audit`; see
  section 11 for the subsequent successful audit and the exact pip tooling
  advisory findings.

## 8. Migration and deployment risks

No production migrations were run. Deploy profile migrations `0002` through
`0005` and the `django-otp-webauthn` app migrations through the normal release
process with a database backup and staging verification. The new rate-limit,
proof, and challenge tables are Django-owned; the library migrations are also
Django models and reference `profile.UserProfile`. Apply them before enabling
the feature. Set `PASSKEY_RP_ID`, `PASSKEY_ALLOWED_ORIGINS`, and then
`PASSKEYS_ENABLED=true`; origins must match the actual browser-facing HTTPS
site. Verify trusted forwarded-proto handling, secure cookies, and cross-worker
session persistence. To roll back, turn the feature flag off and redeploy;
retain schema and credential rows. Existing passwords, accounts, tokens,
permissions, and sessions are not removed.
This repository does not currently contain a `docs/db/` DER/schema artifact;
the generated Django migrations and architecture documentation are the schema
record for these Django-owned tables. `docs/DATA_CONTRACT.md` was reviewed and
left unchanged because no bot-owned/shared table semantics changed.

## 9. Manual verification checklist

Requires deployment verification with real browsers/authenticators; not run in
Work Cloud.

- Safari on iOS: password login remains present; register a Face ID/iCloud
  passkey, sign out, sign in, verify normal dashboard session, add a second key,
  revoke one, and retry the revoked key.
- Desktop Safari/macOS: verify Touch ID and platform credential discovery.
- Chrome/Edge/Firefox desktop: verify Windows Hello and a hardware security key
  where available; test cancellation and browser-without-WebAuthn fallback.
- Verify wrong-origin requests, expired challenges, repeated assertions,
  replayed step-up challenge, cross-account credentials, expired/replayed
  proof grants, inactive accounts, and rate limits fail safely.
- Verify password and DRF token login, staff Admin access, nonstaff Admin
  denial, logout invalidation, CSRF rejection, and safe `next` redirects.
- Confirm production HTTPS, RP ID/origin configuration, reverse-proxy header
  sanitization, secure cookie attributes, and no credential/challenge values
  in logs.

## 10. Open questions for reviewer

- Confirm package maintenance/security posture and re-run dependency auditing
  against the exact deployment-resolved dependency graph; this repository has
  no lockfile.
- Confirm deployment proxy overwrites `X-Forwarded-Proto` and application
  workers are not directly reachable before relying on proxy SSL detection.
- Confirm the exact production origin/RP ID and browser support matrix.
- Review whether password reauthentication for revocation and the additional
  passkey verification for second-key enrollment meet operator policy.
- Confirm row-lock behavior and transactional guarantees on the deployed
  PostgreSQL configuration; SQLite's `select_for_update()` is a no-op and
  cannot prove production concurrency behavior.
- Re-run a vulnerability audit against the complete deployment-resolved
  dependency graph before deployment; this environment audit is recorded in
  section 11, but no lockfile pins the deployment resolution.
- Confirm the recovery procedure for a user who loses every passkey and cannot
  use the existing password through the operator's established process.

## 11. Pre-merge isolated validation follow-up

Date: 2026-10-15. This follow-up used only local validation resources and did
not access production credentials, databases, or services.

### Dependency audit

- `.venv/bin/pip-audit -r requirements.txt --desc`: no known vulnerabilities
  in the dependency requirements resolved by pip-audit.
- `.venv/bin/pip-audit --local --desc`: no known vulnerabilities after the
  isolated environment's pip was upgraded from 25.0.1 to 26.2.1. Before that
  upgrade, the scanner reported 12 advisory records affecting only pip 25.0.1
  (six distinct PYSEC IDs, with duplicate advisory records for overlapping
  fix versions): PYSEC-2026-1795 (fix 25.3), PYSEC-2026-1796 (26.0),
  PYSEC-2026-196 (26.1.2), PYSEC-2026-2875 (26.1), PYSEC-2026-2876 (26.1),
  and PYSEC-2026-3721 (26.2.0). The environment-only tool was upgraded; pip is
  not a runtime requirement in `requirements.txt`. Re-run the audit against
  the exact deployment lock/resolution before rollout because this repository
  does not pin a lockfile.

### PostgreSQL attempt and concurrency coverage

The container had no PostgreSQL server or Docker. PostgreSQL 16 packages were
downloaded, but Work Cloud blocked the package post-install service-account
setup (`setgroups`/`setuid` are unavailable), `runuser` cannot switch users,
and `initdb` explicitly rejected execution as root. No shared/remote database
was substituted. Therefore fresh PostgreSQL migrations, full-suite PostgreSQL
execution, and actual PostgreSQL row-lock/concurrency outcomes remain
unverified and are merge/deployment review gates.

Added `tests/test_passkey_postgres_concurrency.py`, containing three threaded,
barrier-synchronized tests for concurrent proof consumption, challenge
consumption, and fixed-window rate limits. They are explicitly skipped unless
the configured backend reports PostgreSQL; SQLite cannot establish row-lock
behavior. `django_render/postgres_test_settings.py` accepts only a loopback
PostgreSQL URL, the `passkey_test` role, and a database named with the `test_`
prefix, preventing accidental use of production or remote databases.

### Checks completed here

- `manage.py check --deploy` with representative production settings and a
  strong disposable key: no issues. Repeating against base commit
  `82e32fd04d525e5e13dd098fd3194d3f4968e33c` also reported no issues; no
  existing or PR-introduced deploy warnings were observed.
- All migrations applied from scratch to a disposable SQLite database,
  including `profile.0004` and `profile.0005`; `makemigrations --check` found
  no model/migration drift. This does not substitute for the requested
  PostgreSQL migration run.
- Full suite uses the default SQLite test database and remains separately
  reported below. PostgreSQL concurrency tests were not run against PostgreSQL.

### Reproducible local HTTPS test with iPhone Safari

This procedure uses a disposable local PostgreSQL database and a private
development certificate. It does not use production credentials or data.

1. Install PostgreSQL and create a dedicated local-only role/database (never
   copy a production connection URL):

   ```sh
   sudo -u postgres psql -c "CREATE ROLE passkey_test LOGIN CREATEDB PASSWORD 'local-only-change-me';"
   sudo -u postgres createdb -O passkey_test test_django_render_passkeys
   export PASSKEY_TEST_DATABASE_URL='postgresql://passkey_test:local-only-change-me@127.0.0.1:5432/test_django_render_passkeys'
   ```

2. Install `mkcert` on the development computer, run `mkcert -install`, and
   configure the local router/DNS to resolve `passkeys.test` to that
   computer's LAN address. Generate a development-only certificate:

   ```sh
   mkcert -cert-file /tmp/passkeys.test.pem -key-file /tmp/passkeys.test-key.pem passkeys.test
   ```

   Install only the generated `rootCA.pem` from `mkcert -CAROOT` on the iPhone;
   never copy `rootCA-key.pem`. On iOS, install the downloaded certificate
   profile, then enable full trust under Settings → General → About →
   Certificate Trust Settings.

3. Configure and migrate only the disposable database, then create a local
   test account:

   ```sh
   export DJANGO_SETTINGS_MODULE=django_render.postgres_test_settings
   export PASSKEY_TEST_HOST=passkeys.test
   export PASSKEYS_ENABLED=true
   export PASSKEY_RP_ID=passkeys.test
   export PASSKEY_ALLOWED_ORIGINS=https://passkeys.test
   export CC_DEBUG=true
   export SECRET_KEY='replace-with-a-long-random-development-only-key'
   export TUTORIAL_BOT_TOKEN=local-placeholder
   export TELEGRAM_WEBHOOK_TOKEN=local-placeholder
   python manage.py migrate --noinput
   python manage.py createsuperuser
   ```

   For Django tests, use `pytest --ds=django_render.postgres_test_settings
   --migrations tests/test_passkey_postgres_concurrency.py` and then the full
   suite with `pytest --ds=django_render.postgres_test_settings --migrations`.
   The test settings reject non-loopback hosts and database names without the
   `test_` prefix.

4. Run the dashboard on loopback and terminate HTTPS at a local reverse proxy
   such as Caddy. Save this local-only `/tmp/Caddyfile`:

   ```caddyfile
   https://passkeys.test {
       tls /tmp/passkeys.test.pem /tmp/passkeys.test-key.pem
       reverse_proxy 127.0.0.1:8000
   }
   ```

   Start Django with `python manage.py runserver 127.0.0.1:8000` and Caddy
   with `caddy run --config /tmp/Caddyfile`. Caddy must forward
   `X-Forwarded-Proto: https`. From Safari on the iPhone, navigate to
   `https://passkeys.test/login/` while on the same network.

5. Verify password fallback, first passkey enrollment, sign-out and passkey
   login, second passkey enrollment using password plus the existing key,
   revocation, revoked-key rejection, and cancellation/failure handling. Also
   verify the secure session cookie and safe redirect behavior. Delete the
   disposable database and development certificate after testing.

The local proxy/DNS setup is not evidence that the production proxy overwrites
forwarded headers or isolates app workers. Safari/iPhone authenticator
interoperability and the production proxy boundary still require actual
deployment-side verification before enabling Passkeys.
