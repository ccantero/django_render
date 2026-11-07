from datetime import date
from io import BytesIO

from django.test import SimpleTestCase, Client
from django.urls import reverse
from pypdf import PdfReader

from .pdf import DEFAULT_PDF_TEMPLATE, fill_prescription_pdf


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
        self.assertIn("06/11/2026", text)
        self.assertIn("Ene - 2027 / Dic - 2027", text)


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
