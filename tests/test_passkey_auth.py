import hashlib
import json
import time
import hashlib as hashlib_module
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django_otp_webauthn.models import WebAuthnCredential
from django_otp_webauthn.helpers import WebAuthnHelper
from webauthn.helpers.exceptions import InvalidAuthenticationResponse
from webauthn.helpers import bytes_to_base64url
from rest_framework.authtoken.models import Token


def make_credential(user, credential_id, name="Device"):
    return WebAuthnCredential.objects.create(
        user=user,
        name=name,
        credential_id=credential_id.encode(),
        public_key=b"test-public-key",
        aaguid="00000000-0000-0000-0000-000000000000",
        credential_id_sha256=hashlib.sha256(credential_id.encode()).hexdigest(),
        discoverable=True,
    )


class FakeWebAuthnHelper:
    """Application-flow test double; it does not validate WebAuthn signatures."""

    credential = None

    def register_begin(self, user):
        return ({"challenge": "dGVzdC1jaGFsbGVuZ2U", "user": {"id": "dXNlcg"}}, {"challenge": "dGVzdC1jaGFsbGVuZ2U"})

    def register_complete(self, user, state, data):
        self.credential = make_credential(user, f"credential-{WebAuthnCredential.objects.count() + 1}")
        return self.credential

    def authenticate_begin(self, user=None, require_user_verification=True):
        return ({"challenge": "dGVzdC1jaGFsbGVuZ2U", "rpId": "localhost", "userVerification": "required"}, {"challenge": "dGVzdC1jaGFsbGVuZ2U"})

    def authenticate_complete(self, user, state, data):
        credential = WebAuthnCredential.objects.get(credential_id=data["id"].encode())
        if user and credential.user_id != user.pk:
            from django_otp_webauthn.exceptions import CredentialUserMismatch
            raise CredentialUserMismatch()
        return credential


class PasskeyEntryPointTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="operator@example.com",
            password="A-strong-test-password-123",
            name="Operator",
            is_staff=True,
        )

    @override_settings(PASSKEYS_ENABLED=True)
    def test_existing_login_page_offers_passkey_sign_in(self):
        response = self.client.get(reverse("login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in with a passkey")

    @override_settings(PASSKEYS_ENABLED=True)
    def test_credential_management_requires_a_login(self):
        response = self.client.get(reverse("passkey_manage"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('passkey_manage')}",
            fetch_redirect_response=False,
        )

    @override_settings(PASSKEYS_ENABLED=True)
    def test_existing_user_can_open_credential_management(self):
        original = (self.user.pk, self.user.email, self.user.password,
                    self.user.is_staff, self.user.is_superuser,
                    list(self.user.groups.values_list("pk", flat=True)),
                    list(self.user.user_permissions.values_list("pk", flat=True)))
        self.client.force_login(self.user)

        response = self.client.get(reverse("passkey_manage"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passkeys")
        self.user.refresh_from_db()
        self.assertEqual(
            (self.user.pk, self.user.email, self.user.password,
             self.user.is_staff, self.user.is_superuser,
             list(self.user.groups.values_list("pk", flat=True)),
             list(self.user.user_permissions.values_list("pk", flat=True))),
            original,
        )

    def test_passkey_login_entry_is_unavailable_when_feature_is_disabled(self):
        response = self.client.get("/passkeys/authentication/begin/")

        self.assertEqual(response.status_code, 404)


@override_settings(PASSKEYS_ENABLED=True)
class PasskeyFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            email="operator@example.com",
            password="A-strong-test-password-123",
            name="Operator",
            is_staff=True,
        )
        self.helper = FakeWebAuthnHelper()
        self.helper_patch = patch.object(WebAuthnCredential, "get_webauthn_helper", return_value=self.helper)
        self.helper_patch.start()
        self.addCleanup(self.helper_patch.stop)

    def register(self, name):
        if not self.client.session.get("_auth_user_id"):
            self.client.force_login(self.user)
        reauth = self.client.post(reverse("passkey_reauthenticate"), {"password": "A-strong-test-password-123"})
        self.assertEqual(reauth.status_code, 200)
        begin = self.client.post(reverse("passkey_registration_begin"), {"name": name})
        self.assertEqual(begin.status_code, 200)
        complete = self.client.post(
            reverse("passkey_registration_complete"),
            data=json.dumps({"type": "public-key"}),
            content_type="application/json",
        )
        return complete

    def test_successful_registration_preserves_existing_identity(self):
        self.user.groups.create(name="operators")
        self.user.refresh_from_db()
        identity_before = (
            self.user.pk, self.user.email, self.user.password, self.user.is_staff,
            self.user.is_superuser,
            tuple(self.user.groups.values_list("pk", flat=True)),
            tuple(self.user.user_permissions.values_list("pk", flat=True)),
        )

        response = self.register("Work laptop")

        self.assertEqual(response.status_code, 200)
        credential = WebAuthnCredential.objects.get(user=self.user)
        self.assertEqual(credential.name, "Work laptop")
        self.user.refresh_from_db()
        self.assertEqual(
            (self.user.pk, self.user.email, self.user.password, self.user.is_staff,
             self.user.is_superuser,
             tuple(self.user.groups.values_list("pk", flat=True)),
             tuple(self.user.user_permissions.values_list("pk", flat=True))),
            identity_before,
        )

    def test_multiple_credentials_belong_to_the_same_existing_user(self):
        self.assertEqual(self.register("Phone").status_code, 200)
        self.assertEqual(self.register("Security key").status_code, 200)

        self.assertEqual(
            list(WebAuthnCredential.objects.filter(user=self.user).values_list("name", flat=True)),
            ["Phone", "Security key"],
        )

    def test_enrollment_requires_recent_password_reauthentication(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("passkey_registration_begin"), {"name": "Old session"})

        self.assertEqual(response.status_code, 428)
        self.assertEqual(WebAuthnCredential.objects.count(), 0)

    def test_revocation_requires_password_and_is_scoped_to_current_user(self):
        credential = make_credential(self.user, "owned-credential")
        other = get_user_model().objects.create_user(email="other@example.com", password="OtherPassword123", name="Other")
        self.client.force_login(other)

        response = self.client.post(reverse("passkey_revoke", args=[credential.pk]), {"password": "OtherPassword123"})

        self.assertEqual(response.status_code, 404)
        self.assertTrue(WebAuthnCredential.objects.filter(pk=credential.pk, user=self.user).exists())

    def test_revoked_credential_is_no_longer_usable_by_the_backend(self):
        credential = make_credential(self.user, "revoked-credential")
        credential.delete()

        with self.assertRaises(WebAuthnCredential.DoesNotExist):
            WebAuthnCredential.get_by_credential_id(b"revoked-credential")

    def test_authenticated_user_cannot_attach_another_users_credential(self):
        other = get_user_model().objects.create_user(email="other@example.com", password="OtherPassword123", name="Other")
        self.helper.credential = make_credential(other, "other-credential")
        self.client.force_login(self.user)
        self.client.post(reverse("passkey_authentication_begin"), data="{}", content_type="application/json")

        response = self.client.post(
            reverse("passkey_authentication_complete"),
            data=json.dumps({"id": "other-credential", "type": "public-key"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.session.get("_auth_user_id"), str(self.user.pk))

    def test_credential_can_be_revoked_with_password_reauthentication(self):
        credential = make_credential(self.user, "to-revoke")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("passkey_revoke", args=[credential.pk]),
            {"password": "A-strong-test-password-123"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(WebAuthnCredential.objects.filter(pk=credential.pk).exists())

    def test_password_login_regression(self):
        response = self.client.post(reverse("login"), {
            "username": self.user.email,
            "password": "A-strong-test-password-123",
            "next": reverse("dashboard"),
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("dashboard"))

    def test_passkey_login_creates_normal_staff_session_for_admin(self):
        self.helper.credential = make_credential(self.user, "admin-credential")
        begin = self.client.post(reverse("passkey_authentication_begin"), data="{}", content_type="application/json")
        self.assertEqual(begin.status_code, 200)
        original_session_key = self.client.session.session_key
        complete = self.client.post(
            reverse("passkey_authentication_complete") + "?next=/admin/",
            data=json.dumps({"id": "admin-credential", "type": "public-key"}),
            content_type="application/json",
        )

        self.assertEqual(complete.status_code, 200)
        self.assertEqual(json.loads(complete.content)["redirect_url"], "/admin/")
        self.assertNotEqual(self.client.session.session_key, original_session_key)
        admin_response = self.client.get("/admin/")
        self.assertEqual(admin_response.status_code, 200)

    def test_non_staff_passkey_login_does_not_grant_admin_access(self):
        ordinary = get_user_model().objects.create_user(email="ordinary@example.com", password="OrdinaryPassword123", name="Ordinary")
        self.helper.credential = make_credential(ordinary, "ordinary-credential")
        self.client.post(reverse("passkey_authentication_begin"), data="{}", content_type="application/json")

        response = self.client.post(
            reverse("passkey_authentication_complete"),
            data=json.dumps({"id": "ordinary-credential", "type": "public-key"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/admin/").status_code, 302)

    def test_invalid_expired_and_replayed_challenges_are_rejected(self):
        credential = make_credential(self.user, "replay-credential")
        begin = self.client.post(reverse("passkey_authentication_begin"), data="{}", content_type="application/json")
        self.assertEqual(begin.status_code, 200)
        session = self.client.session
        session["passkeys.authentication_started_at"] = time.time() - 301
        session.save()
        expired = self.client.post(
            reverse("passkey_authentication_complete"),
            data=json.dumps({"id": "replay-credential", "type": "public-key"}),
            content_type="application/json",
        )
        self.assertEqual(expired.status_code, 400)

        self.client.post(reverse("passkey_authentication_begin"), data="{}", content_type="application/json")
        valid = self.client.post(
            reverse("passkey_authentication_complete"),
            data=json.dumps({"id": "replay-credential", "type": "public-key"}),
            content_type="application/json",
        )
        replay = self.client.post(
            reverse("passkey_authentication_complete"),
            data=json.dumps({"id": "replay-credential", "type": "public-key"}),
            content_type="application/json",
        )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(WebAuthnCredential.objects.get(pk=credential.pk).user_id, self.user.pk)

    def test_inactive_user_is_rejected_by_completion_view(self):
        inactive = get_user_model().objects.create_user(email="inactive@example.com", password="InactivePassword123", name="Inactive", is_active=False)
        self.helper.credential = make_credential(inactive, "inactive-credential")
        self.client.post(reverse("passkey_authentication_begin"), data="{}", content_type="application/json")

        response = self.client.post(
            reverse("passkey_authentication_complete"),
            data=json.dumps({"id": "inactive-credential", "type": "public-key"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_origin_rp_and_user_verification_configuration_is_explicit(self):
        from profile.passkeys import StrictWebAuthnHelper
        helper = StrictWebAuthnHelper(request=None)

        self.assertEqual(helper.get_relying_party_domain(), "www.cantero-solutions.com.ar")
        self.assertEqual(helper.get_allowed_origins(), ["https://www.cantero-solutions.com.ar"])
        self.assertEqual(settings.PASSKEY_CHALLENGE_TTL_SECONDS, 300)
        options = helper.get_generate_registration_options_kwargs(user=self.user)
        self.assertEqual(options["authenticator_selection"].user_verification.value, "required")

    def test_webauthn_library_rejects_incorrect_origin_and_rp_id(self):
        credential_id = b"origin-test-credential"
        credential = make_credential(self.user, credential_id.decode())
        helper = WebAuthnHelper(request=None)
        challenge = b"test-challenge"
        state = {"challenge": bytes_to_base64url(challenge), "require_user_verification": True}

        def assertion(origin, rp_id_hash):
            client_data = json.dumps({
                "type": "webauthn.get",
                "challenge": bytes_to_base64url(challenge),
                "origin": origin,
            }).encode()
            authenticator_data = rp_id_hash + bytes([0x05]) + (0).to_bytes(4, "big")
            return {
                "id": bytes_to_base64url(credential_id),
                "rawId": bytes_to_base64url(credential_id),
                "type": "public-key",
                "response": {
                    "clientDataJSON": bytes_to_base64url(client_data),
                    "authenticatorData": bytes_to_base64url(authenticator_data),
                    "signature": bytes_to_base64url(b"not-a-valid-signature"),
                    "userHandle": None,
                },
            }

        with self.assertRaises(InvalidAuthenticationResponse):
            helper.authenticate_complete(
                user=None,
                state=state,
                data=assertion("https://attacker.example", hashlib_module.sha256(settings.PASSKEY_RP_ID.encode()).digest()),
            )
        with self.assertRaises(InvalidAuthenticationResponse):
            helper.authenticate_complete(
                user=None,
                state=state,
                data=assertion("https://www.cantero-solutions.com.ar", hashlib_module.sha256(b"wrong.example").digest()),
            )

    def test_drf_token_authentication_is_unchanged(self):
        token = Token.objects.create(user=self.user)
        response = self.client.get(
            "/api/profiles/",
            HTTP_AUTHORIZATION=f"Token {token.key}",
        )

        self.assertEqual(response.status_code, 200)

    def test_csrf_protects_reauthentication_and_revocation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        client.get(reverse("passkey_manage"))
        response = client.post(reverse("passkey_reauthenticate"), {"password": "A-strong-test-password-123"})

        self.assertEqual(response.status_code, 403)

    def test_csrf_protects_registration_and_authentication_ceremonies(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        registration = client.post(reverse("passkey_registration_begin"), {"name": "No CSRF"})
        authentication = Client(enforce_csrf_checks=True).post(
            reverse("passkey_authentication_begin"), data="{}", content_type="application/json"
        )

        self.assertEqual(registration.status_code, 403)
        self.assertEqual(authentication.status_code, 403)

    def test_login_redirect_rejects_external_next_url(self):
        self.helper.credential = make_credential(self.user, "safe-redirect-credential")
        self.client.post(reverse("passkey_authentication_begin"), data="{}", content_type="application/json")

        response = self.client.post(
            reverse("passkey_authentication_complete") + "?next=https://attacker.example/",
            data=json.dumps({"id": "safe-redirect-credential", "type": "public-key"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["redirect_url"], "/dashboard/")

    def test_login_endpoint_is_rate_limited(self):
        for _ in range(20):
            response = self.client.post(
                reverse("passkey_authentication_begin"), data="{}", content_type="application/json"
            )
            self.assertEqual(response.status_code, 200)

        limited = self.client.post(
            reverse("passkey_authentication_begin"), data="{}", content_type="application/json"
        )

        self.assertEqual(limited.status_code, 429)

    def test_admin_login_shows_passkey_link_when_enabled(self):
        response = self.client.get("/admin/login/?next=/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sign in with a passkey")

    def test_logout_invalidates_passkey_session(self):
        self.helper.credential = make_credential(self.user, "logout-credential")
        self.client.post(reverse("passkey_authentication_begin"), data="{}", content_type="application/json")
        self.client.post(
            reverse("passkey_authentication_complete"),
            data=json.dumps({"id": "logout-credential", "type": "public-key"}),
            content_type="application/json",
        )

        response = self.client.post(reverse("logout"))

        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)
