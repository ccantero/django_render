import os
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.finders import find
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

SOURCE_ASSETS = (
    "favicon.ico",
    "core/css/master.css",
    "core/css/calculator.css",
    "core/css/aboutmestyle.css",
    "core/render-banner.png",
    "currencyconverter/js/master.js",
    "currencyconverter/icons/app-icon.svg",
    "currencyconverter/icons/app-icon-192.png",
    "currencyconverter/icons/app-icon-512.png",
    "profile/passkeys.css",
    "profile/passkeys.js",
)


class StaticSourceLayoutTests(SimpleTestCase):
    def test_project_source_assets_remain_discoverable(self):
        source_root = Path(settings.BASE_DIR) / "static"
        missing = [relative for relative in SOURCE_ASSETS if not (source_root / relative).is_file()]
        self.assertEqual(missing, [])
        for relative in SOURCE_ASSETS:
            found = find(relative)
            self.assertTrue(found, relative)
            self.assertTrue(Path(found).is_file(), relative)

    def test_admin_assets_come_from_installed_django(self):
        found = find("admin/css/base.css")
        self.assertIsNotNone(found)
        admin_css = Path(found)
        self.assertIn("django/contrib/admin/static/admin/css/base.css", admin_css.as_posix())
        self.assertTrue(find("admin/js/theme.js"))
        self.assertIsNone(find("staticfiles.json"))

    def test_collected_manifest_is_not_a_source_file(self):
        source_root = Path(settings.BASE_DIR) / "static"
        self.assertFalse((source_root / "admin").exists())
        self.assertFalse((source_root / "staticfiles.json").exists())

    def test_collectstatic_builds_output_from_source_and_packages(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as temporary_root:
            with override_settings(STATIC_ROOT=temporary_root):
                call_command("collectstatic", interactive=False, verbosity=0)
            collected = Path(temporary_root)
            self.assertTrue((collected / "core" / "css" / "master.css").is_file())
            self.assertTrue((collected / "favicon.ico").is_file())
            self.assertTrue((collected / "profile" / "passkeys.css").is_file())
            self.assertTrue((collected / "admin" / "css" / "base.css").is_file())
            self.assertTrue((collected / "admin" / "js" / "theme.js").is_file())
            collected_admin = (collected / "admin" / "css" / "base.css").read_bytes()
            packaged_admin = Path(find("admin/css/base.css")).read_bytes()
            self.assertEqual(collected_admin, packaged_admin)

    def test_production_settings_use_whitenoise_compressed_storage(self):
        env = os.environ.copy()
        env.update(
            {
                "CC_DEBUG": "false",
                "SECRET_KEY": "test",
                "TUTORIAL_BOT_TOKEN": "test-telegram-bot-token",
                "TELEGRAM_WEBHOOK_TOKEN": "test-telegram-webhook-token",
                "DATABASE_URL": "sqlite:" + "///tmp/django_render_storage_check.sqlite3",
                "DJANGO_SETTINGS_MODULE": "django_render.settings",
            }
        )
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import django; django.setup(); "
                    "from django.conf import settings; "
                    "print(settings.STORAGES['staticfiles']['BACKEND'])"
                ),
            ],
            cwd=settings.BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().splitlines()[-1],
            "whitenoise.storage.CompressedStaticFilesStorage",
        )
