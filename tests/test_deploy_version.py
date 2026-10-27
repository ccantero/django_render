import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from django_render.version import (
    build_release_info,
    is_core_semver,
    read_app_version,
    resolve_timestamp,
    short_commit,
    write_build_stamp,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CLEARED_VERSION_ENV = {
    "RENDER_GIT_COMMIT": "",
    "RENDER_GIT_BRANCH": "",
    "RENDER_SERVICE_ID": "",
    "RENDER": "",
    "DEPLOYED_AT": "",
}
EXPLICIT_AT = datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc)
STAMP_AT = datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc)


class AppVersionSourceTests(SimpleTestCase):
    def test_version_file_is_core_semver(self):
        version_path = REPO_ROOT / "VERSION"
        text = version_path.read_text(encoding="utf-8").strip()

        self.assertTrue(is_core_semver(text), text)
        self.assertEqual(text, "2.1.0")
        self.assertNotIn("+", text)
        self.assertNotIn("-", text)
        self.assertEqual(read_app_version(version_path), text)

    def test_short_commit_uses_seven_characters_or_dev(self):
        self.assertEqual(short_commit(None), "dev")
        self.assertEqual(short_commit(""), "dev")
        self.assertEqual(short_commit("   "), "dev")
        self.assertEqual(
            short_commit("A1B2C3D4E5F6789012345678901234567890ABCD"),
            "a1b2c3d",
        )
        self.assertEqual(short_commit("not a sha !!!"), "dev")

    def test_display_uses_semver_build_metadata_and_buenos_aires_time(self):
        payload = build_release_info(
            version="1.0.0",
            commit="a1b2c3d",
            deployed_at=STAMP_AT,
            timestamp_source="build_stamp",
        )

        self.assertEqual(
            payload,
            {
                "version": "1.0.0",
                "commit": "a1b2c3d",
                "deployed_at": "2026-10-25T14:30:00-03:00",
                "timestamp_source": "build_stamp",
                "display": "v1.0.0+a1b2c3d · 25/10 14:30 ART",
            },
        )
        self.assertNotIn("~", payload["display"])

    def test_missing_commit_and_timestamp_fall_back_without_error(self):
        payload = build_release_info(
            version="1.0.0",
            commit="dev",
            deployed_at=None,
            timestamp_source="unknown",
        )

        self.assertEqual(payload["display"], "v1.0.0+dev · unknown")
        self.assertIsNone(payload["deployed_at"])
        self.assertEqual(payload["timestamp_source"], "unknown")

    def test_unknown_source_does_not_present_a_time(self):
        payload = build_release_info(
            version="1.0.0",
            commit="a1b2c3d",
            deployed_at=STAMP_AT,
            timestamp_source="process_start",
        )

        self.assertIsNone(payload["deployed_at"])
        self.assertEqual(payload["timestamp_source"], "unknown")
        self.assertIn("unknown", payload["display"])

    def test_invalid_version_text_falls_back_instead_of_crashing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing-VERSION"
            self.assertEqual(read_app_version(missing), "0.0.0")

    def test_explicit_timestamp_beats_build_stamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp_path = Path(tmp) / "build_info.json"
            write_build_stamp(stamp_path, now=STAMP_AT)

            moment, source = resolve_timestamp(
                environ={"DEPLOYED_AT": "2026-10-25T18:00:00Z"},
                stamp_path=stamp_path,
            )

        self.assertEqual(moment, EXPLICIT_AT)
        self.assertEqual(source, "explicit")

    def test_restart_without_redeploy_keeps_stamp_and_ignores_mtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version_file = root / "VERSION"
            version_file.write_text("1.0.0\n", encoding="utf-8")
            stamp_path = root / "build_info.json"
            write_build_stamp(stamp_path, now=STAMP_AT)
            before, before_source = resolve_timestamp(
                environ={"RENDER": "true"},
                stamp_path=stamp_path,
            )
            restarted_at = datetime(2026, 10, 25, 19, 45, tzinfo=timezone.utc)
            os_utime = restarted_at.timestamp()
            os.utime(version_file, (os_utime, os_utime))
            after, after_source = resolve_timestamp(
                environ={"RENDER": "true"},
                stamp_path=stamp_path,
            )
            missing, missing_source = resolve_timestamp(
                environ={"RENDER": "true"},
                stamp_path=root / "no-stamp.json",
            )

        self.assertEqual(before, STAMP_AT)
        self.assertEqual(after, before)
        self.assertEqual(before_source, "build_stamp")
        self.assertEqual(after_source, "build_stamp")
        self.assertNotEqual(after, restarted_at)
        self.assertIsNone(missing)
        self.assertEqual(missing_source, "unknown")

    def test_invalid_timestamp_metadata_does_not_crash_or_invent_a_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp_path = Path(tmp) / "build_info.json"
            cases = [
                "{not-json",
                json.dumps(["2026-10-25T17:30:00Z"]),
                json.dumps({"deployed_at": "not-a-timestamp", "secret": "srv-secret"}),
                json.dumps({"note": "missing instant"}),
                "",
            ]
            for raw in cases:
                stamp_path.write_text(raw, encoding="utf-8")
                moment, source = resolve_timestamp(
                    environ={"DEPLOYED_AT": "yesterday", "RENDER": "true"},
                    stamp_path=stamp_path,
                )
                self.assertIsNone(moment, raw)
                self.assertEqual(source, "unknown", raw)
                self.assertNotIn("srv-secret", str(moment))

            write_build_stamp(stamp_path, now=STAMP_AT)
            moment, source = resolve_timestamp(
                environ={"DEPLOYED_AT": "not-a-timestamp"},
                stamp_path=stamp_path,
            )

        self.assertEqual(moment, STAMP_AT)
        self.assertEqual(source, "build_stamp")

    def test_release_payload_does_not_include_render_service_identity(self):
        payload = build_release_info(
            version="1.0.0",
            commit="a1b2c3d",
            deployed_at=None,
            timestamp_source="unknown",
        )

        self.assertEqual(
            set(payload),
            {"version", "commit", "deployed_at", "timestamp_source", "display"},
        )
        self.assertNotIn("srv-secret", str(payload))


class StampBuildCommandTests(SimpleTestCase):
    def test_stamp_build_writes_utc_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp_path = Path(tmp) / "nested" / "build_info.json"
            with patch(
                "django_render.version.datetime",
                wraps=datetime,
            ) as clock:
                clock.now.return_value = STAMP_AT
                call_command("stamp_build", path=str(stamp_path))

            raw = stamp_path.read_text(encoding="utf-8")

        self.assertEqual(json.loads(raw), {"deployed_at": "2026-10-25T17:30:00Z"})
        self.assertNotIn("RENDER_SERVICE_ID", raw)


class DeployVersionHttpTests(TestCase):
    def test_version_endpoint_prefers_explicit_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp_path = Path(tmp) / "build_info.json"
            write_build_stamp(stamp_path, now=STAMP_AT)
            with patch("django_render.version.BUILD_STAMP_PATH", stamp_path):
                with patch.dict(
                    "os.environ",
                    {
                        "RENDER_GIT_COMMIT": "a1b2c3d4e5f6789012345678901234567890abcd",
                        "RENDER_SERVICE_ID": "srv-secret-123",
                        "RENDER_GIT_BRANCH": "main",
                        "DEPLOYED_AT": "2026-10-25T18:00:00Z",
                    },
                ):
                    response = self.client.get(reverse("version"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn("no-store", response["Cache-Control"])
        payload = response.json()
        self.assertEqual(payload["version"], read_app_version())
        self.assertEqual(payload["commit"], "a1b2c3d")
        self.assertEqual(payload["deployed_at"], "2026-10-25T15:00:00-03:00")
        self.assertEqual(payload["timestamp_source"], "explicit")
        self.assertEqual(
            payload["display"],
            f"v{payload['version']}+a1b2c3d · 25/10 15:00 ART",
        )
        body = response.content.decode()
        self.assertNotIn("srv-secret-123", body)
        self.assertNotIn("RENDER_SERVICE_ID", body)
        self.assertNotIn("RENDER_GIT_BRANCH", body)

    def test_version_endpoint_uses_build_stamp_when_env_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            stamp_path = Path(tmp) / "build_info.json"
            write_build_stamp(stamp_path, now=STAMP_AT)
            with patch("django_render.version.BUILD_STAMP_PATH", stamp_path):
                with patch.dict(
                    "os.environ",
                    {"RENDER_GIT_COMMIT": "", "DEPLOYED_AT": "not-a-timestamp"},
                ):
                    response = self.client.get(reverse("version"))

        payload = response.json()
        self.assertEqual(payload["commit"], "dev")
        self.assertEqual(payload["timestamp_source"], "build_stamp")
        self.assertEqual(payload["deployed_at"], "2026-10-25T14:30:00-03:00")
        self.assertEqual(payload["display"], f"v{payload['version']}+dev · 25/10 14:30 ART")

    def test_version_endpoint_falls_back_locally_and_is_get_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_stamp = Path(tmp) / "build_info.json"
            with patch("django_render.version.BUILD_STAMP_PATH", missing_stamp):
                with patch.dict("os.environ", CLEARED_VERSION_ENV):
                    response = self.client.get(reverse("version"))
                    post = self.client.post(reverse("version"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["commit"], "dev")
        self.assertIsNone(payload["deployed_at"])
        self.assertEqual(payload["timestamp_source"], "unknown")
        self.assertEqual(payload["display"], f"v{payload['version']}+dev · unknown")
        self.assertEqual(post.status_code, 405)

    def test_home_and_public_pwa_pages_show_version_when_navigation_is_hidden(self):
        stylesheet = (REPO_ROOT / "static/core/css/calculator.css").read_text(encoding="utf-8")
        standalone = stylesheet.split("@media (display-mode: standalone)", 1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            missing_stamp = Path(tmp) / "build_info.json"
            with patch("django_render.version.BUILD_STAMP_PATH", missing_stamp):
                with patch.dict("os.environ", CLEARED_VERSION_ENV):
                    response = self.client.get(reverse("home"))
                    calculator = self.client.get(reverse("currencyconverter:calculadora"))
                    rates = self.client.get(reverse("currencyconverter:cotizaciones"))

        for page in (response, calculator, rates):
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, 'id="app-version"')
            self.assertContains(page, "+dev")
            self.assertContains(page, "unknown")
            self.assertContains(page, "fetch(")
            self.assertContains(page, "no-store")

        self.assertContains(response, "Bienvenido a Cantero Solutions!")
        self.assertContains(calculator, "id='navbar'")
        self.assertIn("#navbar", standalone)
        self.assertIn("display: none", standalone)
        self.assertIn(".calculator-page .app-version", standalone)
        self.assertIn("display: block", standalone.split(".calculator-page .app-version", 1)[1])
        self.assertNotIn(".app-version {\n    display: none", stylesheet)

    def test_service_worker_refreshes_navigation_html_and_skips_version(self):
        response = self.client.get("/currencyconverter/service-worker.js")
        script = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn("calculadora-uva-v2", script)
        self.assertIn("cache: 'no-store'", script)
        self.assertIn("/version/", script)
        self.assertIn("service-worker.js", script)
        self.assertIn("caches.delete", script)
        self.assertNotIn("'/dashboard/'", script)
        self.assertNotIn("RENDER_SERVICE_ID", script)
