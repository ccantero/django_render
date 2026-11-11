"""Host-project smoke tests for the integrated prescriptions app.

Agent-Signature: Cursor-Auto
"""

from django.test import SimpleTestCase, Client
from django.urls import reverse


class PrescriptionsIntegrationTests(SimpleTestCase):
    def test_terapias_ambulatorias_route_is_mounted(self):
        client = Client()
        response = client.get(reverse("prescriptions:terapias_ambulatorias"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Descargar PDF")

    def test_prescriptions_app_is_installed(self):
        from django.apps import apps

        self.assertTrue(apps.is_installed("prescriptions"))

    def test_main_nav_links_to_prescripciones_medicas(self):
        client = Client()
        prescriptions_url = reverse("prescriptions:terapias_ambulatorias")
        home = client.get(reverse("home"))
        about = client.get(reverse("aboutMe"))

        self.assertEqual(home.status_code, 200)
        self.assertEqual(about.status_code, 200)
        self.assertEqual(prescriptions_url, "/terapias-ambulatorias/")

        for page in (home, about):
            self.assertContains(page, "id='navbar'")
            self.assertContains(page, "Prescripciones médicas")
            self.assertContains(page, f'href="{prescriptions_url}"')
            self.assertContains(page, reverse("currencyconverter:cotizaciones"))
            self.assertContains(page, reverse("currencyconverter:calculadora"))
            self.assertContains(page, reverse("aboutMe"))
            self.assertContains(page, reverse("dashboard_demo"))
