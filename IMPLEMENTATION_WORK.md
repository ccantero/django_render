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
the package should receive independent review. Runtime dependency security
audit tooling (`pip-audit`) was unavailable in this environment.

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
- `pip-audit` could not run because it is not installed in the execution
  environment (`python -m pip_audit` reports no module). `pip check` only
  validates package compatibility and is not a vulnerability audit. Full
  dependency/advisory review remains a deployment gate.

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

- Confirm package maintenance/security posture and transitive dependency audit.
- Confirm deployment proxy overwrites `X-Forwarded-Proto` and application
  workers are not directly reachable before relying on proxy SSL detection.
- Confirm the exact production origin/RP ID and browser support matrix.
- Review whether password reauthentication for revocation and the additional
  passkey verification for second-key enrollment meet operator policy.
- Confirm row-lock behavior and transactional guarantees on the deployed
  PostgreSQL configuration; SQLite's `select_for_update()` is a no-op and
  cannot prove production concurrency behavior.
- Run a vulnerability audit against the complete locked/transitive dependency
  graph before deployment; `pip-audit` was unavailable in this environment.
- Confirm the recovery procedure for a user who loses every passkey and cannot
  use the existing password through the operator's established process.
