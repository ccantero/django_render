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
