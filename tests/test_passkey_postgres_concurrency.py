"""Real row-lock concurrency regression tests; run against PostgreSQL only."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TransactionTestCase
from django.utils import timezone
from django_otp_webauthn.models import WebAuthnCredential

from profile.models import (
    PasskeyEnrollmentChallenge,
    PasskeyEnrollmentProof,
    PasskeyRateLimit,
)
from profile.passkeys import (
    STEP_UP_GRANT_KEY,
    _consume_enrollment_challenge,
    _consume_enrollment_proofs,
    _consume_rate_limit,
    _fingerprint,
    _session_binding_hash,
)


class ConcurrencySession(dict):
    def __init__(self, *args, session_key, **kwargs):
        super().__init__(*args, **kwargs)
        self.session_key = session_key


def request_for(user, session_key, values=None):
    return SimpleNamespace(user=user, session=ConcurrencySession(values or {}, session_key=session_key))


@skipUnless(connection.vendor == "postgresql", "requires PostgreSQL row-level locking")
class PasskeyPostgreSQLConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="postgres-lock-test@example.com",
            password="Test-password-123",
            name="Postgres lock test",
        )

    def _concurrent(self, requests, operation):
        barrier = Barrier(len(requests))

        def invoke(request):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation(request)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            return list(pool.map(invoke, requests))

    def test_only_one_simultaneous_consumer_can_consume_enrollment_proofs(self):
        credential = WebAuthnCredential.objects.create(
            user=self.user,
            name="Existing device",
            credential_id=b"postgres-concurrency-credential",
            public_key=b"test-public-key",
            aaguid="00000000-0000-0000-0000-000000000000",
            credential_id_sha256="c" * 64,
            discoverable=True,
        )
        session_key = "proof-session-key"
        password_token, passkey_token = "password-token", "passkey-token"
        values = {
            "passkeys.reauthenticated_at": password_token,
            STEP_UP_GRANT_KEY: passkey_token,
        }
        template_request = request_for(self.user, session_key, values)
        binding = _session_binding_hash(template_request)
        now = timezone.now()
        for proof_type, token, credential_pk in (
            (PasskeyEnrollmentProof.PASSWORD, password_token, None),
            (PasskeyEnrollmentProof.PASSKEY, passkey_token, credential.pk),
        ):
            PasskeyEnrollmentProof.objects.create(
                token_hash=_fingerprint("enrollment-proof", token),
                user=self.user,
                proof_type=proof_type,
                session_binding_hash=binding,
                credential_pk=credential_pk,
                verified_at=now,
            )
        requests = [request_for(self.user, session_key, values.copy()) for _ in range(2)]

        results = self._concurrent(
            requests, lambda request: _consume_enrollment_proofs(request, require_passkey=True)
        )

        self.assertEqual(sum(success for success, _ in results), 1)
        self.assertEqual(
            PasskeyEnrollmentProof.objects.filter(consumed_at__isnull=False).count(), 2
        )

    def test_only_one_simultaneous_consumer_can_consume_step_up_challenge(self):
        session_key = "challenge-session-key"
        token = "challenge-token"
        template_request = request_for(self.user, session_key)
        challenge = PasskeyEnrollmentChallenge.objects.create(
            token_hash=_fingerprint("enrollment-challenge", token),
            user=self.user,
            session_binding_hash=_session_binding_hash(template_request),
            state={"challenge": "random-state"},
        )
        requests = [request_for(self.user, session_key) for _ in range(2)]

        results = self._concurrent(
            requests, lambda request: _consume_enrollment_challenge(request, token)
        )

        self.assertEqual(sum(result is not None for result in results), 1)
        challenge.refresh_from_db()
        self.assertIsNotNone(challenge.consumed_at)

    def test_concurrent_rate_limit_requests_do_not_lose_attempts(self):
        limit, attempts = 4, 12
        key = "postgres-concurrent-rate-limit"
        requests = [None] * attempts

        results = self._concurrent(
            requests,
            lambda _request: _consume_rate_limit("concurrency-test", key, limit),
        )

        self.assertEqual(sum(results), limit)
        row = PasskeyRateLimit.objects.get(
            key_hash=_fingerprint("concurrency-test", key)
        )
        self.assertEqual(row.attempts, limit)
