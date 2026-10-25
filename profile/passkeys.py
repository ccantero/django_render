"""Passkey views that delegate WebAuthn verification to django-otp-webauthn."""

import hashlib
import hmac
import json
import secrets
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from django_otp_webauthn import exceptions as webauthn_exceptions
from django_otp_webauthn.helpers import WebAuthnHelper
from django_otp_webauthn.models import WebAuthnCredential
from django_otp_webauthn.views import (
    BaseWebAuthnView,
    BeginCredentialAuthenticationView,
    CompleteCredentialAuthenticationView,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
)

from profile.models import (
    PasskeyEnrollmentChallenge,
    PasskeyEnrollmentProof,
    PasskeyRateLimit,
)


REAUTH_SESSION_KEY = "passkeys.reauthenticated_at"
REGISTRATION_TIME_KEY = "passkeys.registration_started_at"
AUTHENTICATION_TIME_KEY = "passkeys.authentication_started_at"
PENDING_NAME_KEY = "passkeys.pending_name"
REGISTRATION_STATE_KEY = "otp_webauthn_register_state"
AUTHENTICATION_STATE_KEY = "otp_webauthn_authentication_state"
REGISTRATION_OWNER_KEY = "passkeys.registration_owner"
REGISTRATION_BINDING_KEY = "passkeys.registration_binding"
REGISTRATION_STEP_UP_CREDENTIAL_KEY = "passkeys.registration_step_up_credential"
STEP_UP_STATE_KEY = "passkeys.enrollment_step_up_state"
STEP_UP_TIME_KEY = "passkeys.enrollment_step_up_started_at"
STEP_UP_BINDING_KEY = "passkeys.enrollment_step_up_binding"
STEP_UP_GRANT_KEY = "passkeys.enrollment_step_up_grant"
WINDOW = timedelta(minutes=15)
REAUTH_TTL_SECONDS = 5 * 60
RATE_LIMIT_CLEANUP_INTERVAL_SECONDS = 5 * 60
_rate_limit_cleanup_lock = threading.Lock()
_last_rate_limit_cleanup = 0.0


def passkey_context(request):
    return {"passkeys_enabled": settings.PASSKEYS_ENABLED}


def _enabled_or_404():
    if not settings.PASSKEYS_ENABLED:
        raise Http404


def _request_ip(request):
    # REMOTE_ADDR is deliberately used: forwarded client-IP headers are not
    # trusted unless a deployment explicitly establishes that proxy boundary.
    return request.META.get("REMOTE_ADDR", "unknown")


def _fingerprint(scope, identity):
    raw = f"{scope}:{identity}".encode("utf-8", "replace")
    return hmac.new(settings.SECRET_KEY.encode(), raw, hashlib.sha256).hexdigest()


def _consume_rate_limit(scope, identity, limit):
    """Apply a shared database-backed fixed-window limit; fail closed on DB errors."""
    key_hash = _fingerprint(scope, identity)
    now = timezone.now()
    try:
        _maybe_cleanup_rate_limits(now)
        with transaction.atomic():
            row, _ = PasskeyRateLimit.objects.select_for_update().get_or_create(
                key_hash=key_hash,
                defaults={"window_started_at": now, "attempts": 0},
            )
            if now - row.window_started_at >= WINDOW:
                row.window_started_at = now
                row.attempts = 0
            if row.attempts >= limit:
                row.save(update_fields=["window_started_at", "attempts"])
                return False
            row.attempts += 1
            row.save(update_fields=["window_started_at", "attempts"])
        return True
    except DatabaseError:
        # Authentication and enrollment fail closed if the shared limiter is
        # unavailable; the credential verifier also requires this database.
        return False


def _maybe_cleanup_rate_limits(now=None):
    """Prune old limiter keys at most once per process per five minutes."""
    global _last_rate_limit_cleanup
    monotonic_now = time.monotonic()
    if monotonic_now - _last_rate_limit_cleanup < RATE_LIMIT_CLEANUP_INTERVAL_SECONDS:
        return
    with _rate_limit_cleanup_lock:
        monotonic_now = time.monotonic()
        if monotonic_now - _last_rate_limit_cleanup < RATE_LIMIT_CLEANUP_INTERVAL_SECONDS:
            return
        try:
            PasskeyRateLimit.objects.filter(
                window_started_at__lt=(now or timezone.now()) - WINDOW
            ).delete()
            PasskeyEnrollmentProof.objects.filter(
                verified_at__lt=(now or timezone.now()) - WINDOW
            ).delete()
            PasskeyEnrollmentChallenge.objects.filter(
                started_at__lt=(now or timezone.now()) - WINDOW
            ).delete()
        except DatabaseError:
            # Housekeeping is best effort. Enforcement below still fails closed
            # if the limiter table itself cannot be read or updated.
            pass
        _last_rate_limit_cleanup = monotonic_now


def _rate_limited(request, scope, identity, limit):
    if _consume_rate_limit(scope, identity, limit):
        return None
    return JsonResponse(
        {"detail": "Too many attempts. Try again later."}, status=429
    )


def _within_ttl(stamp, ttl=REAUTH_TTL_SECONDS):
    if not isinstance(stamp, (int, float)):
        return False
    age = time.time() - stamp
    return 0 <= age <= ttl


def _session_binding(request):
    return {
        "user_id": str(request.user.pk),
        "session_key": request.session.session_key,
        "auth_hash": request.user.get_session_auth_hash(),
    }


def _session_binding_hash(request):
    serialized = json.dumps(_session_binding(request), sort_keys=True, separators=(",", ":"))
    return _fingerprint("enrollment-session", serialized)


def _proof_token_hash(token):
    if not isinstance(token, str) or not token or len(token) > 128:
        return None
    return _fingerprint("enrollment-proof", token)


def _create_enrollment_proof(request, proof_type, credential_pk=None):
    token = secrets.token_urlsafe(32)
    PasskeyEnrollmentProof.objects.create(
        token_hash=_proof_token_hash(token),
        user=request.user,
        proof_type=proof_type,
        session_binding_hash=_session_binding_hash(request),
        credential_pk=credential_pk,
    )
    return token


def _consume_enrollment_challenge(request, token):
    """Lock and consume step-up state before checking its WebAuthn assertion."""
    token_hash = _fingerprint("enrollment-challenge", token) if isinstance(token, str) else None
    if not token_hash:
        return None
    try:
        with transaction.atomic():
            challenge = PasskeyEnrollmentChallenge.objects.select_for_update().get(
                token_hash=token_hash
            )
            age = timezone.now() - challenge.started_at
            if (
                challenge.user_id != request.user.pk
                or challenge.session_binding_hash != _session_binding_hash(request)
                or challenge.consumed_at is not None
                or not timedelta(0) <= age <= timedelta(
                    seconds=settings.PASSKEY_CHALLENGE_TTL_SECONDS
                )
            ):
                return None
            challenge.consumed_at = timezone.now()
            challenge.save(update_fields=["consumed_at"])
            return challenge.state
    except (PasskeyEnrollmentChallenge.DoesNotExist, DatabaseError):
        return None


def _consume_enrollment_proofs(request, require_passkey):
    """Atomically consume proof records so concurrent begins cannot reuse them."""
    password_token = request.session.get(REAUTH_SESSION_KEY)
    passkey_token = request.session.get(STEP_UP_GRANT_KEY)
    if not password_token or (require_passkey and not passkey_token):
        return False, None
    tokens = {
        PasskeyEnrollmentProof.PASSWORD: password_token,
    }
    if require_passkey:
        tokens[PasskeyEnrollmentProof.PASSKEY] = passkey_token
    hashes = {kind: _proof_token_hash(token) for kind, token in tokens.items()}
    if any(not value for value in hashes.values()):
        return False, None
    try:
        with transaction.atomic():
            proofs = list(
                PasskeyEnrollmentProof.objects.select_for_update()
                .filter(token_hash__in=hashes.values())
                .order_by("pk")
            )
            by_hash = {proof.token_hash: proof for proof in proofs}
            now = timezone.now()
            current_binding_hash = _session_binding_hash(request)
            selected = []
            credential_pk = None
            for proof_type, token_hash in hashes.items():
                proof = by_hash.get(token_hash)
                if not proof:
                    return False, None
                age = now - proof.verified_at
                if (
                    proof.user_id != request.user.pk
                    or proof.proof_type != proof_type
                    or proof.consumed_at is not None
                    or proof.session_binding_hash != current_binding_hash
                    or not timedelta(0) <= age <= timedelta(seconds=REAUTH_TTL_SECONDS)
                ):
                    return False, None
                if proof_type == PasskeyEnrollmentProof.PASSKEY:
                    credential_pk = proof.credential_pk
                    if not credential_pk or not WebAuthnCredential.objects.filter(
                        pk=credential_pk, user_id=request.user.pk
                    ).exists():
                        return False, None
                selected.append(proof)
            for proof in selected:
                proof.consumed_at = now
                proof.save(update_fields=["consumed_at"])
        request.session.pop(REAUTH_SESSION_KEY, None)
        request.session.pop(STEP_UP_GRANT_KEY, None)
        return True, credential_pk
    except DatabaseError:
        return False, None


class StrictWebAuthnHelper(WebAuthnHelper):
    """Use discoverable credentials and require local user verification."""

    def get_generate_registration_options_kwargs(self, *, user):
        kwargs = super().get_generate_registration_options_kwargs(user=user)
        selection = kwargs["authenticator_selection"]
        kwargs["authenticator_selection"] = AuthenticatorSelectionCriteria(
            authenticator_attachment=selection.authenticator_attachment,
            resident_key=selection.resident_key,
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        return kwargs


class PasskeyFeatureView:
    """Shared opt-in and server-side one-time challenge-expiry behavior."""

    def dispatch(self, request, *args, **kwargs):
        _enabled_or_404()
        return super().dispatch(request, *args, **kwargs)

    def _consume_challenge_time(self, time_key, state_key):
        started = self.request.session.pop(time_key, None)
        if not _within_ttl(started, settings.PASSKEY_CHALLENGE_TTL_SECONDS):
            self.request.session.pop(state_key, None)
            self.request.session.pop(PENDING_NAME_KEY, None)
            self.request.session.save()
            raise webauthn_exceptions.InvalidState()


@method_decorator(login_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class RegistrationBeginView(PasskeyFeatureView, BaseWebAuthnView):
    def get_user(self):
        return self.request.user if self.request.user.is_authenticated else None

    def get_helper(self):
        return WebAuthnCredential.get_webauthn_helper(request=self.request)

    def post(self, *args, **kwargs):
        user = self.get_user()
        if not user or not user.is_active:
            return JsonResponse({"detail": "Authentication required."}, status=401)
        if not _consume_rate_limit("register", user.pk, 10):
            return JsonResponse({"detail": "Too many attempts. Try again later."}, status=429)
        if not self.request.session.get(REAUTH_SESSION_KEY):
            return JsonResponse({"detail": "Re-enter your password before adding a passkey."}, status=428)
        name = str(self.request.POST.get("name", "")).strip()
        if not name or len(name) > 80:
            return JsonResponse({"detail": "Enter a passkey name of 1 to 80 characters."}, status=400)
        credentials = WebAuthnCredential.objects.filter(user_id=user.pk)
        require_passkey = credentials.exists()
        if require_passkey and not self.request.session.get(STEP_UP_GRANT_KEY):
            return JsonResponse(
                {"detail": "Verify with an existing passkey before adding another."},
                status=428,
            )
        helper = self.get_helper()
        data, state = helper.register_begin(user=user)
        proof_ok, step_up_credential_id = _consume_enrollment_proofs(
            self.request, require_passkey=require_passkey
        )
        if not proof_ok:
            self.request.session.pop(REAUTH_SESSION_KEY, None)
            if require_passkey:
                self.request.session.pop(STEP_UP_GRANT_KEY, None)
            return JsonResponse({"detail": "Reauthentication expired. Verify again before adding a passkey."}, status=428)
        # Password and passkey proof each authorize only one registration
        # ceremony, and are tied to this exact authenticated session.
        self.request.session[REGISTRATION_STATE_KEY] = state
        self.request.session[REGISTRATION_TIME_KEY] = time.time()
        self.request.session[PENDING_NAME_KEY] = name
        self.request.session[REGISTRATION_OWNER_KEY] = str(user.pk)
        self.request.session[REGISTRATION_BINDING_KEY] = _session_binding(self.request)
        self.request.session[REGISTRATION_STEP_UP_CREDENTIAL_KEY] = step_up_credential_id
        return JsonResponse(data)


@method_decorator(login_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class RegistrationCompleteView(PasskeyFeatureView, BaseWebAuthnView):
    def post(self, *args, **kwargs):
        session = self.request.session
        state = session.pop(REGISTRATION_STATE_KEY, None)
        started = session.pop(REGISTRATION_TIME_KEY, None)
        name = session.pop(PENDING_NAME_KEY, None)
        owner_id = session.pop(REGISTRATION_OWNER_KEY, None)
        binding = session.pop(REGISTRATION_BINDING_KEY, None)
        step_up_credential_id = session.pop(REGISTRATION_STEP_UP_CREDENTIAL_KEY, None)
        session.save()  # consume ceremony before verification, including failures
        if (
            not state
            or not name
            or owner_id != str(self.request.user.pk)
            or binding != _session_binding(self.request)
            or not _within_ttl(started, settings.PASSKEY_CHALLENGE_TTL_SECONDS)
            or not self.request.user.is_active
        ):
            return JsonResponse({"detail": "Passkey registration could not be completed."}, status=400)
        if step_up_credential_id and not WebAuthnCredential.objects.filter(
            pk=step_up_credential_id, user_id=self.request.user.pk
        ).exists():
            return JsonResponse({"detail": "Passkey registration could not be completed."}, status=400)
        try:
            credential = self.get_helper().register_complete(
                user=self.request.user, state=state, data=self.request.data
            )
            credential.name = name
            credential.save(update_fields=["name"])
        except (webauthn_exceptions.OTPWebAuthnApiError, ValidationError, DatabaseError):
            return JsonResponse({"detail": "Passkey registration could not be completed."}, status=400)
        return JsonResponse({"id": str(credential.pk)})

    def handle_exception(self, exc):
        if isinstance(exc, (webauthn_exceptions.OTPWebAuthnApiError, ValidationError, DatabaseError)):
            return JsonResponse({"detail": "Passkey registration could not be completed."}, status=400)
        raise exc

    def get_helper(self):
        return WebAuthnCredential.get_webauthn_helper(request=self.request)


@method_decorator(login_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class EnrollmentStepUpBeginView(PasskeyFeatureView, BaseWebAuthnView):
    def post(self, *args, **kwargs):
        user = self.request.user
        if not user.is_active:
            return JsonResponse({"detail": "Passkey verification could not be completed."}, status=403)
        credentials = WebAuthnCredential.objects.filter(user_id=user.pk)
        if not credentials.exists():
            return JsonResponse({"detail": "Register your first passkey with your password."}, status=400)
        if not _consume_rate_limit("enrollment_step_up", user.pk, 10):
            return JsonResponse({"detail": "Passkey verification could not be completed."}, status=429)
        session = self.request.session
        for key in (STEP_UP_STATE_KEY, STEP_UP_TIME_KEY, STEP_UP_BINDING_KEY, STEP_UP_GRANT_KEY):
            session.pop(key, None)
        options, state = self.get_helper().authenticate_begin(
            user=user, require_user_verification=True
        )
        token = secrets.token_urlsafe(32)
        try:
            PasskeyEnrollmentChallenge.objects.create(
                token_hash=_fingerprint("enrollment-challenge", token),
                user=user,
                session_binding_hash=_session_binding_hash(self.request),
                state=state,
            )
        except DatabaseError:
            return JsonResponse({"detail": "Passkey verification could not be completed."}, status=503)
        session[STEP_UP_STATE_KEY] = token
        return JsonResponse(options)

    def get_helper(self):
        return WebAuthnCredential.get_webauthn_helper(request=self.request)


@method_decorator(login_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class EnrollmentStepUpCompleteView(PasskeyFeatureView, BaseWebAuthnView):
    def post(self, *args, **kwargs):
        session = self.request.session
        token = session.pop(STEP_UP_STATE_KEY, None)
        session.pop(STEP_UP_TIME_KEY, None)
        session.pop(STEP_UP_BINDING_KEY, None)
        session.pop(STEP_UP_GRANT_KEY, None)
        session.save()  # challenges are single-use even on malformed assertions
        state = _consume_enrollment_challenge(self.request, token)
        if (
            not state
            or not self.request.user.is_active
        ):
            return JsonResponse({"detail": "Passkey verification could not be completed."}, status=400)
        if not _consume_rate_limit("enrollment_step_up", self.request.user.pk, 10):
            return JsonResponse({"detail": "Passkey verification could not be completed."}, status=429)
        try:
            credential = self.get_helper().authenticate_complete(
                user=self.request.user,
                state=state,
                data=self.request.data,
            )
            if credential.user_id != self.request.user.pk:
                return JsonResponse({"detail": "Passkey verification could not be completed."}, status=400)
        except (webauthn_exceptions.OTPWebAuthnApiError, ValidationError, DatabaseError):
            return JsonResponse({"detail": "Passkey verification could not be completed."}, status=400)
        try:
            session[STEP_UP_GRANT_KEY] = _create_enrollment_proof(
                self.request, PasskeyEnrollmentProof.PASSKEY, credential_pk=credential.pk
            )
        except DatabaseError:
            return JsonResponse({"detail": "Passkey verification could not be completed."}, status=503)
        return JsonResponse({"ok": True})

    def get_helper(self):
        return WebAuthnCredential.get_webauthn_helper(request=self.request)


@method_decorator(never_cache, name="dispatch")
class AuthenticationBeginView(PasskeyFeatureView, BeginCredentialAuthenticationView):
    def post(self, *args, **kwargs):
        if not _consume_rate_limit("login", _request_ip(self.request), 20):
            return JsonResponse({"detail": "Sign-in could not be completed."}, status=429)
        helper = self.get_helper()
        data, state = helper.authenticate_begin(
            user=self.get_user(), require_user_verification=True
        )
        self.request.session[AUTHENTICATION_STATE_KEY] = state
        self.request.session[AUTHENTICATION_TIME_KEY] = time.time()
        return JsonResponse(data)


@method_decorator(never_cache, name="dispatch")
class AuthenticationCompleteView(PasskeyFeatureView, CompleteCredentialAuthenticationView):
    def get_state(self):
        self._consume_challenge_time(AUTHENTICATION_TIME_KEY, AUTHENTICATION_STATE_KEY)
        return super().get_state()

    def post(self, *args, **kwargs):
        if not _consume_rate_limit("login", _request_ip(self.request), 20):
            return JsonResponse({"detail": "Sign-in could not be completed."}, status=429)
        return super().post(*args, **kwargs)

    def handle_exception(self, exc):
        if isinstance(exc, (webauthn_exceptions.OTPWebAuthnApiError, DatabaseError)):
            return JsonResponse({"detail": "Sign-in could not be completed."}, status=400)
        raise exc


@login_required
@never_cache
def manage(request):
    _enabled_or_404()
    credentials = WebAuthnCredential.objects.filter(user=request.user).order_by("created_at", "pk")
    return render(
        request,
        "profile/passkeys.html",
        {"credentials": credentials, "login_url": settings.LOGIN_URL},
    )


@login_required
@require_POST
def reauthenticate(request):
    _enabled_or_404()
    limited = _rate_limited(request, "reauth", request.user.pk, 5)
    if limited:
        return limited
    password = request.POST.get("password", "")
    if not request.user.check_password(password):
        return JsonResponse({"detail": "Reauthentication failed."}, status=403)
    try:
        request.session[REAUTH_SESSION_KEY] = _create_enrollment_proof(
            request, PasskeyEnrollmentProof.PASSWORD
        )
    except DatabaseError:
        return JsonResponse({"detail": "Reauthentication could not be completed."}, status=503)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def revoke(request, credential_id):
    _enabled_or_404()
    limited = _rate_limited(request, "revoke", request.user.pk, 5)
    if limited:
        return limited
    if not request.user.check_password(request.POST.get("password", "")):
        return JsonResponse({"detail": "Reauthentication failed."}, status=403)
    credential = get_object_or_404(
        WebAuthnCredential, pk=credential_id, user=request.user
    )
    credential.delete()
    return redirect("passkey_manage")
