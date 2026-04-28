from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
import json
from unittest.mock import patch

class TelegramWebhookTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.webhook_url = reverse('listener')  # Assumes 'listener' is in core.urls

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.TUTORIAL_BOT_TOKEN', 'test-token')
    @patch('core.views.send_message')
    def test_listener_post_start(self, mock_send_message):
        data = {
            "message": {
                "text": "/start",
                "message_id": 123,
                "chat": {"id": 1},
                "from": {"username": "testuser"}
            }
        }
        response = self.client.post(
            self.webhook_url,
            data=json.dumps(data),
            content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-webhook-token'
        )
        self.assertEqual(response.status_code, 200)
        mock_send_message.assert_called()


class DashboardEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.dashboard_url = reverse('dashboard')
        self.user = get_user_model().objects.create_user(
            email='dashboard@example.com',
            password='TestPassword123',
            name='Dashboard User',
        )

    def test_dashboard_requires_authentication(self):
        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    @patch('core.views.get_dashboard_context')
    def test_dashboard_authenticated_user_gets_dashboard(self, mock_get_dashboard_context):
        mock_get_dashboard_context.return_value.context = {
            'bot_control': None,
            'health': {
                'row': None,
                'state': 'unknown',
                'age': None,
                'is_stale': False,
                'stale_minutes': None,
            },
            'summary': {
                'portfolio_positions_count': 0,
                'open_lot_symbols_count': 0,
                'total_value': 0,
                'drift_alerts_count': 0,
                'dust_alerts_count': 0,
            },
            'positions': [],
            'trades': [],
            'alerts': [],
            'thresholds': {},
            'data_error': None,
        }
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trading Dashboard')
        mock_get_dashboard_context.assert_called_once()
