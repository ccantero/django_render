from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.db import DatabaseError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from prescriptions.views import EscolaridadEspecialView, TerapiasAmbulatoriasView

TERAPIAS_URL = "prescriptions:terapias_ambulatorias"
ESCOLARIDAD_URL = "prescriptions:escolaridad_especial"


def _terapias(**overrides):
    payload = {
        "fecha": "2026-11-06",
        "nombre_apellido": "Juan Pérez",
        "dni": "30123456",
        "edad": "42",
        "diagnostico": "Diagnóstico de prueba",
        "prestacion": "Kinesiología",
        "frecuencia_semanal": "2 veces por semana",
        "periodo_desde": "2027-01",
        "periodo_hasta": "2027-12",
    }
    payload.update(overrides)
    return payload


def _escolaridad(**overrides):
    payload = {
        "fecha": "2026-11-06",
        "nombre_apellido": "Juan Pérez",
        "dni": "30123456",
        "edad": "10",
        "diagnostico": "Autismo en la niñez",
        "prestacion": "Escolaridad especial",
        "jornada": "Simple",
        "periodo_desde": "2027-01",
        "periodo_hasta": "2027-12",
    }
    payload.update(overrides)
    return payload


def _body(response):
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


class GalenoPublicGuardTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.factory = RequestFactory()

    def _post(self, url_name, payload, **extra):
        return self.client.post(reverse(url_name), payload, **extra)

    def test_anonymous_get_stays_public(self):
        for url_name, marker in (
            (TERAPIAS_URL, "Terapias ambulatorias"),
            (ESCOLARIDAD_URL, "Escolaridad especial"),
        ):
            response = self.client.get(reverse(url_name), REMOTE_ADDR="")
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, marker)

    def test_valid_post_under_the_limit_returns_a_pdf(self):
        for url_name, payload, filename in (
            (TERAPIAS_URL, _terapias(), "prescripcion_terapias_30123456.pdf"),
            (ESCOLARIDAD_URL, _escolaridad(), "prescripcion_escolaridad_30123456.pdf"),
        ):
            response = self._post(url_name, payload, REMOTE_ADDR="198.51.100.10")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], "application/pdf")
            self.assertIn(filename, response["Content-Disposition"])
            self.assertNotIn("\r", response["Content-Disposition"])
            self.assertNotIn("\n", response["Content-Disposition"])
            self.assertTrue(_body(response).startswith(b"%PDF"))

    def test_dotted_dni_is_normalized_in_the_filename(self):
        response = self._post(
            TERAPIAS_URL,
            _terapias(dni="30.123.456"),
            REMOTE_ADDR="198.51.100.11",
        )
        self.assertEqual(response.status_code, 200)
        disposition = response["Content-Disposition"]
        self.assertIn("prescripcion_terapias_30123456.pdf", disposition)
        self.assertNotIn("30.123.456", disposition)
        text = PdfReader(BytesIO(_body(response))).pages[0].extract_text()
        self.assertIn("30123456", text)

    def test_seven_digit_dni_is_accepted(self):
        response = self._post(
            ESCOLARIDAD_URL,
            _escolaridad(dni="1.234.567"),
            REMOTE_ADDR="198.51.100.12",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("prescripcion_escolaridad_1234567.pdf", response["Content-Disposition"])

    def test_bad_dni_values_return_400_and_no_pdf(self):
        rejected = (
            "123456",
            "123456789",
            "30.123.4567",
            "30123'456",
            "30123456\n",
            "30123456\r",
            "3012\r\n3456",
            "30123\"456",
        )
        for url_name, builder in (
            (TERAPIAS_URL, _terapias),
            (ESCOLARIDAD_URL, _escolaridad),
        ):
            for dni in rejected:
                response = self._post(
                    url_name,
                    builder(dni=dni),
                    REMOTE_ADDR="198.51.100.13",
                )
                self.assertEqual(response.status_code, 400, dni)
                self.assertNotEqual(response.get("Content-Type"), "application/pdf")
                self.assertFalse(_body(response).startswith(b"%PDF"))
                self.assertNotIn("\r\n\r\n", response.get("Content-Disposition", ""))

    def test_oversized_diagnosis_and_prestacion_return_400(self):
        cases = (
            (TERAPIAS_URL, _terapias(diagnostico="D" * 501)),
            (TERAPIAS_URL, _terapias(prestacion="P" * 501)),
            (ESCOLARIDAD_URL, _escolaridad(diagnostico="D" * 501)),
            (ESCOLARIDAD_URL, _escolaridad(prestacion="P" * 501)),
        )
        for url_name, payload in cases:
            response = self._post(url_name, payload, REMOTE_ADDR="198.51.100.14")
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "500", status_code=400)
            self.assertFalse(_body(response).startswith(b"%PDF"))

    def test_twenty_posts_are_allowed_and_the_next_is_429_without_a_pdf(self):
        with patch(
            "prescriptions.views.fill_prescription_pdf", return_value=b"%PDF-1.4"
        ) as fill_pdf:
            for _ in range(20):
                response = self._post(
                    TERAPIAS_URL, _terapias(), REMOTE_ADDR="198.51.100.20"
                )
                self.assertEqual(response.status_code, 200)
            blocked = self._post(
                ESCOLARIDAD_URL, _escolaridad(), REMOTE_ADDR="198.51.100.20"
            )
        self.assertEqual(blocked.status_code, 429)
        self.assertFalse(_body(blocked).startswith(b"%PDF"))
        self.assertNotEqual(blocked.get("Content-Type"), "application/pdf")
        self.assertEqual(fill_pdf.call_count, 20)

        other_client = self._post(
            TERAPIAS_URL, _terapias(), REMOTE_ADDR="198.51.100.21"
        )
        self.assertEqual(other_client.status_code, 200)
        self.assertTrue(_body(other_client).startswith(b"%PDF"))

    def test_limit_resets_after_ten_minutes_and_passkey_default_stays_fifteen(self):
        from profile.passkeys import _consume_rate_limit

        start = timezone.now()
        with patch("prescriptions.views.fill_prescription_pdf", return_value=b"%PDF-1.4"):
            with patch("profile.passkeys.timezone.now", return_value=start):
                for _ in range(20):
                    allowed = self._post(
                        TERAPIAS_URL, _terapias(), REMOTE_ADDR="198.51.100.30"
                    )
                    self.assertEqual(allowed.status_code, 200)
                blocked = self._post(
                    TERAPIAS_URL, _terapias(), REMOTE_ADDR="198.51.100.30"
                )
                self.assertEqual(blocked.status_code, 429)
            with patch(
                "profile.passkeys.timezone.now",
                return_value=start + timedelta(minutes=10),
            ):
                reset = self._post(
                    TERAPIAS_URL, _terapias(), REMOTE_ADDR="198.51.100.30"
                )
                self.assertEqual(reset.status_code, 200)

        with patch("profile.passkeys.timezone.now", return_value=start), patch(
            "profile.passkeys._maybe_cleanup_rate_limits"
        ):
            self.assertTrue(_consume_rate_limit("passkey-window", "same", 1))
        with patch(
            "profile.passkeys.timezone.now",
            return_value=start + timedelta(minutes=10),
        ), patch("profile.passkeys._maybe_cleanup_rate_limits"):
            self.assertFalse(_consume_rate_limit("passkey-window", "same", 1))
        with patch(
            "profile.passkeys.timezone.now",
            return_value=start + timedelta(minutes=10),
        ), patch("profile.passkeys._maybe_cleanup_rate_limits"):
            self.assertTrue(
                _consume_rate_limit(
                    "custom-window",
                    "same",
                    1,
                    window=timedelta(minutes=10),
                )
            )

    def test_missing_or_empty_remote_addr_returns_429_without_a_pdf(self):
        views = (
            (TerapiasAmbulatoriasView, _terapias()),
            (EscolaridadEspecialView, _escolaridad()),
        )
        for view, payload in views:
            request = self.factory.post(reverse(TERAPIAS_URL), payload)
            request.META.pop("REMOTE_ADDR", None)
            response = view.as_view()(request)
            self.assertEqual(response.status_code, 429)
            self.assertFalse(_body(response).startswith(b"%PDF"))

            blank = self.factory.post(reverse(ESCOLARIDAD_URL), payload)
            blank.META["REMOTE_ADDR"] = "   "
            blank_response = view.as_view()(blank)
            self.assertEqual(blank_response.status_code, 429)
            self.assertFalse(_body(blank_response).startswith(b"%PDF"))

        empty = self._post(TERAPIAS_URL, _terapias(), REMOTE_ADDR="")
        self.assertEqual(empty.status_code, 429)
        self.assertFalse(_body(empty).startswith(b"%PDF"))

    def test_limiter_errors_deny_once_without_a_pdf(self):
        with patch(
            "prescriptions.views._consume_rate_limit", side_effect=RuntimeError("down")
        ) as consume, patch(
            "prescriptions.views.fill_prescription_pdf", return_value=b"%PDF-1.4"
        ) as fill_pdf:
            response = self._post(
                TERAPIAS_URL, _terapias(), REMOTE_ADDR="198.51.100.40"
            )
        self.assertEqual(response.status_code, 429)
        self.assertFalse(_body(response).startswith(b"%PDF"))
        self.assertEqual(consume.call_count, 1)
        self.assertEqual(fill_pdf.call_count, 0)

        with patch.object(
            __import__("profile.models", fromlist=["PasskeyRateLimit"]).PasskeyRateLimit.objects,
            "select_for_update",
            side_effect=DatabaseError("database unavailable"),
        ), patch("profile.passkeys._maybe_cleanup_rate_limits"), patch(
            "prescriptions.views.fill_prescription_pdf", return_value=b"%PDF-1.4"
        ) as fill_pdf:
            denied = self._post(
                ESCOLARIDAD_URL, _escolaridad(), REMOTE_ADDR="198.51.100.41"
            )
        self.assertEqual(denied.status_code, 429)
        self.assertFalse(_body(denied).startswith(b"%PDF"))
        self.assertEqual(fill_pdf.call_count, 0)

    def test_form_posts_do_not_log_submitted_values(self):
        with self.assertNoLogs("prescriptions", level="DEBUG"):
            valid = self._post(
                TERAPIAS_URL, _terapias(), REMOTE_ADDR="198.51.100.50"
            )
            invalid = self._post(
                TERAPIAS_URL,
                _terapias(dni="30123'456"),
                REMOTE_ADDR="198.51.100.50",
            )
        self.assertEqual(valid.status_code, 200)
        self.assertEqual(invalid.status_code, 400)
