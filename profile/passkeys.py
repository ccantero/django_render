"""Passkey views that delegate WebAuthn verification to django-otp-webauthn."""

import hashlib
import hmac
import json
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
    BeginCredentialAuthenticationView,
    BeginCredentialRegistrationView,
    CompleteCredentialAuthenticationView,
    CompleteCredentialRegistrationView,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
)

from profile.models import PasskeyRateLimit


REAUTH_SESSION_KEY = "passkeys.reauthenticated_at"
REGISTRATION_TIME_KEY = "passkeys.registration_started_at"
AUTHENTICATION_TIME_KEY = "passkeys.authentication_started_at"
PENDING_NAME_KEY = "passkeys.pending_name"
REGISTRATION_STATE_KEY = "otp_webauthn_register_state"
AUTHENTICATION_STATE_KEY = "otp_webauthn_authentication_state"
WINDOW = timedelta(minutes=15)
REAUTH_TTL_SECONDS = 5 * 60


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
        # Bound storage when source IPs rotate. The indexed cleanup is cheap at
        # the dashboard's request volume and keeps only current windows.
        PasskeyRateLimit.objects.filter(window_started_at__lt=now - WINDOW).delete()
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


def _rate_limited(request, scope, identity, limit):
    if _consume_rate_limit(scope, identity, limit):
        return None
    return JsonResponse(
        {"detail": "Too many attempts. Try again later."}, status=429
    )


def _reauthenticated_recently(request):
    stamp = request.session.get(REAUTH_SESSION_KEY)
    if not isinstance(stamp, (int, float)):
        return False
    if time.time() - stamp > REAUTH_TTL_SECONDS:
        request.session.pop(REAUTH_SESSION_KEY, None)
        return False
    return True


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
        expired = (
            not isinstance(started, (int, float))
            or time.time() - started > settings.PASSKEY_CHALLENGE_TTL_SECONDS
        )
        if expired:
            self.request.session.pop(state_key, None)
            self.request.session.pop(PENDING_NAME_KEY, None)
            self.request.session.save()
            raise webauthn_exceptions.InvalidState()


@method_decorator(never_cache, name="dispatch")
class RegistrationBeginView(PasskeyFeatureView, BeginCredentialRegistrationView):
    def post(self, *args, **kwargs):
        user = self.get_user()
        if not user:
            return JsonResponse({"detail": "Authentication required."}, status=401)
        if not _consume_rate_limit("register", user.pk, 10):
            return JsonResponse({"detail": "Too many attempts. Try again later."}, status=429)
        if not _reauthenticated_recently(self.request):
            return JsonResponse({"detail": "Re-enter your password before adding a passkey."}, status=428)
        name = str(self.request.POST.get("name", "")).strip()
        if not name or len(name) > 80:
            return JsonResponse({"detail": "Enter a passkey name of 1 to 80 characters."}, status=400)
        self.request.session.pop(REAUTH_SESSION_KEY, None)
        response = super().post(*args, **kwargs)
        if response.status_code == 200:
            self.request.session[REGISTRATION_TIME_KEY] = time.time()
            self.request.session[PENDING_NAME_KEY] = name
        return response


@method_decorator(never_cache, name="dispatch")
class RegistrationCompleteView(PasskeyFeatureView, CompleteCredentialRegistrationView):
    def get_state(self):
        self._consume_challenge_time(REGISTRATION_TIME_KEY, REGISTRATION_STATE_KEY)
        return super().get_state()

    def post(self, *args, **kwargs):
        response = super().post(*args, **kwargs)
        if response.status_code == 200:
            try:
                credential_id = json.loads(response.content).get("id")
                name = self.request.session.pop(PENDING_NAME_KEY, None)
                if credential_id and name:
                    WebAuthnCredential.objects.filter(
                        pk=credential_id, user=self.request.user
                    ).update(name=name)
            except (TypeError, ValueError):
                return JsonResponse({"detail": "Passkey registration failed."}, status=400)
        return response

    def handle_exception(self, exc):
        if isinstance(exc, (webauthn_exceptions.OTPWebAuthnApiError, ValidationError, DatabaseError)):
            return JsonResponse({"detail": "Passkey registration could not be completed."}, status=400)
        raise exc


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
    request.session[REAUTH_SESSION_KEY] = time.time()
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
