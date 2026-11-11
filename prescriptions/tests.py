from datetime import date
from io import BytesIO

from django.test import SimpleTestCase, Client
from django.urls import reverse
from pypdf import PdfReader

from .forms import TerapiasAmbulatoriasForm
from .pdf import (
    DEFAULT_PDF_TEMPLATE,
    FIELD_BOXES,
    PrescriptionLayoutError,
    fill_prescription_pdf,
    plan_overlay,
)


SAMPLE = {
    "fecha": date(2026, 11, 6),
    "nombre_apellido": "Juan Pérez",
    "dni": "30123456",
    "edad": 42,
    "diagnostico": "Parálisis cerebral. Requiere rehabilitación motora integral.",
    "prestacion": "Kinesiología y terapia ocupacional ambulatoria.",
    "frecuencia_semanal": "2 veces por semana",
    "periodo_desde": date(2027, 1, 1),
    "periodo_hasta": date(2027, 12, 1),
}

VISUAL_SAMPLE = {
    "fecha": date(2026, 11, 27),
    "nombre_apellido": "John Wick",
    "dni": "12345678",
    "edad": 10,
    "diagnostico": "Autismo en la niñez",
    "prestacion": "Fonoaudiología",
    "frecuencia_semanal": "2",
    "periodo_desde": date(2027, 1, 1),
    "periodo_hasta": date(2027, 12, 1),
}


def _overlay_text_positions(pdf_bytes: bytes) -> list[tuple[float, float, str]]:
    """Return (x, y, text) for non-empty overlay strings."""
    reader = PdfReader(BytesIO(pdf_bytes))
    page = reader.pages[0]
    parts: list[tuple[float, float, str]] = []

    def visitor(text, cm, tm, fontDict, fontSize):
        if text and text.strip():
            parts.append((float(tm[4]), float(tm[5]), text.strip()))

    page.extract_text(visitor_text=visitor)
    return parts


def _positions_for(pdf_bytes: bytes, needle: str) -> list[tuple[float, float, str]]:
    return [(x, y, t) for x, y, t in _overlay_text_positions(pdf_bytes) if needle in t]


class PdfGenerationTests(SimpleTestCase):
    def test_template_bundled_with_app(self):
        self.assertTrue(DEFAULT_PDF_TEMPLATE.is_file())

    def test_fill_returns_valid_pdf(self):
        pdf_bytes = fill_prescription_pdf(SAMPLE)
        reader = PdfReader(BytesIO(pdf_bytes))
        self.assertEqual(len(reader.pages), 1)
        text = reader.pages[0].extract_text()
        self.assertIn("Juan Pérez", text)
        self.assertIn("30123456", text)
        self.assertIn("06", text)
        self.assertIn("11", text)
        self.assertIn("2026", text)
        self.assertIn("Enero", text)
        self.assertIn("Diciembre", text)
        self.assertIn("2027", text)

    def test_preserves_original_template_labels(self):
        pdf_bytes = fill_prescription_pdf(SAMPLE)
        text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
        self.assertIn("Periodo: desde:", text)
        self.assertIn("hasta:", text)
        self.assertIn("Firma y sello del medico tratante.", text)
        self.assertIn("Frecuencia semanales:", text)
        self.assertNotIn("Ene - 2027 / Dic - 2027", text)

    def test_accented_spanish_text_is_preserved(self):
        pdf_bytes = fill_prescription_pdf(VISUAL_SAMPLE)
        text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
        self.assertIn("Autismo en la niñez", text)
        self.assertIn("Fonoaudiología", text)

    def test_short_visual_sample_places_each_field(self):
        pdf_bytes = fill_prescription_pdf(VISUAL_SAMPLE)
        plan = plan_overlay(VISUAL_SAMPLE)
        for segment in plan.segments:
            box = FIELD_BOXES[segment.field]
            self.assertGreaterEqual(segment.x, box.x - 0.5)
            self.assertLessEqual(segment.x + segment.width, box.x + box.width + 0.5)
            self.assertAlmostEqual(segment.y, box.y_for_line(segment.line_index), delta=0.6)

        text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
        for value in (
            "John Wick",
            "12345678",
            "10",
            "Autismo en la niñez",
            "Fonoaudiología",
            "Enero",
            "Diciembre",
        ):
            self.assertIn(value, text)

        day_hits = _positions_for(pdf_bytes, "27")
        self.assertTrue(any(abs(y - FIELD_BOXES["fecha_day"].y) < 1.0 for _, y, _ in day_hits))

    def test_long_name_and_frequency_fit_or_reject(self):
        long_ok = {
            **SAMPLE,
            "nombre_apellido": "María Fernanda González de la Torre",
            "frecuencia_semanal": "3 veces por semana, 45 minutos",
        }
        pdf_bytes = fill_prescription_pdf(long_ok)
        text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text()
        self.assertIn("María Fernanda González de la Torre", text)
        self.assertIn("3 veces por semana, 45 minutos", text)

        too_long = {
            **SAMPLE,
            "nombre_apellido": "W" * 55,
        }
        with self.assertRaises(PrescriptionLayoutError) as ctx:
            fill_prescription_pdf(too_long)
        self.assertEqual(ctx.exception.field, "nombre_apellido")

    def test_multiline_diagnosis_and_prestacion_wrap(self):
        data = {
            **SAMPLE,
            "diagnostico": (
                "Trastorno del espectro autista con compromiso del lenguaje "
                "expresivo y necesidad de apoyo en habilidades sociales y "
                "comunicación funcional diaria"
            ),
            "prestacion": (
                "Fonoaudiología ambulatoria con abordaje interdisciplinario "
                "y terapia ocupacional complementaria"
            ),
        }
        plan = plan_overlay(data)
        diag_lines = [s for s in plan.segments if s.field == "diagnostico"]
        prest_lines = [s for s in plan.segments if s.field == "prestacion"]
        self.assertGreaterEqual(len(diag_lines), 2)
        self.assertLessEqual(len(diag_lines), 3)
        self.assertGreaterEqual(len(prest_lines), 2)
        self.assertLessEqual(len(prest_lines), 2)
        pdf_bytes = fill_prescription_pdf(data)
        text = PdfReader(BytesIO(pdf_bytes)).pages[0].extract_text().replace("\n", " ")
        for word in data["diagnostico"].split():
            self.assertIn(word, text)
        for word in data["prestacion"].split():
            self.assertIn(word, text)

    def test_overflowing_diagnosis_is_rejected_without_truncation(self):
        data = {
            **SAMPLE,
            "diagnostico": " ".join(["diagnósticoextraordinariamentelargo"] * 40),
        }
        with self.assertRaises(PrescriptionLayoutError) as ctx:
            fill_prescription_pdf(data)
        self.assertEqual(ctx.exception.field, "diagnostico")
        self.assertNotIn("diagnósticoextraordinariamentelargo"[:20], str(ctx.exception).split()[0:1] or "")

    def test_no_silent_character_truncation_helpers(self):
        """plan_overlay must not slice submitted clinical strings away."""
        name = "W" * 55
        with self.assertRaises(PrescriptionLayoutError) as ctx:
            plan_overlay({**SAMPLE, "nombre_apellido": name})
        self.assertEqual(ctx.exception.field, "nombre_apellido")
        self.assertIn("legible", ctx.exception.message.lower())

    def test_period_uses_separate_desde_hasta_month_year_slots(self):
        plan = plan_overlay(VISUAL_SAMPLE)
        fields = {s.field for s in plan.segments}
        self.assertIn("periodo_desde_month", fields)
        self.assertIn("periodo_desde_year", fields)
        self.assertIn("periodo_hasta_month", fields)
        self.assertIn("periodo_hasta_year", fields)
        self.assertNotIn("periodo", fields)
        desde_month = next(s for s in plan.segments if s.field == "periodo_desde_month")
        hasta_month = next(s for s in plan.segments if s.field == "periodo_hasta_month")
        self.assertEqual(desde_month.text, "Enero")
        self.assertEqual(hasta_month.text, "Diciembre")
        self.assertLess(desde_month.x, hasta_month.x)

    def test_fecha_parts_do_not_span_date_separators(self):
        from .pdf import FONT_SIZE

        plan = plan_overlay(VISUAL_SAMPLE)
        day = next(s for s in plan.segments if s.field == "fecha_day")
        month = next(s for s in plan.segments if s.field == "fecha_month")
        year = next(s for s in plan.segments if s.field == "fecha_year")
        self.assertEqual(day.text, "27")
        self.assertEqual(month.text, "11")
        self.assertEqual(year.text, "2026")
        self.assertEqual(day.font_size, FONT_SIZE)
        self.assertEqual(month.font_size, FONT_SIZE)
        self.assertEqual(year.font_size, FONT_SIZE)
        self.assertLess(day.x + day.width, FIELD_BOXES["fecha_month"].x)
        self.assertLess(month.x + month.width, FIELD_BOXES["fecha_year"].x)
        self.assertLess(
            day.x + day.width,
            FIELD_BOXES["fecha_day"].x + FIELD_BOXES["fecha_day"].width + 0.5,
        )


class FormValidationTests(SimpleTestCase):
    def _valid_post(self, **overrides):
        payload = {
            "fecha": "2026-11-27",
            "nombre_apellido": "John Wick",
            "dni": "12345678",
            "edad": "10",
            "diagnostico": "Autismo en la niñez",
            "prestacion": "Fonoaudiología",
            "frecuencia_semanal": "2",
            "periodo_desde": "2027-01",
            "periodo_hasta": "2027-12",
        }
        payload.update(overrides)
        return payload

    def test_valid_form(self):
        form = TerapiasAmbulatoriasForm(self._valid_post())
        self.assertTrue(form.is_valid(), form.errors)

    def test_malformed_month_becomes_validation_error(self):
        for bad in ("2027-13", "abcd-01", "2027", "2027-00", "not-a-month"):
            form = TerapiasAmbulatoriasForm(self._valid_post(periodo_desde=bad))
            self.assertFalse(form.is_valid(), bad)
            self.assertIn("periodo_desde", form.errors)

    def test_out_of_range_month_hasta(self):
        form = TerapiasAmbulatoriasForm(self._valid_post(periodo_hasta="2027-99"))
        self.assertFalse(form.is_valid())
        self.assertIn("periodo_hasta", form.errors)

    def test_capacity_overflow_returns_field_error(self):
        form = TerapiasAmbulatoriasForm(
            self._valid_post(nombre_apellido="W" * 55)
        )
        self.assertFalse(form.is_valid())
        self.assertIn("nombre_apellido", form.errors)
        self.assertIn("legible", form.errors["nombre_apellido"][0].lower())

    def test_invalid_capacity_preserves_entered_values_on_view(self):
        client = Client()
        wide_name = "W" * 55
        response = client.post(
            reverse("prescriptions:terapias_ambulatorias"),
            self._valid_post(nombre_apellido=wide_name),
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "nombre_apellido", status_code=400)
        self.assertNotEqual(response.get("Content-Type", ""), "application/pdf")
        self.assertContains(response, wide_name[:40], status_code=400)


class FormViewTests(SimpleTestCase):
    def test_get_form(self):
        client = Client()
        response = client.get(reverse("prescriptions:terapias_ambulatorias"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Descargar PDF")

    def test_post_downloads_pdf(self):
        client = Client()
        response = client.post(
            reverse("prescriptions:terapias_ambulatorias"),
            {
                "fecha": "2026-11-06",
                "nombre_apellido": "Juan Pérez",
                "dni": "30123456",
                "edad": "42",
                "diagnostico": "Diagnóstico de prueba",
                "prestacion": "Kinesiología",
                "frecuencia_semanal": "2 veces por semana",
                "periodo_desde": "2027-01",
                "periodo_hasta": "2027-12",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("prescripcion_terapias_30123456.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))
        text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
        self.assertIn("Juan Pérez", text)
        self.assertIn("Enero", text)
        self.assertIn("Diciembre", text)
