from django.test import TestCase
from django.test import SimpleTestCase
from rest_framework.test import APIClient


# Create your tests here.
class TestViews(SimpleTestCase):
    def test_calculadora_uva_no_authentication(self):
        client = APIClient()
        res = client.get('currencyconverter/calculadora_uva/')

        self.assertEqual(res.status_code, 404)