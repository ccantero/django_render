"""Host-project smoke tests for the integrated prescriptions app.

Agent-Signature: Cursor-Auto
"""

from django.test import SimpleTestCase, Client
from django.urls import reverse


class PrescriptionsIntegrationTests(SimpleTestCase):
    def test_galeno_hub_route_is_mounted(self):
        client = Client()
        hub_url = reverse("prescriptions:galeno_hub")
        self.assertEqual(hub_url, "/prescripciones-galeno/")
        response = client.get(hub_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Prescripciones Galeno")
        self.assertContains(response, "Terapias ambulatorias")
        self.assertContains(response, "Escolaridad especial")
        self.assertContains(response, reverse("prescriptions:terapias_ambulatorias"))
        self.assertContains(response, reverse("prescriptions:escolaridad_especial"))

    def test_terapias_ambulatorias_route_is_mounted(self):
        client = Client()
        response = client.get(reverse("prescriptions:terapias_ambulatorias"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Descargar PDF")

    def test_prescriptions_app_is_installed(self):
        from django.apps import apps

        self.assertTrue(apps.is_installed("prescriptions"))

    def test_main_nav_links_only_to_shared_galeno_hub(self):
        client = Client()
        hub_url = reverse("prescriptions:galeno_hub")
        terapias_url = reverse("prescriptions:terapias_ambulatorias")
        escolaridad_url = reverse("prescriptions:escolaridad_especial")
        home = client.get(reverse("home"))
        about = client.get(reverse("aboutMe"))

        self.assertEqual(home.status_code, 200)
        self.assertEqual(about.status_code, 200)
        self.assertEqual(hub_url, "/prescripciones-galeno/")

        for page in (home, about):
            html = page.content.decode()
            self.assertContains(page, "id='navbar'")
            self.assertContains(page, "Prescripciones Galeno")
            self.assertContains(page, f'href="{hub_url}"')
            self.assertEqual(html.count(f'href="{hub_url}"'), 1)
            self.assertNotIn(f'href="{terapias_url}"', html)
            self.assertNotIn(f'href="{escolaridad_url}"', html)
            self.assertContains(page, reverse("currencyconverter:cotizaciones"))
            self.assertContains(page, reverse("currencyconverter:calculadora"))
            self.assertContains(page, reverse("aboutMe"))
            self.assertContains(page, reverse("dashboard_demo"))

    def test_prescription_form_includes_shared_navigation(self):
        client = Client()
        hub_url = reverse("prescriptions:galeno_hub")
        response = client.get(reverse("prescriptions:terapias_ambulatorias"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "id='navbar'")
        self.assertContains(response, "Prescripciones Galeno")
        self.assertContains(response, f'href="{hub_url}"')
        self.assertContains(response, reverse("home"))
        self.assertContains(response, reverse("currencyconverter:cotizaciones"))
        self.assertContains(response, reverse("currencyconverter:calculadora"))
        self.assertContains(response, reverse("aboutMe"))
        self.assertContains(response, reverse("dashboard_demo"))
        self.assertContains(response, "Descargar PDF")
        self.assertContains(response, "csrfmiddlewaretoken")
        self.assertContains(response, "prescriptions-page")
        # Standalone document shell must not be duplicated under the shared layout.
        self.assertEqual(response.content.decode().lower().count("<!doctype html>"), 1)

    def test_escolaridad_especial_route_is_mounted(self):
        client = Client()
        url = reverse("prescriptions:escolaridad_especial")
        self.assertEqual(url, "/escolaridad-especial/")
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escolaridad especial")
        self.assertContains(response, "Descargar PDF")
        self.assertContains(response, "id='navbar'")
        self.assertContains(response, reverse("prescriptions:galeno_hub"))
