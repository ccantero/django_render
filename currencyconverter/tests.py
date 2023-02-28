from django.test import RequestFactory, TestCase
from django.test import SimpleTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from rest_framework import status

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from currencyconverter.models import Currency, ExchangeRate
from currencyconverter.serializers import CurrencySerializer, CurrencyDetailSerializer

# Create your tests here.
class PublicTestViews(TestCase):
    def test_calculadora_uva_no_authentication(self):
        self.client = APIClient()
        res = self.client.get(
            reverse('currencyconverter:calculadora')
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
    
    def test_calculadora_uva_no_authentication_with_parameters(self):
        #self.client = APIClient()
        res = self.client.get(
            reverse('currencyconverter:calculadora'),
            {
                'cuota':381.16,
                'saldo':63698.11
                }
        )
        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_get_currencies_no_authentication(self):
        self.client = APIClient()
        res = self.client.get('/currencyconverter/json/currencies/')

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
    
    def test_post_currency_no_authentication(self):
        self.client = APIClient()
        res = self.client.post('/currencyconverter/json/currencies/',
        {
            'key': 'EUR',
            'description': 'EURO Currency'
        }
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_delete_currency_no_authentication(self):
        payload = {
            'key': 'EUR',
            'description': 'EURO Currency'
        }
        currency = Currency.objects.create(**payload)
        self.client = APIClient()
        res = self.client.delete(
            '/currencyconverter/json/currencies/', 
            args=[currency.key]
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_put_currency_no_authentication(self):
        payload = {
            'key': 'EUR',
            'description': 'EURO Currency'
        }
        currency = Currency.objects.create(**payload)
        
        new_payload = {
            'description': 'EURO Currency - New Description'
        }

        self.client = APIClient()
        res = self.client.put(
            '/currencyconverter/json/currencies/', 
            **new_payload
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_patch_currency_no_authentication(self):
        payload = {
            'key': 'EUR',
            'description': 'EURO Currency'
        }
        currency = Currency.objects.create(**payload)
        
        new_payload = {
            'description': 'EURO Currency - New Description'
        }

        self.client = APIClient()
        res = self.client.patch(
            '/currencyconverter/json/currencies/', 
            **new_payload
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_get_html_exchangerates_no_authentication(self):
        client = APIClient()
        res = client.get('/currencyconverter/exchangerates/')

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_get_exchangerates_no_authentication(self):
        client = APIClient()
        res = client.get('/currencyconverter/json/exchangerates/')

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_post_exchangerates_no_authentication(self):
        payload_1 = {
            'key': 'EUR',
            'description': 'EURO Currency'
        }

        payload_2 = {
            'key': 'ARS',
            'description': 'EURO Currency'
        }

        currency_1 = Currency.objects.create(**payload_1)
        currency_2 = Currency.objects.create(**payload_2)

        payload_3 = {
            'key': 'ARS_EUR',
            'numerator': currency_1.key,
            'denominator': currency_2.key
        }


        self.client = APIClient()
        res = self.client.post('/currencyconverter/json/exchangerates/',
            payload_3,
            format='json'
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

from django.contrib.auth import get_user_model

def create_user(**params):
    """Create and return a new user"""
    return get_user_model().objects.create_user(**params)

class PrivateTestViews(TestCase):
    def setUp(self):
        user_details = {
            'name': 'Test Name',
            'email': 'test@example.com',
            'password': 'test-user-password123'
        }
        self.user = create_user(**user_details)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_get_currency_authenticated(self):
        """ It is supposed that is being tested 
        already by test_get_currencies_no_authentication """
        Currency.objects.create(key='EUR')
        Currency.objects.create(key='ARS')

        url = reverse('currencyconverter:currency-list')

        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        factory = APIRequestFactory()
        request = factory.get('/')

        serializer_context = {
            'request': Request(request),
        }

        currencies = Currency.objects.all().order_by("-key")
        serializer = CurrencySerializer(currencies, many=True, context=serializer_context)
        self.assertEqual(res.data['results'], serializer.data)
        
    def test_post_currency_authenticated(self):
        res = self.client.post(
            '/currencyconverter/json/currencies/',
            {
                'key': 'EUR',
                'description': 'EURO Currency'
            }
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

        res = self.client.get('/currencyconverter/json/currencies/')
        self.assertEqual(len(res.data), 4)

        factory = APIRequestFactory()
        request = factory.get('/')

        serializer_context = {
            'request': Request(request),
        }

        currencies = Currency.objects.all().order_by('key')
        serializer = CurrencySerializer(currencies, context=serializer_context, many=True)

        self.assertEqual(res.data['results'], serializer.data)

        res = self.client.get(
            '/currencyconverter/json/currencies/EUR/',
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        serializer = CurrencyDetailSerializer(currencies[0], context=serializer_context)
        self.assertEqual(res.data, serializer.data)

    def test_calculadora_uva_authenticated(self):
        res = self.client.get(
            reverse('currencyconverter:calculadora')
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_put_currency_notallowed(self):
        res = self.client.post(
            '/currencyconverter/json/currencies/',
            {
                'key': 'EUR',
                'description': 'EURO Currency'
            }
        )

        res = self.client.put(
            '/currencyconverter/json/currencies/EUR/',
            {
                'key': 'EUR',
                'description': 'EURO Currency - New description'
            }
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_patch_currency_notallowed(self):
        res = self.client.post(
            '/currencyconverter/json/currencies/',
            {
                'key': 'EUR',
                'description': 'EURO Currency'
            }
        )

        res = self.client.patch(
            '/currencyconverter/json/currencies/EUR/',
            {
                'description': 'EURO Currency - New description'
            }
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_currency_notallowed(self):
        res = self.client.post(
            '/currencyconverter/json/currencies/',
            {
                'key': 'EUR',
                'description': 'EURO Currency'
            }
        )

        res = self.client.delete(
            '/currencyconverter/json/currencies/EUR/'
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
    
    def test_duplicate_post_currency_with_same_key_not_allowed(self):
        res = self.client.post(
            '/currencyconverter/json/currencies/',
            {
                'key': 'EUR',
                'description': 'EURO Currency'
            }
        )

        res = self.client.post(
            '/currencyconverter/json/currencies/',
            {
                'key': 'EUR',
                'description': 'EURO Currency'
            }
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_exchangerate(self):
        payload_1 = {
            'key': 'EUR',
            'description': 'EURO Currency'
        }

        payload_2 = {
            'key': 'ARS',
            'description': 'EURO Currency'
        }

        currency_1 = Currency.objects.create(**payload_1)
        currency_2 = Currency.objects.create(**payload_2)
        

        payload_3 = {
            'key': 'ARS_EUR',
            'numerator': currency_1.key,
            'denominator': currency_2.key
        }

        res = self.client.post('/currencyconverter/json/exchangerates/',
            payload_3,
            format='json'
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_patch_exchangerate_notallowed(self):
        payload_1 = {
            'key': 'EUR',
            'description': 'EURO Currency'
        }

        payload_2 = {
            'key': 'ARS',
            'description': 'ARS Currency'
        }

        currency_1 = Currency.objects.create(**payload_1)
        currency_2 = Currency.objects.create(**payload_2)

        payload_3 = {
            'key': 'ARS_EUR',
            'numerator': currency_1,
            'denominator': currency_2
        }

        exchange_rate = ExchangeRate.objects.create(**payload_3)

        res = self.client.patch('/currencyconverter/json/exchangerates/' + 
                                exchange_rate.key + '/',
            {'numerator': currency_2.key},
            format='json'
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
    
    def test_put_exchangerate_notallowed(self):
        payload_1 = {
            'key': 'EUR',
            'description': 'EURO Currency'
        }

        payload_2 = {
            'key': 'ARS',
            'description': 'ARS Currency'
        }

        currency_1 = Currency.objects.create(**payload_1)
        currency_2 = Currency.objects.create(**payload_2)

        payload_3 = {
            'key': 'ARS_EUR',
            'numerator': currency_1,
            'denominator': currency_2
        }

        exchange_rate = ExchangeRate.objects.create(**payload_3)

        res = self.client.put('/currencyconverter/json/exchangerates/' + 
                                exchange_rate.key + '/',
            {'numerator': currency_2.key},
            format='json'
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def test_delete_exchangerate_notallowed(self):
        payload_1 = {
            'key': 'EUR',
            'description': 'EURO Currency'
        }

        payload_2 = {
            'key': 'ARS',
            'description': 'ARS Currency'
        }

        currency_1 = Currency.objects.create(**payload_1)
        currency_2 = Currency.objects.create(**payload_2)

        payload_3 = {
            'key': 'ARS_EUR',
            'numerator': currency_1,
            'denominator': currency_2
        }

        exchange_rate = ExchangeRate.objects.create(**payload_3)

        res = self.client.delete('/currencyconverter/json/exchangerates/' + 
                                exchange_rate.key + '/'
        )

        self.assertNotEqual(res.reason_phrase, 'Not Found')
        self.assertEqual(res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)