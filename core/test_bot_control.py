from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import BotControl


BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
PAUSE_REQUESTED = "Pausa solicitada"
RESUME_REQUESTED = "Reanudación solicitada"
CONFIRM_REQUIRED = "Confirmá la solicitud de pausa antes de continuar. No se registró ningún cambio."
DESIRED_STATE_NOTE = "Esto solo guarda el estado solicitado. No hay confirmación de que el bot lo haya aplicado."


class BotControlHttpTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="TestPassword123",
            name="Owner",
            is_staff=False,
        )
        self.pause_url = reverse("bot_stop")
        self.resume_url = reverse("bot_resume")
        self.dashboard_url = reverse("dashboard")

    def test_control_table_and_columns_stay_unchanged(self):
        self.assertEqual(BotControl._meta.db_table, "core_botcontrol")
        self.assertEqual(
            {field.name for field in BotControl._meta.local_fields},
            {"id", "is_paused", "updated_at", "updated_by", "reason"},
        )

    def test_anonymous_post_does_not_request_pause(self):
        response = self.client.post(
            self.pause_url,
            {"confirm": "yes", "reason": "should-not-write"},
            HTTP_ACCEPT=BROWSER_ACCEPT,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])
        self.assertFalse(BotControl.objects.filter(is_paused=True).exists())

    def test_pause_get_is_rejected(self):
        self.client.force_login(self.user)

        response = self.client.get(self.pause_url)

        self.assertEqual(response.status_code, 405)
        self.assertFalse(BotControl.objects.exists())

    def test_html_pause_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            self.pause_url,
            {"confirm": "yes", "reason": "csrf"},
            HTTP_ACCEPT=BROWSER_ACCEPT,
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(BotControl.objects.filter(is_paused=True).exists())

    def test_non_staff_html_pause_redirects_with_requested_message(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.pause_url,
            {
                "confirm": "yes",
                "reason": "mantenimiento",
                "next": self.dashboard_url,
            },
            HTTP_ACCEPT=BROWSER_ACCEPT,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{self.dashboard_url}#control-seguro")
        self.assertNotIn("application/json", response.get("Content-Type", ""))
        control = BotControl.objects.get()
        self.assertTrue(control.is_paused)
        self.assertEqual(control.reason, "mantenimiento")
        self.assertEqual(control.updated_by, self.user)
        page = self._dashboard_page()
        self.assertContains(page, PAUSE_REQUESTED)
        self.assertNotContains(page, "Bot pausado")
        self.assertNotContains(page, "Bot reanudado")

    def test_html_pause_without_confirmation_does_not_write(self):
        self.client.force_login(self.user)
        existing = BotControl.get_solo()
        existing.reason = "anterior"
        existing.save(update_fields=["reason", "updated_at"])

        response = self.client.post(
            self.pause_url,
            {"reason": "no-confirmado", "next": "https://evil.example/phish"},
            HTTP_ACCEPT=BROWSER_ACCEPT,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{self.dashboard_url}#control-seguro")
        self.assertNotIn("evil.example", response["Location"])
        existing.refresh_from_db()
        self.assertFalse(existing.is_paused)
        self.assertEqual(existing.reason, "anterior")
        page = self._dashboard_page()
        self.assertContains(page, CONFIRM_REQUIRED)

    def test_html_resume_redirects_with_requested_message(self):
        self.client.force_login(self.user)
        control = BotControl.get_solo()
        control.is_paused = True
        control.reason = "mantenimiento"
        control.save(update_fields=["is_paused", "reason", "updated_at"])

        response = self.client.post(
            self.resume_url,
            {"reason": "continuar", "next": "/dashboard/analytics/"},
            HTTP_ACCEPT=BROWSER_ACCEPT,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/dashboard/analytics/")
        control.refresh_from_db()
        self.assertFalse(control.is_paused)
        self.assertEqual(control.reason, "continuar")
        self.assertEqual(control.updated_by, self.user)
        page = self._dashboard_page()
        self.assertContains(page, RESUME_REQUESTED)

    def test_unsafe_next_and_action_url_fall_back_to_dashboard(self):
        self.client.force_login(self.user)

        for unsafe in ("https://evil.example/phish", "//evil.example/phish", self.pause_url):
            BotControl.objects.all().delete()
            response = self.client.post(
                self.pause_url,
                {"confirm": "yes", "reason": unsafe, "next": unsafe},
                HTTP_ACCEPT=BROWSER_ACCEPT,
            )
            self.assertEqual(response.status_code, 302, unsafe)
            self.assertEqual(response["Location"], f"{self.dashboard_url}#control-seguro", unsafe)
            self.assertNotIn("evil.example", response["Location"])

    def test_same_host_referer_is_used_when_next_is_missing(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.resume_url,
            {},
            HTTP_ACCEPT=BROWSER_ACCEPT,
            HTTP_REFERER="http://testserver/dashboard/churn/",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "http://testserver/dashboard/churn/")

    def test_external_referer_is_rejected(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.resume_url,
            {},
            HTTP_ACCEPT=BROWSER_ACCEPT,
            HTTP_REFERER="https://evil.example/dashboard/",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], f"{self.dashboard_url}#control-seguro")
        self.assertNotIn("evil.example", response["Location"])

    def test_json_client_still_receives_the_existing_payload(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.pause_url,
            {"confirm": "yes", "reason": "api"},
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])
        payload = response.json()
        self.assertEqual(
            set(payload),
            {"is_paused", "status", "updated_at", "updated_by", "reason"},
        )
        self.assertEqual(payload["is_paused"], True)
        self.assertEqual(payload["status"], "paused")
        self.assertEqual(payload["reason"], "api")
        self.assertEqual(payload["updated_by"], "owner@example.com")
        self.assertTrue(payload["updated_at"])
        self.assertEqual(BotControl.objects.get().reason, "api")

    def test_pause_save_writes_only_the_existing_columns(self):
        self.client.force_login(self.user)
        update_fields = []
        original_save = BotControl.save

        def record_save(instance, *args, **kwargs):
            if "update_fields" in kwargs:
                update_fields.append(list(kwargs["update_fields"]))
            return original_save(instance, *args, **kwargs)

        with patch.object(BotControl, "save", record_save):
            response = self.client.post(
                self.pause_url,
                {"confirm": "yes", "reason": "column-lock"},
                HTTP_ACCEPT="application/json",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(update_fields, [["is_paused", "reason", "updated_by", "updated_at"]])

    def test_json_pause_without_confirmation_returns_400_and_does_not_write(self):
        self.client.force_login(self.user)
        existing = BotControl.get_solo()
        existing.reason = "anterior"
        existing.save(update_fields=["reason", "updated_at"])

        response = self.client.post(
            self.pause_url,
            {"reason": "sin-confirmacion"},
            content_type="application/x-www-form-urlencoded",
            HTTP_ACCEPT="application/json, text/html;q=0.8",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "confirmation_required")
        self.assertIn("No se registró ningún cambio", response.json()["detail"])
        existing.refresh_from_db()
        self.assertFalse(existing.is_paused)
        self.assertEqual(existing.reason, "anterior")

    def test_json_body_pause_accepts_confirm_yes_or_true(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.pause_url,
            data='{"confirm": "yes", "reason": "desde-json"}',
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json()),
            {"is_paused", "status", "updated_at", "updated_by", "reason"},
        )
        self.assertTrue(response.json()["is_paused"])
        self.assertEqual(response.json()["reason"], "desde-json")

        BotControl.objects.all().delete()
        boolean_confirm = self.client.post(
            self.pause_url,
            data='{"confirm": true, "reason": "bool"}',
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(boolean_confirm.status_code, 200)
        self.assertEqual(boolean_confirm.json()["reason"], "bool")

        BotControl.objects.all().delete()
        rejected = self.client.post(
            self.pause_url,
            data='{"confirm": "no", "reason": "no"}',
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(BotControl.objects.filter(is_paused=True).exists())

    def test_browser_like_accept_never_returns_raw_json(self):
        self.client.force_login(self.user)

        response = self.client.post(
            self.pause_url,
            {"confirm": "yes"},
            HTTP_ACCEPT="text/html, application/json;q=0.1, */*;q=0.8",
        )

        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b'"is_paused"', response.content)

    def test_wildcard_accept_keeps_json_for_existing_clients(self):
        self.client.force_login(self.user)

        rejected = self.client.post(self.pause_url, {"reason": "curl"}, HTTP_ACCEPT="*/*")
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(BotControl.objects.filter(is_paused=True).exists())

        response = self.client.post(
            self.pause_url,
            {"confirm": "yes", "reason": "curl"},
            HTTP_ACCEPT="*/*",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "paused")
        self.assertEqual(response.json()["reason"], "curl")

    def test_missing_accept_keeps_json_for_existing_clients(self):
        self.client.force_login(self.user)

        rejected = self.client.post(self.pause_url, {"reason": "no-accept"})
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(BotControl.objects.filter(is_paused=True).exists())

        response = self.client.post(self.pause_url, {"confirm": "yes", "reason": "no-accept"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reason"], "no-accept")

    def _dashboard_page(self):
        with patch("dashboard.views.get_dashboard_context") as mock_context:
            context = _empty_dashboard_context()
            context["bot_control"] = BotControl.get_solo()
            mock_context.return_value.context = context
            return self.client.get(self.dashboard_url)


class BotControlDashboardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            email="owner@example.com",
            password="TestPassword123",
            name="Owner",
            is_staff=False,
        )
        self.client.force_login(self.user)

    def test_dashboard_shows_desired_state_in_buenos_aires(self):
        control = BotControl(
            is_paused=True,
            reason="ventana",
            updated_by=self.user,
            updated_at=datetime(2026, 10, 25, 18, 16, 56, tzinfo=timezone.utc),
        )
        response = self._render(control)

        self.assertContains(response, "Estado solicitado: pausado")
        self.assertContains(response, "25/10/2026 15:16 ART")
        self.assertContains(response, "owner@example.com")
        self.assertContains(response, "ventana")
        self.assertContains(response, DESIRED_STATE_NOTE)
        self.assertContains(response, "Solicitar pausa")
        self.assertContains(response, "Solicitar reanudación")
        self.assertContains(response, 'name="confirm"')
        self.assertContains(response, 'name="reason"')
        self.assertContains(response, 'name="next"')
        self.assertContains(response, 'data-status-url="/bot/status/"')
        self.assertContains(response, "bot_control.js")
        self.assertContains(response, "data-bot-control-retry")
        self.assertContains(response, "Reintentar el pedido")
        self.assertNotContains(response, "form.submit")
        self.assertNotContains(response, ">Stop<")
        self.assertNotContains(response, ">Resume<")
        self.assertNotContains(response, "Bot pausado")
        self.assertNotContains(response, "el bot está pausado")
        self.assertNotContains(response, "bot stopped")
        html = response.content.decode()
        self.assertLess(html.index('id="control-seguro"'), html.index("BUY / Cooldown"))

    def test_running_request_and_unknown_control_are_labeled_as_desired(self):
        running = BotControl(is_paused=False, reason="", updated_by=None, updated_at=None)
        running_page = self._render(running)
        self.assertContains(running_page, "Estado solicitado: en ejecución")

        unknown_page = self._render(None)
        self.assertContains(unknown_page, "Estado solicitado: desconocido")

    def test_demo_hides_pause_controls(self):
        response = self.client.get(reverse("dashboard_demo"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Solicitar pausa")
        self.assertNotContains(response, reverse("bot_stop"))

    def _render(self, control):
        with patch("dashboard.views.get_dashboard_context") as mock_context:
            context = _empty_dashboard_context()
            context["bot_control"] = control
            mock_context.return_value.context = context
            return self.client.get(reverse("dashboard"))


def _empty_dashboard_context():
    from core.tests import DashboardEndpointTests

    return DashboardEndpointTests.empty_dashboard_context(None)
