"""Guarded settings for disposable, loopback-only PostgreSQL validation."""

import os
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from django_render.settings import *  # noqa: F403


database_url = os.environ.get("PASSKEY_TEST_DATABASE_URL", "")
parsed = urlsplit(database_url)
database_name = parsed.path.lstrip("/")
test_host = os.environ.get("PASSKEY_TEST_HOST", "passkeys.test").lower()
if (
    parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2"}
    or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
    or not database_name.startswith("test_")
    or parsed.username != "passkey_test"
    or not test_host.endswith(".test")
    or "/" in test_host
    or ":" in test_host
):
    raise ImproperlyConfigured(
        "PASSKEY_TEST_DATABASE_URL must use the passkey_test role and a test_ "
        "database on loopback; remote and production databases are forbidden."
    )

DATABASES = {  # noqa: F405
    "default": dj_database_url.parse(database_url, conn_max_age=0),  # noqa: F405
}
DATABASES["default"]["OPTIONS"] = {"options": "-c search_path=django,public"}
ALLOWED_HOSTS = [test_host]
CSRF_TRUSTED_ORIGINS = [f"https://{test_host}"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
PASSKEY_RP_ID = test_host
PASSKEY_ALLOWED_ORIGINS = [f"https://{test_host}"]
OTP_WEBAUTHN_RP_ID = test_host
OTP_WEBAUTHN_ALLOWED_ORIGINS = PASSKEY_ALLOWED_ORIGINS
