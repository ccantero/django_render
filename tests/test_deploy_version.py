import os
from datetime import datetime, timezone
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from django_render.version import (
    build_release_info,
    is_core_semver,
    read_app_version,
    resolve_deployed_at,
    short_commit,
)


class AppVersionSourceTests(SimpleTestCase):
    def test_version_file_is_core_semver(self):
        version_path = Path(__file__).resolve().parents[1] / "VERSION"
        text = version_path.read_text(encoding="utf-8").strip()

        self.assertTrue(is_core_semver(text), text)
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
        deployed_at = datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc)

        payload = build_release_info(
            version="1.0.0",
            commit="a1b2c3d",
            deployed_at=deployed_at,
        )

        self.assertEqual(payload["version"], "1.0.0")
        self.assertEqual(payload["commit"], "a1b2c3d")
        self.assertEqual(payload["deployed_at"], "2026-10-25T14:30:00-03:00")
        self.assertEqual(payload["display"], "v1.0.0+a1b2c3d · 25/10 14:30 ART")

    def test_missing_commit_and_timestamp_fall_back_without_error(self):
        payload = build_release_info(version="1.0.0", commit="dev", deployed_at=None)

        self.assertEqual(payload["display"], "v1.0.0+dev · unknown")
        self.assertIsNone(payload["deployed_at"])

    def test_invalid_version_text_falls_back_instead_of_crashing(self):
        self.assertEqual(read_app_version(Path("/tmp/does-not-exist-version")), "0.0.0")

    def test_deployed_at_prefers_env_then_render_mtime_then_unknown(self):
        version_path = Path("/tmp/django_render_version_mtime")
        version_path.write_text("1.0.0\n", encoding="utf-8")
        stamp = datetime(2026, 10, 25, 17, 30, tzinfo=timezone.utc)
        os.utime(version_path, (stamp.timestamp(), stamp.timestamp()))
        process_started_at = datetime(2020, 1, 1, tzinfo=timezone.utc)

        from_env = resolve_deployed_at(
            environ={"DEPLOYED_AT": "2026-10-25T18:00:00Z", "RENDER": "true"},
            version_path=version_path,
            process_started_at=process_started_at,
        )
        from_mtime = resolve_deployed_at(
            environ={"RENDER": "true", "DEPLOYED_AT": "not-a-timestamp"},
            version_path=version_path,
            process_started_at=process_started_at,
        )
        local = resolve_deployed_at(
            environ={},
            version_path=version_path,
            process_started_at=process_started_at,
        )
        missing_file = resolve_deployed_at(
            environ={"RENDER": "true"},
            version_path=Path("/tmp/does-not-exist-version-mtime"),
            process_started_at=process_started_at,
        )

        self.assertEqual(from_env, datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc))
        self.assertEqual(from_mtime, stamp)
        self.assertIsNone(local)
        self.assertEqual(missing_file, process_started_at)

    def test_release_payload_does_not_include_render_service_identity(self):
        payload = build_release_info(version="1.0.0", commit="a1b2c3d", deployed_at=None)

        self.assertEqual(
            set(payload),
            {"version", "commit", "deployed_at", "display"},
        )
        self.assertNotIn("srv-secret", str(payload))


class DeployVersionHttpTests(TestCase):
    def setUp(self):
        super().setUp()
        self._env = os.environ.copy()
        os.environ.pop("RENDER_GIT_COMMIT", None)
        os.environ.pop("RENDER_GIT_BRANCH", None)
        os.environ.pop("RENDER_SERVICE_ID", None)
        os.environ.pop("RENDER", None)
        os.environ.pop("DEPLOYED_AT", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        super().tearDown()

    def test_version_endpoint_is_public_minimal_json(self):
        os.environ["RENDER_GIT_COMMIT"] = "a1b2c3d4e5f6789012345678901234567890abcd"
        os.environ["RENDER_SERVICE_ID"] = "srv-secret-123"
        os.environ["RENDER_GIT_BRANCH"] = "main"
        os.environ["DEPLOYED_AT"] = "2026-10-25T17:30:00Z"

        response = self.client.get(reverse("version"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertIn("no-store", response["Cache-Control"])
        payload = response.json()
        self.assertEqual(payload["version"], read_app_version())
        self.assertEqual(payload["commit"], "a1b2c3d")
        self.assertEqual(payload["deployed_at"], "2026-10-25T14:30:00-03:00")
        self.assertEqual(
            payload["display"],
            f"v{payload['version']}+a1b2c3d · 25/10 14:30 ART",
        )
        body = response.content.decode()
        self.assertNotIn("srv-secret-123", body)
        self.assertNotIn("RENDER_SERVICE_ID", body)
        self.assertNotIn("RENDER_GIT_BRANCH", body)

    def test_version_endpoint_falls_back_locally_and_is_get_only(self):
        response = self.client.get(reverse("version"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["commit"], "dev")
        self.assertIsNone(payload["deployed_at"])
        self.assertEqual(payload["display"], f"v{payload['version']}+dev · unknown")
        self.assertEqual(self.client.post(reverse("version")).status_code, 405)

    def test_home_and_public_pwa_pages_show_version_when_navigation_is_hidden(self):
        response = self.client.get(reverse("home"))
        calculator = self.client.get(reverse("currencyconverter:calculadora"))
        rates = self.client.get(reverse("currencyconverter:cotizaciones"))
        stylesheet = Path("static/core/css/calculator.css").read_text(encoding="utf-8")
        standalone = stylesheet.split("@media (display-mode: standalone)", 1)[1]

        for page in (response, calculator, rates):
            self.assertEqual(page.status_code, 200)
            self.assertContains(page, 'id="app-version"')
            self.assertContains(page, "v")
            self.assertContains(page, "+dev")
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
