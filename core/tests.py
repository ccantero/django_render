from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from decimal import Decimal
from types import SimpleNamespace
import json
from unittest.mock import patch

from core.dashboard_read_model import _build_bot_status, _build_fee_summary

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
        mock_get_dashboard_context.return_value.context = self.empty_dashboard_context()
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trading Dashboard')
        mock_get_dashboard_context.assert_called_once()

    @patch('core.views.get_dashboard_context')
    def test_dashboard_loads_when_bot_tables_are_empty(self, mock_get_dashboard_context):
        mock_get_dashboard_context.return_value.context = self.empty_dashboard_context()
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No data yet.')
        self.assertContains(response, 'Portfolio Summary')

    @patch('core.views.get_dashboard_context')
    def test_dashboard_loads_with_sample_read_model_data(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        context.update({
            'bot_status': {
                'row': SimpleNamespace(),
                'status': 'ok',
                'probe_message': 'healthy',
                'created_at': timezone.now(),
                'read_only': True,
                'is_stale': False,
                'stale_after_minutes': 15,
            },
            'portfolio_summary': {
                'rows_count': 2,
                'total_estimated_value': Decimal('25.50'),
                'material_positions_count': 1,
                'dust_positions_count': 1,
            },
            'fee_summary': {
                'asset_count': 1,
                'fill_count': 2,
                'rows': [{'asset': 'USDT', 'total': Decimal('0.25'), 'fill_count': 2}],
            },
            'latest_trade': {
                'row': SimpleNamespace(
                    side='BUY',
                    symbol='BTCUSDT',
                    status='FILLED',
                    executed_base_qty=Decimal('0.001'),
                    executed_at=timezone.now(),
                ),
                'gross_quote': Decimal('20.00'),
                'net_quote': Decimal('20.00'),
            },
            'reconciliation': {
                'status': 'warning',
                'warning_count': 1,
                'warnings': [{
                    'symbol': 'BTCUSDT',
                    'portfolio_quantity': Decimal('0.002'),
                    'open_lot_quantity': Decimal('0.001'),
                    'diff': Decimal('0.001'),
                }],
                'checked_count': 1,
                'tolerance': Decimal('0.00000001'),
            },
        })
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BTCUSDT')
        self.assertContains(response, '1 warning')
        self.assertContains(response, 'Total Fees')
        self.assertContains(response, '0.25000000')

    def test_demo_dashboard_is_public_and_read_only(self):
        response = self.client.get(reverse('dashboard_demo'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public demo')
        self.assertContains(response, 'Total Fees')
        self.assertNotContains(response, 'Control seguro')
        self.assertNotContains(response, 'Stop')
        self.assertNotContains(response, 'Resume')

    def test_stale_healthcheck_detection(self):
        stale_row = SimpleNamespace(
            status='ok',
            probe_message='old heartbeat',
            created_at=timezone.now() - timezone.timedelta(minutes=16),
            details={'read_only': True},
        )
        with patch('core.dashboard_read_model.BotHealthcheck.objects') as manager:
            manager.order_by.return_value.first.return_value = stale_row

            status = _build_bot_status()

        self.assertTrue(status['is_stale'])
        self.assertEqual(status['read_only'], True)

    def test_fee_summary_uses_trade_operations_fee_fields(self):
        class FakeTradeOperationQuery:
            def __init__(self):
                self.calls = []

            def filter(self, **kwargs):
                self.calls.append(('filter', kwargs))
                return self

            def values(self, *fields):
                self.calls.append(('values', fields))
                return self

            def annotate(self, **kwargs):
                self.calls.append(('annotate', tuple(kwargs)))
                return self

            def order_by(self, *fields):
                self.calls.append(('order_by', fields))
                return [
                    {'fee_asset': 'BNB', 'total': Decimal('0.0018'), 'fill_count': 2},
                    {'fee_asset': 'USDT', 'total': Decimal('3.42'), 'fill_count': 5},
                ]

        query = FakeTradeOperationQuery()
        with patch('core.dashboard_read_model.TradeOperation.objects', query):
            summary = _build_fee_summary()

        self.assertEqual(summary['asset_count'], 2)
        self.assertEqual(summary['fill_count'], 7)
        self.assertEqual(summary['rows'][0]['asset'], 'BNB')
        self.assertIn(('filter', {'fee_amount__isnull': False}), query.calls)
        self.assertIn(('values', ('fee_asset',)), query.calls)
        self.assertIn(('order_by', ('fee_asset',)), query.calls)

    def empty_dashboard_context(self):
        return {
            'bot_control': None,
            'bot_status': {
                'row': None,
                'status': None,
                'probe_message': None,
                'created_at': None,
                'read_only': None,
                'is_stale': False,
                'stale_after_minutes': 15,
            },
            'portfolio_summary': {
                'rows_count': 0,
                'total_estimated_value': Decimal('0'),
                'material_positions_count': 0,
                'dust_positions_count': 0,
            },
            'fee_summary': {
                'asset_count': 0,
                'fill_count': 0,
                'rows': [],
            },
            'latest_trade': {'row': None, 'gross_quote': None, 'net_quote': None},
            'reconciliation': {
                'status': 'ok',
                'warning_count': 0,
                'warnings': [],
                'checked_count': 0,
                'tolerance': Decimal('0.00000001'),
            },
            'data_error': None,
            'is_demo': False,
        }
