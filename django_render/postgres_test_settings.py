"""Guarded settings for disposable, loopback-only PostgreSQL validation."""

import os
import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from django_render.settings import *  # noqa: F403


database_url = os.environ.get("PASSKEY_TEST_DATABASE_URL", "")
parsed = urlsplit(database_url)
database_name = parsed.path.lstrip("/")
test_host = os.environ.get("PASSKEY_TEST_HOST", "passkeys.test").lower()
template_name = os.environ.get("PASSKEY_TEST_TEMPLATE", "")
django_test_database_name = os.environ.get("PASSKEY_TEST_DJANGO_DATABASE", "")
if (
    parsed.scheme not in {"postgres", "postgresql", "postgresql+psycopg2"}
    or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
    or not re.fullmatch(r"test_passkey_validation_[0-9a-f]{12}", database_name)
    or parsed.username != "passkey_test"
    or not test_host.endswith(".test")
    or "/" in test_host
    or ":" in test_host
    or not re.fullmatch(r"template_passkey_[0-9a-f]{12}", template_name)
    or not re.fullmatch(r"test_django_passkey_[0-9a-f]{12}", django_test_database_name)
):
    raise ImproperlyConfigured(
        "PASSKEY_TEST_DATABASE_URL must use the passkey_test role and a test_ "
        "database on loopback; remote and production databases are forbidden."
    )

DATABASES = {  # noqa: F405
    "default": dj_database_url.parse(database_url, conn_max_age=0),  # noqa: F405
}
# Historical unqualified migrations stay in the Django-owned schema. Bot-owned
# fixture tables are always schema-qualified and are not implicitly visible.
DATABASES["default"]["OPTIONS"] = {"options": "-c search_path=django,public"}
DATABASES["default"]["TEST"] = {
    "NAME": django_test_database_name,
    "TEMPLATE": template_name,
}
ALLOWED_HOSTS = [test_host, "testserver", "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = [f"https://{test_host}"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Deployment checks intentionally use a loopback-only synthetic Passkey
# configuration. Ordinary pytest runs retain the project's DEBUG-mode defaults,
# so existing assertions cover the normal configured RP identity.
if os.environ.get("PASSKEY_TEST_FORCE_PASSKEY_ORIGIN") == "1":
    PASSKEY_RP_ID = test_host
    PASSKEY_ALLOWED_ORIGINS = [f"https://{test_host}"]
    OTP_WEBAUTHN_RP_ID = test_host
    OTP_WEBAUTHN_ALLOWED_ORIGINS = PASSKEY_ALLOWED_ORIGINS
