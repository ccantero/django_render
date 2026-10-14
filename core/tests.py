Warning: truncated output (original token count: 77371)
Total output lines: 6860

from django.test import TestCase, TransactionTestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from django.db import DatabaseError, connection
from decimal import Decimal
from datetime import timezone as datetime_timezone, timedelta
from types import SimpleNamespace
import inspect
import json
import logging
import os
import requests
from pathlib import Path
from unittest.mock import patch

from dashboard.dashboard_read_model import (
    _build_bot_status,
    _build_fee_summary,
    _build_performance_kpis,
    _build_position_exit_status,
    _build_inventory_scope_summary,
    _build_latest_trade_from_recent_operations,
    _build_quote_fee_summary,
    _build_valuation_consistency,
    _calculate_performance_kpis,
    _dashboard_profile_enabled,
    _homepage_sell_diagnostics_enabled,
    _ensure_dashboard_profile_console_logging,
    _latest_sell_events_by_symbol,
    _latest_sell_events_for_exit_status,
    _build_buy_status_summary,
    _build_churn_summary,
    _position_exit_suggested_action,
    get_dashboard_context,
    get_exit_status_context,
    get_churn_context,
)
from dashboard.dust_read_model import (
    _active_operational_issues,
    _build_summary,
    _build_homepage_summary,
    _clean_filters,
    _dashboard_queryset,
    _filtered_group_detections,
    _format_payload,
    _operator_guidance,
    _filter_by_review_status,
    _informational_residual_summary,
    _with_correction_state,
    _with_review_state,
    _reviews_for_rows,
    get_dust_dashboard_context,
    update_dust_signal_review,
)
from dashboard.forms import ManualCorrectionRequestForm
from dashboard.services.operational_kpis import (
    OperationalKpiFilters,
    _calculate_operational_kpis,
)
from dashboard.services.telegram_buy_status_formatter import (
    build_buy_status_exposure,
    build_cooldown_diagnostics,
)
from core.models import DustSignalReview, ManualCorrection
from core.trading_models import DustDetection, LotClosure, PositionLot, TradeOperation
from dashboard.views import _manual_correction_quantity
from core.telegram_diagnostics import format_dust_drift_alert


class HealthEndpointTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.health_url = reverse('health')

    def test_health_endpoint_is_public_and_returns_ok(self):
        response = self.client.get(self.health_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(response.json(), {'status': 'ok'})
        self.assertNotContains(response, 'Disk Usage')

    def test_health_endpoint_is_get_only(self):
        response = self.client.post(self.health_url)

        self.assertEqual(response.status_code, 405)


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

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.views.TelegramMessage.objects.create', side_effect=DatabaseError('database unavailable'))
    @patch('core.views.TelegramMessage.objects.filter')
    @patch('core.views.diagnostic_response', side_effect=AssertionError('help must not dispatch diagnostics'))
    def test_help_continues_after_audit_persistence_failure_without_diagnostics(
        self,
        mock_diagnostic_response,
        mock_message_filter,
        mock_message_create,
        mock_send_message,
    ):
        payload = {
            'update_id': 42,
            'message': {
                'text': '/help',
                'message_id': 123,
                'chat': {'id': 1},
                'from': {'id': 2, 'username': 'operator'},
            },
        }

        mock_message_filter.return_value.exists.return_value = False
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='1'):
            response = self.client.post(
                self.webhook_url,
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-webhook-token',
            )

        self.assertEqual(response.status_code, 200)
        mock_send_message.assert_called_once()
        self.assertIn('Bot commands', mock_send_message.call_args.args[0])
        mock_diagnostic_response.assert_not_called()
        mock_message_filter.assert_called_once_with(chat_id='1', message_id=123)
        mock_message_create.assert_called_once_with(
            message='/help',
            message_id=123,
            from_username='operator',
            chat_id='1',
        )

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    def test_listener_rejects_malformed_json_without_server_error(self):
        response = self.client.post(
            self.webhook_url,
            data='{not-json',
            content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-webhook-token',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'ok': False, 'error': 'invalid_update'})

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    def test_listener_accepts_update_without_message_text(self):
        response = self.client.post(
            self.webhook_url,
            data=json.dumps({'update_id': 43, 'callback_query': {'id': 'callback'}}),
            content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-webhook-token',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'ok': True, 'ignored': 'no_text_message'})

    @patch('core.views.requests.post', side_effect=requests.Timeout('timed out'))
    def test_send_message_uses_timeout_and_reports_timeout_failure(self, mock_post):
        from core.views import send_message

        self.assertFalse(send_message('hello', 1))
        self.assertEqual(mock_post.call_args.kwargs['timeout'], 10)

    @patch('core.views.requests.post')
    def test_send_message_rejects_telegram_ok_false(self, mock_post):
        from core.views import send_message

        mock_post.return_value = SimpleNamespace(
            ok=True,
            json=lambda: {'ok': False, 'error_code': 403, 'description': 'Forbidden'},
        )

        self.assertFalse(send_message('hello', 1))

    @patch('core.views.requests.post')
    def test_send_message_reports_confirmed_telegram_success(self, mock_post):
        from core.views import send_message

        mock_post.return_value = SimpleNamespace(ok=True, json=lambda: {'ok': True, 'result': {}})

        self.assertTrue(send_message('hello', 1))


class TelegramDiagnosticsCommandTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.webhook_url = reverse('listener')

    def post_telegram_message(self, text, chat_id=999, username='operator'):
        payload = {
            "message": {
                "text": text,
                "message_id": 456,
                "chat": {"id": chat_id},
                "from": {"id": 777, "username": username},
            }
        }
        return self.client.post(
            self.webhook_url,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-webhook-token',
        )

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_unauthorized_chat_rejected_without_diagnostic_query(self, mock_health_manager, mock_send_message):
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/health', chat_id=111)

        self.assertEqual(response.status_code, 200)
        mock_send_message.assert_called_once()
        self.assertIn('Unauthorized', mock_send_message.call_args[0][0])
        mock_health_manager.order_by.assert_not_called()

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_invalid_symbol_rejected(self, mock_portfolio_manager, mock_send_message):
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/position saga/usdt')

        self.assertEqual(response.status_code, 200)
        mock_send_message.assert_called_once()
        self.assertIn('Invalid symbol', mock_send_message.call_args[0][0])
        mock_portfolio_manager.filter.assert_not_called()

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_health_formats_latest_healthcheck(self, mock_health_manager, mock_send_message):
        created_at = timezone.now() - timezone.timedelta(minutes=3)
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=7,
            status='healthy',
            created_at=created_at,
            details={
                'run_id': 'run-123',
                'positions_count': 4,
                'material_positions_count': 2,
                'dust_positions_count': 1,
                'unknown_value_positions_count': 1,
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/health')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🟢 Bot health</b>', message)
        self.assertIn('<code>run-123</code>', message)
        self.assertIn('raw/material/dust/unknown', message)
        self.assertIn('<code>4/2/1/1</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_health_formats_vps_disk_usage_from_healthcheck_details(self, mock_health_manager, mock_send_message):
        created_at = timezone.now() - timezone.timedelta(minutes=3)
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=7,
            status='healthy',
            created_at=created_at,
            details={
                'run_id': 'run-123',
                'disk_usage': {
                    'filesystem': '/',
                    'total_bytes': 100 * 1024 ** 3,
                    'used_bytes': 72 * 1024 ** 3,
                    'free_bytes': 28 * 1024 ** 3,
                    'used_pct': 72.0,
                    'status': 'warning',
                    'source': 'bot_vps',
                },
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/health')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>Disk Usage</b>', message)
        self.assertIn('Source: <code>Bot VPS</code>', message)
        self.assertIn('Filesystem: <code>/</code>', message)
        self.assertIn('Used: <code>72.0%</code>', message)
        self.assertIn('Free: <code>28.00 GB</code>', message)
        self.assertIn('Status:\n<code>🟡 Warning</code>', message)
        self.assertNotIn('Django host', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_health_missing_disk_usage_does_not_hide_bot_health(self, mock_health_manager, mock_send_message):
        created_at = timezone.now() - timezone.timedelta(minutes=3)
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=7,
            status='healthy',
            created_at=created_at,
            details={'run_id': 'run-123'},
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/health')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🟢 Bot health</b>', message)
        self.assertIn('<b>Disk Usage</b>', message)
        self.assertIn('Source: <code>Unavailable</code>', message)
        self.assertIn('Status:\n<code>Unavailable</code>', message)
        self.assertNotIn('Django host', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_health_disk_usage_renders_when_bot_healthcheck_missing(self, mock_health_manager, mock_send_message):
        mock_health_manager.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/health')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>⚪ Bot health</b>', message)
        self.assertIn('Status: <code>unknown</code>', message)
        self.assertIn('<b>Disk Usage</b>', message)
        self.assertIn('Source: <code>Unavailable</code>', message)
        self.assertIn('Status:\n<code>Unavailable</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_health_malformed_disk_usage_renders_unavailable(self, mock_health_manager, mock_send_message):
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=7,
            status='healthy',
            created_at=timezone.now(),
            details={'run_id': 'run-123', 'disk_usage': {'used_pct': 'not-a-number'}},
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/health')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>Disk Usage</b>', message)
        self.assertIn('Source: <code>Unavailable</code>', message)
        self.assertIn('Status:\n<code>Unavailable</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    def test_help_lists_available_diagnostics_commands(self, mock_send_message):
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/help')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🤖 Bot commands</b>', message)
        self.assertIn('/start', message)
        self.assertIn('/help', message)
        self.assertIn('/health', message)
        self.assertIn('/buy_status', message)
        self.assertIn('/portfolio_status', message)
        self.assertIn('/position SYMBOL', message)
        self.assertIn('/last_sell SYMBOL', message)
        self.assertIn('/why_not_sell SYMBOL', message)
        self.assertIn('/getmyinvest', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_returns_capacity_with_runtime_max_positions_fallback(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.side_effect = DatabaseError('portfolio unavailable')
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=9,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 17,
                'material_positions_count': 5,
                'dust_positions_count': 12,
                'unknown_value_positions_count': 0,
                'material_symbols': ['BTCUSDT'],
                'dust_symbols': ['SAGAUSDT', 'ETHUSDT'],
                'unknown_value_symbols': [],
                'free_usdt': Decimal('123.450000000000000000'),
                'latest_buy_reason': 'capacity available',
            },
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with patch.dict(os.environ, {'MAX_POSITIONS': '10'}):
            with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
                response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🟢 BUY status</b>', message)
        self.assertIn('Raw: <code>17</code>', message)
        self.assertIn('Effective positions: <code>5 / 10</code>', message)
        self.assertIn('Remaining slots: <code>5</code>', message)
        self.assertIn('Material: <code>5</code>', message)
        self.assertIn('Dust: <code>12</code>', message)
        self.assertIn('Dust positions are non-blocking', message)
        self.assertIn('Free USDT: <code>123.45 USDT</code>', message)
        self.assertIn('Reason: <code>capacity available</code>', message)
        self.assertIn('✅ Capacity available', message)


    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_keeps_capacity_when_optional_fields_are_missing(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.side_effect = DatabaseError('portfolio unavailable')
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=10,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 6,
                'material_positions_count': 4,
                'dust_positions_count': 1,
                'unknown_value_positions_count': 1,
                'material_symbols': ['BTCUSDT'],
                'dust_symbols': ['SAGAUSDT'],
                'unknown_value_symbols': ['MYSTERYUSDT'],
                'max_positions': 10,
            },
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Effective positions: <code>5 / 10</code>', message)
        self.assertIn('Remaining slots: <code>5</code>', message)
        self.assertIn('Free USDT: <code>diagnostic unavailable</code>', message)
        self.assertIn('Reason: <code>unavailable</code>', message)
        self.assertIn('✅ Capacity available', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_prefers_nested_position_classification_from_healthcheck(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.side_effect = DatabaseError('portfolio unavailable')
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=26,
            status='healthy',
            created_at=timezone.now(),
            details={
                'max_positions': 8,
                'position_classification': {
                    'positions_count': 3,
                    'material_positions_count': 1,
                    'dust_positions_count': 1,
                    'unknown_value_positions_count': 1,
                    'material_symbols': ['BTCUSDT'],
                    'dust_symbols': ['WLDUSDT'],
                    'unknown_value_symbols': ['MYSTERYUSDT'],
                },
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Raw: <code>3</code>', message)
        self.assertIn('Material: <code>1</code>', message)
        self.assertIn('Dust: <code>1</code>', message)
        self.assertIn('Unknown value: <code>1</code>', message)
        self.assertIn('Effective positions: <code>2 / 8</code>', message)
        self.assertIn('Valuation unavailable: <code>MYSTERYUSDT', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_rejects_unauthorized_chat_without_query(self, mock_health_manager, mock_send_message):
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status', chat_id=111)

        self.assertEqual(response.status_code, 200)
        mock_send_message.assert_called_once()
        self.assertIn('Unauthorized', mock_send_message.call_args[0][0])
        mock_health_manager.order_by.assert_not_called()

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_handles_missing_healthcheck_gracefully(self, mock_health_manager, mock_send_message):
        mock_health_manager.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>⚪ BUY status</b>', message)
        self.assertIn('⚪ Diagnostic unavailable: latest healthcheck missing', message)

    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('0'))
    @patch('core.telegram_diagnostics.latest_buy_rejection_reason', return_value=None)
    def test_buy_status_keeps_current_positions_when_healthcheck_is_missing(
        self, _mock_rejection, _mock_realized,
    ):
        from core.telegram_diagnostics import format_buy_status

        row = SimpleNamespace(
            symbol='BTCUSDT', quantity=Decimal('1'), entry_price=Decimal('9'),
            current_price=Decimal('10'),
        )
        with patch('core.telegram_diagnostics.BotHealthcheck.objects') as health, \
             patch('core.telegram_diagnostics.Portfolio.objects') as portfolio:
            health.order_by.return_value.first.return_value = None
            portfolio.filter.return_value = [row]
            with self.settings(MAX_POSITIONS=8):
                message = format_buy_status()

        self.assertIn('Effective positions: <code>N/A / 8</code>', message)
        self.assertIn('Material: <code>N/A</code>', message)
        self.assertNotIn('- BTCUSDT ~ 10 USDT', message)
        self.assertIn('Diagnostic unavailable: latest healthcheck missing', message)

    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('0'))
    @patch('core.telegram_diagnostics.latest_buy_rejection_reason', return_value=None)
    def test_buy_status_does_not_treat_stale_healthcheck_values_as_current(
        self, _mock_rejection, _mock_realized,
    ):
        from core.telegram_diagnostics import format_buy_status

        row = SimpleNamespace(
            symbol='BTCUSDT', quantity=Decimal('1'), entry_price=Decimal('9'),
            current_price=Decimal('10'),
        )
        stale = SimpleNamespace(
            created_at=timezone.now() - timezone.timedelta(minutes=45),
            details={
                'max_positions': 8, 'free_usdt': '100',
                'positions_count': 1, 'material_positions_count': 1,
                'dust_positions_count': 0, 'unknown_value_positions_count': 0,
                'material_symbols': ['BTCUSDT'], 'dust_symbols': [],
                'latest_buy_decision': 'blocked_by_usdt',
                'latest_buy_reason': 'free_usdt_below_buy_amount',
                'latest_buy_error_class': 'BinanceAPIError',
                'latest_buy_error_code': '429',
            },
        )
        with patch('core.telegram_diagnostics.BotHealthcheck.objects') as health, \
             patch('core.telegram_diagnostics.Portfolio.objects') as portfolio:
            health.order_by.return_value.first.return_value = stale
            portfolio.filter.return_value = [row]
            from core.telegram_diagnostics import interpret_buy_state as real_interpret_buy_state
            with patch('core.telegram_diagnostics.interpret_buy_state', wraps=real_interpret_buy_state) as interpret:
                message = format_buy_status()

        self.assertIn('Free USDT: <code>diagnostic unavailable</code>', message)
        self.assertIn('healthcheck stale', message.lower())
        self.assertIn('<b>Positions (last persisted; stale)</b>', message)
        self.assertIn('<b>Last persisted BUY (historical; healthcheck stale)</b>', message)
        self.assertIn('- Reason: <code>free_usdt_below_buy_amount</code>', message)
        self.assertIn('- Error code: <code>429</code>', message)
        self.assertIsNone(interpret.call_args.kwargs['latest_buy_error'])
        self.assertNotIn('Insufficient free USDT for next BUY', message)
        self.assertNotIn('✅ Capacity available', message)

    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('0'))
    @patch('core.telegram_diagnostics.latest_buy_rejection_reason', return_value=None)
    def test_buy_status_prefers_persisted_remaining_capacity(
        self, _mock_rejection, _mock_realized,
    ):
        from core.telegram_diagnostics import format_buy_status

        current = SimpleNamespace(
            created_at=timezone.now(),
            details={
                'positions_count': 1, 'material_positions_count': 1,
                'dust_positions_count': 0, 'unknown_value_positions_count': 0,
                'max_positions': 8, 'remaining_buy_capacity': 3,
                'material_symbols': [], 'dust_symbols': [],
            },
        )
        with patch('core.telegram_diagnostics.BotHealthcheck.objects') as health, \
             patch('core.telegram_diagnostics.Portfolio.objects'):
            health.order_by.return_value.first.return_value = current
            message = format_buy_status()

        self.assertIn('Effective positions: <code>1 / 8</code>', message)
        self.assertIn('Remaining slots: <code>3</code>', message)

    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('0'))
    @patch('core.telegram_diagnostics.latest_buy_rejection_reason', return_value=None)
    def test_buy_status_with_healthcheck_without_timestamp_marks_freshness_unknown(
        self, _mock_rejection, _mock_realized,
    ):
        from core.telegram_diagnostics import format_buy_status

        with patch('core.telegram_diagnostics.BotHealthcheck.objects') as health, \
             patch('core.telegram_diagnostics.Portfolio.objects') as portfolio:
            health.order_by.return_value.first.return_value = SimpleNamespace(
                created_at=None, details={'max_positions': 8, 'free_usdt': '20'},
            )
            portfolio.filter.return_value = SimpleNamespace(order_by=lambda *args: [])
            message = format_buy_status()

        self.assertIn('Healthcheck freshness unavailable', message)
        self.assertIn('Free USDT: <code>diagnostic unavailable</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_displays_blocked_when_effective_positions_reach_max(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.side_effect = DatabaseError('portfolio unavailable')
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=10,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 10,
                'material_positions_count': 10,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'material_symbols': ['BTCUSDT'],
                'dust_symbols': [],
                'unknown_value_symbols': [],
                'max_positions': 10,
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🔴 BUY status</b>', message)
        self.assertIn('⛔ No remaining BUY slots', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_treats_dust_as_non_blocking_when_raw_positions_exceed_max(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=11,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 15,
                'material_positions_count': 2,
                'dust_positions_count': 13,
                'unknown_value_positions_count': 0,
                'material_symbols': ['ETHUSDT', 'SOLUSDT'],
                'dust_symbols': ['SAGAUSDT'],
                'unknown_value_symbols': [],
                'max_positions': 10,
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🟢 BUY status</b>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_renders_reentry_cooldown_details(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=12,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 2,
                'material_positions_count': 1,
                'dust_positions_count': 1,
                'unknown_value_positions_count': 0,
                'max_positions': 5,
                'latest_buy_state': 'rejected',
                'latest_buy_reason': 'loss_reentry_cooldown_active',
                'latest_buy_symbol': 'BTCUSDT',
                'latest_sell_operation_id': 77,
                'latest_sell_reason': 'stop_loss_reached',
                'cooldown_type': 'loss',
                'cooldown_minutes': 60,
                'cooldown_remaining_minutes': 42,
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Re-entry blocked after loss/stop-loss cooldown', message)
        self.assertIn('Candidate: <code>BTCUSDT</code>', message)
        self.assertIn('Cooldown remaining: <code>42 min</code>', message)
        self.assertIn('Dust positions are non-blocking', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_renders_extended_reentry_cooldown_diagnostics(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=22,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 2,
                'material_positions_count': 1,
                'dust_positions_count': 1,
                'unknown_value_positions_count': 0,
                'max_positions': 5,
                'latest_buy_state': 'rejected',
                'latest_buy_reason': 'loss_reentry_cooldown_active',
                'latest_buy_symbol': 'BTCUSDT',
                'latest_sell_operation_id': 77,
                'latest_sell_symbol': 'BTCUSDT',
                'latest_sell_executed_at': '2026-05-25T12:34:56Z',
                'latest_sell_reason': 'stop_loss_reached',
                'latest_sell_reason_source': 'raw_payload',
                'latest_sell_realized_pnl': '-3.125',
                'cooldown_type': 'loss',
                'cooldown_minutes': 60,
                'cooldown_elapsed_minutes': 18,
                'cooldown_remaining_minutes': 42,
                'cooldown_classification_source': 'explicit_sell_reason',
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Latest SELL operation: <code>77</code>', message)
        self.assertIn('Latest SELL symbol: <code>BTCUSDT</code>', message)
        self.assertIn('Latest SELL timestamp: <code>2026-05-25T12:34:56Z</code>', message)
        self.assertIn('Latest SELL reason: <code>stop_loss_reached</code>', message)
        self.assertIn('Reason source: <code>raw_payload</code>', message)
        self.assertIn('Latest SELL realized PnL: <code>-3.13 USDT</code>', message)
        self.assertIn('Cooldown type: <code>loss</code>', message)
        self.assertIn('Classification source: <code>explicit sell reason</code>', message)
        self.assertIn('Cooldown elapsed: <code>18 min</code>', message)
        self.assertIn('Cooldown remaining: <code>42 min</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_renders_partial_cooldown_metadata_without_ambiguous_na(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=23,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 5,
                'latest_buy_state': 'rejected',
                'latest_buy_reason': 'loss_reentry_cooldown_active',
                'latest_buy_symbol': 'ETHUSDT',
                'latest_sell_operation_id': 88,
                'latest_sell_executed_at': '2026-05-25T13:00:00Z',
                'latest_sell_reason': None,
                'latest_sell_realized_pnl': '-0.01',
                'cooldown_type': 'sell',
                'cooldown_minutes': 30,
                'cooldown_elapsed_minutes': 7,
                'cooldown_remaining_minutes': 23,
                'cooldown_classification_source': 'realized_pnl',
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertNotIn('Latest SELL reason: <code>N/A</code>', message)
        self.assertIn('Latest SELL reason: <code>not provided</code>', message)
        self.assertIn('Cooldown triggered from negative realized PnL', message)
        self.assertIn('Cooldown type: <code>recent sell</code>', message)
        self.assertIn('Classification source: <code>realized PnL</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_keeps_legacy_cooldown_payload_compatible(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=24,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 5,
                'latest_buy_state': 'rejected',
                'latest_buy_reason': 'sell_reentry_cooldown_active',
                'latest_buy_symbol': 'SOLUSDT',
                'latest_sell_timestamp': '2026-05-25T11:11:00Z',
                'cooldown_type': 'generic_sell',
                'cooldown_remaining_minutes': 4,
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Latest SELL timestamp: <code>2026-05-25T11:11:00Z</code>', message)
        self.assertIn('Latest SELL operation: <code>unknown</code>', message)
        self.assertIn('Cooldown type: <code>recent sell</code>', message)
        self.assertIn('Cooldown remaining: <code>4 min</code>', message)

    def test_cooldown_diagnostics_format_realized_pnl_edge_cases(self):
        cases = [
            (None, None, 'unknown'),
            ('0', Decimal('0'), '0 USDT'),
            ('-1.234', Decimal('-1.234'), '-1.23 USDT'),
            ('2.345', Decimal('2.345'), '2.35 USDT'),
            ('1.2300', Decimal('1.2300'), '1.23 USDT'),
            ('1E+3', Decimal('1E+3'), '1000 USDT'),
            ('not-a-number', None, 'unknown'),
        ]
        for raw_value, parsed_value, label in cases:
            with self.subTest(raw_value=raw_value):
                diagnostics = build_cooldown_diagnostics({
                    'latest_buy_reason': 'sell_reentry_cooldown_active',
                    'latest_sell_operation_id': 77,
                    'latest_sell_realized_pnl': raw_value,
                    'cooldown_type': 'generic_sell',
                })

                self.assertEqual(diagnostics['latest_sell_realized_pnl'], parsed_value)
                self.assertEqual(diagnostics['latest_sell_realized_pnl_label'], label)
                self.assertEqual(diagnostics['cooldown_type_label'], 'recent sell')

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_renders_material_inventory_warnings_from_healthcheck_details(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=18,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 8,
                'reconciliation': {
                    'inventory_warnings': [
                        {
                            'symbol': 'USDCUSDT',
                            'reason': 'open_lots_without_portfolio_row',
                            'severity': 'WARNING',
                            'estimated_notional_usdt': '15',
                        },
                    ],
                },
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>Inventory warnings</b>', message)
        self.assertIn('- USDCUSDT: open lots without portfolio row (~15 USDT)', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_omits_inventory_warning_section_without_relevant_warnings(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=19,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 8,
                'reconciliation': {'inventory_warnings': []},
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertNotIn('<b>Inventory warnings</b>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_omits_info_inventory_warnings_from_main_message(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=20,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 8,
                'reconciliation': {
                    'inventory_warnings': [
                        {'symbol': 'DUSTUSDT', 'reason': 'portfolio_row_without_open_lots', 'severity': 'INFO'},
                    ],
                },
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertNotIn('<b>Inventory warnings</b>', message)
        self.assertNotIn('DUSTUSDT', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_renders_unknown_inventory_valuation_and_escapes_dynamic_values(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=21,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 8,
                'reconciliation': {
                    'inventory_warnings': [
                        {
                            'symbol': '<LEGACY&USDT>',
                            'reason': '<custom_reason>',
                            'severity': 'CRITICAL',
                            'estimated_notional_usdt': None,
                            'valuation_status': 'unknown',
                        },
                    ],
                },
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertIn('&lt;LEGACY&amp;USDT&gt;', message)
        self.assertIn('&lt;custom reason&gt;', message)
        self.assertIn('(valuation unknown)', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_limits_inventory_warning_rows_for_mobile_readability(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=22,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 8,
                'reconciliation': {
                    'inventory_warnings': [
                        {'symbol': f'SYM{i}', 'reason': 'portfolio_lot_quantity_drift', 'severity': 'WARNING'}
                        for i in range(4)
                    ],
                },
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertIn('- SYM0: portfolio vs lots quantity drift', message)
        self.assertIn('- SYM2: portfolio vs lots quantity drift', message)
        self.assertNotIn('- SYM3: portfolio vs lots quantity drift', message)
        self.assertIn('- +1 more', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_renders_mobile_exposure_summary_with_material_values_sorted_desc(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_send_message,
    ):
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=13,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 4,
                'material_positions_count': 3,
                'dust_positions_count': 1,
                'unknown_value_positions_count': 0,
                'material_symbols': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
                'dust_symbols': ['XRPUSDT'],
                'max_positions': 8,
                'remaining_buy_capacity': 5,
                'free_usdt': Decimal('0.020000000000000000'),
            },
        )
        mock_portfolio_manager.filter.return_value = [
            SimpleNamespace(symbol='BTCUSDT', quantity=Decimal('1'), entry_price=None, current_price=Decimal('5.24')),
            SimpleNamespace(symbol='ETHUSDT', quantity=Decimal('2'), entry_price=Decimal('5.00'), current_price=Decimal('5.41')),
            SimpleNamespace(symbol='SOLUSDT', quantity=Decimal('1'), entry_price=Decimal('4.00'), current_price=Decimal('6.00')),
            SimpleNamespace(symbol='XRPUSDT', quantity=Decimal('2'), entry_price=Decimal('0.55'), current_price=Decimal('0.56')),
        ]

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🟢 BUY status</b>', message)
        self.assertIn('<b>Capacity</b>', message)
        self.assertIn('Effective positions: <code>3 / 8</code>', message)
        self.assertIn('Remaining slots: <code>5</code>', message)
        self.assertIn('Free USDT: <code>0.02 USDT</code>', message)
        self.assertIn('<b>Positions</b>', message)
        self.assertIn('Raw: <code>4</code>', message)
        self.assertIn('<b>Material exposure (~22.06 USDT)</b>', message)
        self.assertIn('ETHUSDT ~ 10.82 USDT | PnL +0.82 USDT (+8.20%)', message)
        self.assertIn('SOLUSDT ~ 6 USDT | PnL +2 USDT (+50.00%)', message)
        self.assertIn('BTCUSDT ~ 5.24 USDT | PnL unavailable', message)
        self.assertLess(message.index('ETHUSDT ~ 10.82 USDT'), message.index('SOLUSDT ~ 6 USDT'))
        self.assertLess(message.index('SOLUSDT ~ 6 USDT'), message.index('BTCUSDT ~ 5.24 USDT'))
        self.assertIn('<b>Dust exposure</b>', message)
        self.assertIn('Estimated dust exposure: <code>~1.12 USDT</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_compacts_dust_lists_and_marks_partial_unavailable(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_send_message,
    ):
        dust_symbols = [f'DUST{i}USDT' for i in range(6)]
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=14,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 6,
                'material_positions_count': 0,
                'dust_positions_count': 6,
                'unknown_value_positions_count': 0,
                'material_symbols': [],
                'dust_symbols': dust_symbols,
                'max_positions': 8,
            },
        )
        mock_portfolio_manager.filter.return_value = [
            SimpleNamespace(symbol=symbol, quantity=Decimal('1'), current_price=Decimal('0.1'))
            for symbol in dust_symbols[:-1]
        ] + [
            SimpleNamespace(symbol=dust_symbols[-1], quantity=Decimal('1'), current_price=None),
        ]

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertIn('Dust positions: <code>6</code>', message)
        self.assertIn('Unknown value: <code>0</code>', message)
        self.assertIn('Estimated dust exposure: <code>partially unavailable</code>', message)
        self.assertNotIn('DUST0USDT, DUST1USDT, DUST2USDT, DUST3USDT, DUST4USDT, DUST5USDT', message)
        self.assertIn('Unknown value', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_lists_small_dust_sets_compactly_and_escapes_dynamic_values(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_send_message,
    ):
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=15,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 2,
                'material_positions_count': 0,
                'dust_positions_count': 2,
                'unknown_value_positions_count': 0,
                'material_symbols': [],
                'dust_symbols': ['<XRPUSDT>', 'NEAR&USDT'],
                'max_positions': 8,
                'latest_buy_state': 'no_candidate',
                'latest_buy_reason': '<scanner&empty>',
                'latest_buy_symbol': '<BTCUSDT>',
            },
        )
        mock_portfolio_manager.filter.return_value = [
            SimpleNamespace(symbol='<XRPUSDT>', quantity=Decimal('1'), current_price=Decimal('0.1')),
            SimpleNamespace(symbol='NEAR&USDT', quantity=Decimal('1'), current_price=Decimal('0.2')),
        ]

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertIn('Symbols: <code>&lt;XRPUSDT&gt;, NEAR&amp;USDT</code>', message)
        self.assertIn('Reason: <code>&lt;scanner&amp;empty&gt;</code>', message)
        self.assertIn('Candidate: <code>&lt;BTCUSDT&gt;</code>', message)
        self.assertIn('Scanner did not select a BUY candidate', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_separates_capacity_from_latest_buy_blockers(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.side_effect = DatabaseError('portfolio unavailable')
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=16,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 5,
                'material_positions_count': 5,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 8,
                'remaining_buy_capacity': 3,
                'latest_buy_state': 'blocked_by_usdt',
                'latest_buy_reason': 'free_usdt_below_buy_amount',
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertIn('✅ Capacity available', message)
        self.assertIn('⚠️ Insufficient free USDT for next BUY', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_fallback_classifies_wld_residual_as_dust(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        wld_row = SimpleNamespace(
            symbol='WLDUSDT',
            quantity=Decimal('0.0884'),
            entry_price=Decimal('0.5000'),
            current_price=Decimal('0.4367'),
        )

        def portfolio_filter(**kwargs):
            if kwargs == {'quantity__gt': 0}:
                return SimpleNamespace(order_by=lambda *args: [wld_row])
            if kwargs == {'symbol__in': ['WLDUSDT']}:
                return [wld_row]
            return []

        mock_portfolio_manager.filter.side_effect = portfolio_filter
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=23,
            status='healthy',
            created_at=timezone.now(),
            details={
                'max_positions': 8,
                'free_usdt': Decimal('25'),
            },
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Material: <code>N/A</code>', message)
        self.assertIn('Dust: <code>N/A</code>', message)
        self.assertIn('Effective positions: <code>N/A / 8</code>', message)
        self.assertNotIn('WLDUSDT', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_exposure_preserves_healthcheck_material_symbol(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        wld_row = SimpleNamespace(
            symbol='WLDUSDT',
            quantity=Decimal('0.0884'),
            entry_price=Decimal('0.5000'),
            current_price=Decimal('0.4367'),
        )
        mock_portfolio_manager.filter.return_value = [wld_row]
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=27,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'material_symbols': ['WLDUSDT'],
                'dust_symbols': [],
                'unknown_value_symbols': [],
                'max_positions': 8,
            },
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>Material exposure (~0.04 USDT)</b>', message)
        self.assertIn('- WLDUSDT ~ 0.04 USDT', message)
        self.assertIn('Estimated dust exposure: <code>~0 USDT</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_final_message_keeps_healthcheck_wld_material_classification(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = [
            SimpleNamespace(
                symbol='WLDUSDT',
                quantity=Decimal('0.0884'),
                entry_price=Decimal('0.5000'),
                current_price=Decimal('0.4367'),
            ),
        ]
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=28,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'material_symbols': ['WLDUSDT'],
                'dust_symbols': [],
                'unknown_value_symbols': [],
                'max_positions': 8,
            },
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        material_section = message.split('<b>Dust exposure</b>', 1)[0].split('<b>Material exposure', 1)[1]
        dust_section = message.split('<b>Dust exposure</b>', 1)[1].split('<b>Latest BUY</b>', 1)[0]

        self.assertIn('(~0.04 USDT)</b>', material_section)
        self.assertIn('WLDUSDT', material_section)
        self.assertIn('Estimated dust exposure: <code>~0 USDT</code>', dust_section)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_uses_one_current_classification_snapshot(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        current_rows = [
            SimpleNamespace(symbol='ZECUSDT', quantity=Decimal('1'), entry_price=Decimal('6'), current_price=Decimal('6.38')),
            SimpleNamespace(symbol='BNBUSDT', quantity=Decimal('0.02'), entry_price=Decimal('250'), current_price=Decimal('258')),
            *[
                SimpleNamespace(symbol=symbol, quantity=Decimal('1'), entry_price=Decimal('1'), current_price=Decimal('0.01'))
                for symbol in ('ETHUSDT', 'SOLUSDT', 'BTCUSDT', 'UNIUSDT', 'SUIUSDT', 'DOGEUSDT')
            ],
        ]
        mock_portfolio_manager.filter.side_effect = lambda **kwargs: (
            SimpleNamespace(order_by=lambda *args: current_rows)
            if kwargs == {'quantity__gt': 0}
            else current_rows
        )
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=29, status='healthy', created_at=timezone.now(),
            details={'positions_count': 8, 'material_positions_count': 8,
                     'dust_positions_count': 0, 'unknown_value_positions_count': 0,
                     'material_symbols': [row.symbol for row in current_rows],
                     'max_positions': 8, 'latest_buy_state': 'available'},
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Raw: <code>8</code>', message)
        self.assertIn('Material: <code>8</code>', message)
        self.assertIn('Dust: <code>0</code>', message)
        self.assertIn('Unknown value: <code>0</code>', message)
        self.assertIn('Effective positions: <code>8 / 8</code>', message)
        self.assertIn('Remaining slots: <code>0</code>', message)
        material_section = message.split('<b>Dust exposure</b>', 1)[0]
        self.assertIn('ZECUSDT', material_section)
        self.assertIn('BNBUSDT', material_section)
        self.assertIn('- ETHUSDT ~', material_section)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_uses_healthcheck_classification_not_portfolio_reclassification(
        self, portfolio_manager, health_manager, send_message,
    ):
        health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            created_at=timezone.now(),
            details={
                'positions_count': 2, 'material_positions_count': 1,
                'dust_positions_count': 1, 'unknown_value_positions_count': 0,
                'material_symbols': ['BTCUSDT'], 'dust_symbols': ['SHIBUSDT'],
                'unknown_value_symbols': [], 'max_positions': 8,
            },
        )
        portfolio_manager.filter.return_value = [
            SimpleNamespace(symbol='BTCUSDT', quantity=Decimal('1'), entry_price=Decimal('2'), current_price=Decimal('1')),
            SimpleNamespace(symbol='SHIBUSDT', quantity=Decimal('1'), entry_price=Decimal('1'), current_price=Decimal('6')),
        ]

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = send_message.call_args[0][0]
        material_section = message.split('<b>Dust exposure</b>', 1)[0]
        dust_section = message.split('<b>Dust exposure</b>', 1)[1].split('<b>Latest BUY</b>', 1)[0]
        self.assertIn('Material: <code>1</code>', message)
        self.assertIn('Dust: <code>1</code>', message)
        self.assertIn('- BTCUSDT ~ 1 USDT', material_section)
        self.assertNotIn('- SHIBUSDT ~', material_section)
        self.assertIn('SHIBUSDT', dust_section)

    def test_buy_classification_accepts_iterable_without_order_by(self):
        from core.telegram_diagnostics import _buy_classification_from_portfolio

        row = SimpleNamespace(symbol='ZECUSDT', quantity=Decimal('1'), current_price=Decimal('6'))
        with patch('core.telegram_diagnostics.Portfolio.objects') as manager:
            manager.filter.return_value = [row]
            classification = _buy_classification_from_portfolio()

        self.assertEqual(classification['material_count'], 1)
        self.assertFalse(classification['query_fallback'])
        self.assertEqual(classification['portfolio_rows'], [row])

    def test_buy_status_does_not_requery_empty_current_portfolio_snapshot(self):
        from core.telegram_diagnostics import format_buy_status

        empty_query = SimpleNamespace(order_by=lambda *args: [])
        with patch('core.telegram_diagnostics.Portfolio.objects') as manager, \
             patch('core.telegram_diagnostics.BotHealthcheck.objects') as health:
            manager.filter.return_value = empty_query
            health.order_by.return_value.first.return_value = SimpleNamespace(
                details={'material_positions_count': 8, 'max_positions': 8}
            )
            format_buy_status()

        manager.filter.assert_not_called()

    def test_buy_classification_falls_back_on_portfolio_database_error(self):
        from core.telegram_diagnostics import _buy_classification_from_portfolio

        with patch('core.telegram_diagnostics.Portfolio.objects') as manager:
            manager.filter.side_effect = DatabaseError('unavailable')
            classification = _buy_classification_from_portfolio()

        self.assertTrue(classification['query_fallback'])
        self.assertEqual(classification['portfolio_rows'], [])

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_fallback_classifies_material_position_above_threshold(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        material_row = SimpleNamespace(
            symbol='SOLUSDT',
            quantity=Decimal('2'),
            entry_price=Decimal('4.50'),
            current_price=Decimal('3.00'),
        )

        def portfolio_filter(**kwargs):
            if kwargs == {'quantity__gt': 0}:
                return SimpleNamespace(order_by=lambda *args: [material_row])
            if kwargs == {'symbol__in': ['SOLUSDT']}:
                return [material_row]
            return []

        mock_portfolio_manager.filter.side_effect = portfolio_filter
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=24,
            status='healthy',
            created_at=timezone.now(),
            details={'max_positions': 8},
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Material: <code>N/A</code>', message)
        self.assertIn('Dust: <code>N/A</code>', message)
        self.assertIn('Effective positions: <code>N/A / 8</code>', message)
        self.assertNotIn('- SOLUSDT ~ 6 USDT', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_fallback_classifies_missing_price_as_unknown_capacity(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        unknown_row = SimpleNamespace(
            symbol='MYSTERYUSDT',
            quantity=Decimal('1.5'),
            entry_price=Decimal('2'),
            current_price=None,
        )

        def portfolio_filter(**kwargs):
            if kwargs == {'quantity__gt': 0}:
                return SimpleNamespace(order_by=lambda *args: [unknown_row])
            return []

        mock_portfolio_manager.filter.side_effect = portfolio_filter
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=25,
            status='healthy',
            created_at=timezone.now(),
            details={'max_positions': 8},
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Material: <code>N/A</code>', message)
        self.assertIn('Unknown value: <code>N/A</code>', message)
        self.assertIn('Effective positions: <code>N/A / 8</code>', message)

    def test_buy_status_exposure_preserves_persisted_material_bucket_below_threshold(self):
        exposure = build_buy_status_exposure(
            ['WLDUSDT'],
            [],
            [
                SimpleNamespace(
                    symbol='WLDUSDT',
                    quantity=Decimal('0.0884'),
                    entry_price=Decimal('0.5000'),
                    current_price=Decimal('0.4367'),
                ),
            ],
        )

        self.assertEqual(exposure['material_rows'][0]['symbol'], 'WLDUSDT')
        self.assertEqual(exposure['material_rows'][0]['estimated_value_usdt'], Decimal('0.03860428'))
        self.assertEqual(exposure['dust_rows'], [])
        self.assertEqual(exposure['material_total'], Decimal('0.03860428'))
        self.assertEqual(exposure['dust_total'], Decimal('0'))

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_buy_status_reports_no_slots_when_blocked_by_positions(
        self,
        mock_portfolio_manager,
        mock_health_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=17,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 8,
                'material_positions_count': 8,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'max_positions': 8,
                'latest_buy_state': 'blocked_by_positions',
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.post_telegram_message('/buy_status')

        message = mock_send_message.call_args[0][0]
        self.assertIn('⛔ No remaining BUY slots', message)

    def test_numeric_formatting_trims_trailing_zeros(self):
        from core.telegram_diagnostics import fmt_drift, fmt_price, fmt_qty

        self.assertEqual(fmt_price(Decimal('0.031570000000000000')), '0.03157')
        self.assertEqual(fmt_qty(Decimal('15.000000000000000000')), '15')
        self.assertEqual(fmt_drift(Decimal('0E-18')), '0')

    def test_buy_state_reports_configured_blockers(self):
        from core.telegram_diagnostics import interpret_buy_state

        self.assertEqual(
            interpret_buy_state(5, 4, 10, free_usdt=Decimal('4'), min_required_buy_amount=Decimal('5'))[0],
            'blocked_by_usdt',
        )
        self.assertEqual(
            interpret_buy_state(5, 4, 10, read_only=True)[0],
            'blocked_by_read_only',
        )

    def test_buy_state_reports_latest_buy_outcomes(self):
        from core.telegram_diagnostics import interpret_buy_state

        self.assertEqual(
            interpret_buy_state(
                5,
                4,
                10,
                latest_buy_decision='submitted',
                latest_buy_error='BinanceAPIException',
            )[0],
            'execution_error',
        )
        self.assertEqual(
            interpret_buy_state(
                5,
                4,
                10,
                latest_buy_decision='no_candidate',
            )[0],
            'no_candidate',
        )

    def test_percent_formatting_rounds_to_two_decimals(self):
        from core.telegram_diagnostics import fmt_percent

        self.assertEqual(fmt_percent(Decimal('-4.592360807020153500')), '-4.59%')

    def test_usdt_formatting_avoids_noisy_long_decimals(self):
        from core.telegram_diagnostics import fmt_usdt

        self.assertEqual(fmt_usdt(Decimal('0.028549210000000000')), '0.0285 USDT')

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.DustDetection.objects')
    @patch('core.telegram_diagnostics.PositionLot.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_position_reads_portfolio_lots_and_latest_dust(
        self,
        mock_portfolio_manager,
        mock_lot_manager,
        mock_dust_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value.first.return_value = SimpleNamespace(
            symbol='SAGAUSDT',
            quantity=Decimal('12.5'),
            entry_price=Decimal('0.2100'),
            current_price=Decimal('0.2500'),
        )
        mock_lot_manager.filter.return_value.aggregate.return_value = {
            'open_quantity': Decimal('10.0'),
            'entry_price': Decimal('0.2050'),
        }
        mock_dust_manager.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            event_type='lot_balance_drift_detected',
            reason='<drift>',
            detected_at=timezone.now(),
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/position SAGAUSDT')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>📍 Position — SAGAUSDT</b>', message)
        self.assertIn('Portfolio qty: <code>12.5</code>', message)
        self.assertIn('Open lots: <code>10</code>', message)
        self.assertIn('Value: <code>3.13 USDT</code>', message)
        self.assertIn('&lt;drift&gt;', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.SellDecisionEvent.objects')
    def test_last_sell_reads_latest_sell_decision_event(self, mock_event_manager, mock_send_message):
        mock_event_manager.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            event_name='sell_signal_approved',
            reason='stop_loss_reached',
            validation_stage='approved',
            estimated_pnl_percent=Decimal('-23.21'),
            entry_price=Decimal('0.3100'),
            current_price=Decimal('0.2380'),
            stop_loss_threshold=Decimal('-3.00'),
            take_profit_threshold=Decimal('5.00'),
            profit_guard_bypassed=True,
            created_at=timezone.now(),
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/last_sell SAGAUSDT')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🔴 SELL diagnostic — SAGAUSDT</b>', message)
        self.assertIn('Reason: <code>stop_loss_reached</code>', message)
        self.assertIn('PnL: <code>-23.21%</code>', message)
        self.assertIn('Profit guard: <code>bypassed</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.SellDecisionEvent.objects')
    def test_why_not_sell_maps_reason_to_friendly_explanation(self, mock_event_manager, mock_send_message):
        mock_event_manager.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            event_name='sell_signal_rejected',
            reason='profit_guard_blocked_min_notional',
            validation_stage='profit_guard',
            estimated_pnl_percent=Decimal('-1.25'),
            entry_price=Decimal('0.3100'),
            current_price=Decimal('0.3061'),
            stop_loss_threshold=Decimal('-3.00'),
            take_profit_threshold=Decimal('5.00'),
            profit_guard_bypassed=False,
            created_at=timezone.now(),
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/why_not_sell SAGAUSDT')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('<b>🤔 Why not sell — SAGAUSDT</b>', message)
        self.assertIn('Status: <code>Review</code>', message)
        self.assertIn('Interpretation:', message)
        self.assertNotIn('<pre>', message)
        self.assertNotIn('Unknown', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.SellDecisionEvent.objects')
    def test_why_not_sell_known_reason_has_actionable_interpretation(self, mock_event_manager, mock_send_message):
        mock_event_manager.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            event_name='sell_order_skipped',
            reason='stop_loss_not_reached',
            validation_stage='strategy',
            estimated_pnl_percent=Decimal('-0.14'),
            entry_price=Decimal('1.00'),
            current_price=Decimal('0.9986'),
            stop_loss_threshold=Decimal('-3.00'),
            take_profit_threshold=Decimal('5.00'),
            profit_guard_bypassed=False,
            created_at=timezone.now(),
            payload={
                'strategy_name': 'full_exit',
                'estimated_value_usdt': '12.34',
                'open_lot_quantity': '4.56',
                'asset': 'XRP',
            },
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/why_not_sell XRPUSDT')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('Status: <code>Holding</code>', message)
        self.assertIn('Stop loss has not been reached.', message)
        self.assertIn('Suggested action:', message)
        self.assertIn('No action. Continue monitoring.', message)
        self.assertNotIn('Unknown', message)
        self.assertIn('Strategy: <code>full_exit</code>', message)
        self.assertIn('Estimated value: <code>12.34 USDT</code>', message)

    def test_dust_drift_alert_formats_manual_external_operation_human_readably(self):
        message = format_dust_drift_alert({
            'event': 'lot_balance_drift_detected',
            'severity': 'warning',
            'run_id': 'run-123',
            'symbol': 'XRPUSDT',
            'asset': 'XRP',
            'reason': 'manual_external_operation',
            'estimated_value_usdt': Decimal('0.000197302011'),
        })

        self.assertIn('<b>⚠️ Dust / drift detected — XRPUSDT</b>', message)
        self.assertIn('Reason: <code>Manual / external operation</code>', message)
        self.assertIn('tiny dust value', message)
        self.assertIn('Review in dashboard.', message)
        self.assertIn('Run ID: <code>run-123</code>', message)

    def test_dust_drift_alert_normalizes_reason_before_mapping(self):
        message = format_dust_drift_alert({
            'event': 'lot_balance_drift_detected',
            'severity': 'warning',
            'symbol': 'XRPUSDT',
            'asset': 'XRP',
            'reason': '  MANUAL_EXTERNAL_OPERATION  ',
            'estimated_value_usdt': Decimal('1'),
        })

        self.assertIn('Reason: <code>Manual / external operation</code>', message)

    def test_dust_drift_alert_marks_possible_incomplete_sell_as_urgent(self):
        message = format_dust_drift_alert({
            'event': 'lot_balance_drift_detected',
            'severity': 'critical',
            'symbol': 'BTCUSDT',
            'asset': 'BTC',
            'reason': 'possible_incomplete_sell',
            'estimated_value_usdt': Decimal('25'),
        })

        self.assertIn('🔴 Dust / drift detected', message)
        self.assertIn('Possible incomplete sell', message)
        self.assertIn('Review urgently.', message)

    def test_dust_drift_alert_escapes_dynamic_fields(self):
        message = format_dust_drift_alert({
            'event': '<event>',
            'severity': 'warning',
            'run_id': 'run&1',
            'symbol': '<XRP>',
            'asset': 'X&RP',
            'reason': '<manual>',
            'estimated_value_usdt': Decimal('1'),
        })

        self.assertIn('&lt;XRP&gt;', message)
        self.assertIn('X&amp;RP', message)
        self.assertIn('&lt;manual&gt;', message)
        self.assertIn('run&amp;1', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.SellDecisionEvent.objects')
    def test_html_escaping_prevents_broken_markup(self, mock_event_manager, mock_send_message):
        mock_event_manager.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
            event_name='sell_signal_rejected',
            reason='<script>alert(1)</script>',
            validation_stage='stage&check',
            estimated_pnl_percent=None,
            entry_price=None,
            current_price=None,
            stop_loss_threshold=None,
            take_profit_threshold=None,
            profit_guard_bypassed=False,
            created_at=timezone.now(),
        )

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/last_sell SAGAUSDT')

        self.assertEqual(response.status_code, 200)
        message = mock_send_message.call_args[0][0]
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', message)
        self.assertIn('stage&amp;check', message)
        self.assertNotIn('<script>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.requests.post')
    def test_send_message_uses_html_parse_mode(self, mock_post):
        send_url = 'https://api.telegram.org/bottest-token/sendMessage'
        with patch('core.views.TUTORIAL_BOT_TOKEN', 'test-token'):
            from core.views import send_message

            send_message('<b>ok</b>', 999)

        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args[0][0], send_url)
        self.assertEqual(mock_post.call_args.kwargs['data']['parse_mode'], 'HTML')

    def test_diagnostics_models_are_read_only(self):
        from core.trading_models import SellDecisionEvent, Snapshot

        self.assertFalse(SellDecisionEvent._meta.managed)
        self.assertEqual(SellDecisionEvent._meta.db_table, '"bot"."sell_decision_events"')
        self.assertFalse(Snapshot._meta.managed)
        self.assertEqual(Snapshot._meta.db_table, '"bot"."portfolio_snapshots"')
        self.assertIn("notes", {field.name for field in Snapshot._meta.fields})
        with self.assertRaisesMessage(RuntimeError, 'read-only'):
            SellDecisionEvent(symbol='SAGAUSDT', event_name='sell_signal_rejected').save()

    def test_diagnostics_module_does_not_import_binance_client(self):
        import core.telegram_diagnostics as telegram_diagnostics

        source = inspect.getsource(telegram_diagnostics)
        self.assertNotIn('from binance', source.lower())
        self.assertNotIn('import binance', source.lower())

    def test_trade_operation_model_is_read_only_for_buy_status(self):
        self.assertFalse(TradeOperation._meta.managed)
        with self.assertRaisesMessage(RuntimeError, 'read-only'):
            TradeOperation(symbol='SAGAUSDT', side='BUY').save()

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.DustDetection.objects')
    @patch('core.telegram_diagnostics.PositionLot.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    def test_position_command_does_not_write_bot_owned_tables(
        self,
        mock_portfolio_manager,
        mock_lot_manager,
        mock_dust_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value.first.return_value = None
        mock_lot_manager.filter.return_value.aggregate.return_value = {
            'open_quantity': Decimal('0'),
            'entry_price': None,
        }
        mock_dust_manager.filter.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/position SAGAUSDT')

        self.assertEqual(response.status_code, 200)
        for manager in [mock_portfolio_manager, mock_lot_manager, mock_dust_manager]:
            manager.create.assert_not_called()
            manager.bulk_create.assert_not_called()
            manager.update_or_create.assert_not_called()
            manager.filter.return_value.update.assert_not_called()
        mock_send_message.assert_called_once()

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_command_does_not_write_bot_owned_tables(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_trade_manager,
        mock_send_message,
    ):
        mock_portfolio_manager.filter.return_value = []
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=12,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 0,
                'dust_positions_count': 1,
                'unknown_value_positions_count': 0,
                'material_symbols': [],
                'dust_symbols': ['SAGAUSDT'],
                'unknown_value_symbols': [],
                'max_positions': 10,
            },
        )
        mock_trade_manager.filter.return_value.exclude.return_value.order_by.return_value.first.return_value = None

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = self.post_telegram_message('/buy_status')

        self.assertEqual(response.status_code, 200)
        for manager in [mock_health_manager, mock_trade_manager]:
            manager.create.assert_not_called()
            manager.bulk_create.assert_not_called()
            manager.update_or_create.assert_not_called()
            manager.filter.return_value.update.assert_not_called()
        mock_send_message.assert_called_once()

    @patch('core.telegram_diagnostics.logger')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_portfolio_fallback_logs_at_debug_level(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        mock_logger,
    ):
        from django.db import DatabaseError
        from core.telegram_diagnostics import format_buy_status

        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            id=18,
            status='healthy',
            created_at=timezone.now(),
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'material_symbols': ['BTCUSDT'],
                'dust_symbols': [],
                'unknown_value_symbols': [],
                'max_positions': 8,
            },
        )
        mock_portfolio_manager.filter.side_effect = DatabaseError('missing portfolio')

        format_buy_status()

        mock_logger.debug.assert_any_call('Could not read portfolio rows for Telegram BUY status exposure')
        mock_logger.warning.assert_not_called()


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

    def test_dashboard_route_is_owned_by_dashboard_app(self):
        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.resolver_match.func.__module__, "dashboard.views")

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_authenticated_user_gets_dashboard(self, mock_get_dashboard_context):
        mock_get_dashboard_context.return_value.context = self.empty_dashboard_context()
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operations Console')
        mock_get_dashboard_context.assert_called_once()

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_loads_when_bot_tables_are_empty(self, mock_get_dashboard_context):
        mock_get_dashboard_context.return_value.context = self.empty_dashboard_context()
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No latest message.')
        self.assertContains(response, 'Inventory Integrity')

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_renders_disk_usage_section(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        context['disk_usage'] = {
            'available': True,
            'filesystem': '/',
            'total_bytes': 100 * 1024 ** 3,
            'used_bytes': 72 * 1024 ** 3,
            'free_bytes': 28 * 1024 ** 3,
            'used_percent': Decimal('72'),
            'free_gb': Decimal('28'),
            'status': 'warning',
            'status_label': 'Warning',
            'status_icon': '🟡',
            'badge_class': 'badge-warning',
            'source': 'bot_vps',
            'source_label': 'Bot VPS',
        }
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Disk Usage')
        self.assertContains(response, 'Source: <strong>Bot VPS</strong>', html=True)
        self.assertContains(response, 'Filesystem: <strong>/</strong>', html=True)
        self.assertContains(response, 'Used: <strong>72.0%</strong>', html=True)
        self.assertContains(response, 'Free: <strong>28.00 GB</strong>', html=True)
        self.assertContains(response, '🟡 Warning')

    @patch('dashboard.views.get_dashboard_context')
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
            'valuation_consistency': {
                'portfolio_value': Decimal('25.50'),
                'lots_value': Decimal('24.75'),
                'drift_value': Decimal('0.75'),
                'portfolio_missing_price_count': 0,
                'lots_missing_price_count': 0,
                'missing_price_count': 0,
                'has_missing_prices': False,
                'portfolio_rows_count': 2,
                'open_lots_symbol_count': 2,
                'dust_positions_count': 1,
            },
            'fee_summary': {
                'asset_count': 1,
                'fill_count': 2,
                'rows': [{'asset': 'USDT', 'total': Decimal('0.25'), 'fill_count': 2}],
            },
            'quote_fee_summary': {
                'total_fees_usdt': Decimal('0.25'),
                'total_operations': 2,
                'by_side': {
                    'BUY': {'total_fee_usdt': Decimal('0.10'), 'operations_count': 1},
                    'SELL': {'total_fee_usdt': Decimal('0.15'), 'operations_count': 1},
                },
            },
            'performance_kpis': {
                'gross_realized_pnl': Decimal('12.50'),
                'total_fees_usdt': Decimal('0.25'),
                'net_realized_pnl': Decimal('12.25'),
                'closures_count': 2,
                'winning_closures_count': 1,
                'losing_closures_count': 1,
                'breakeven_closures_count': 0,
                'win_rate': Decimal('50'),
                'average_win': Decimal('15.00'),
                'average_loss': Decimal('-2.50'),
                'profit_factor': Decimal('6'),
                'gross_deployed_capital': Decimal('120.00'),
                'bot_realized_pnl': Decimal('12.50'),
                'manual_adjustment_pnl': Decimal('0'),
                'manual_corrections_split_available': False,
                'manual_corrections_note': 'Manual/accounting corrections are split only when identifiable from trade operation metadata; otherwise realized PnL remains included in totals.',
                'fee_limitations_note': 'USDT fees use fee_amount_in_quote for FILLED USDT-quote operations. Fees that cannot be normalized to USDT are excluded.',
                'pnl_by_symbol': [
                    {'symbol': 'BTCUSDT', 'realized_pnl': Decimal('12.50'), 'closures_count': 2},
                ],
                'pnl_by_day': [
                    {
                        'date': timezone.datetime(2026, 5, 1, tzinfo=datetime_timezone.utc).date(),
                        'realized_pnl': Decimal('12.50'),
                        'closures_count': 2,
                    },
                ],
            },
            'latest_trade': {
                'row': SimpleNamespace(
                    side='BUY',
                    symbol='BTCUSDT',
                    status='FILLED',
                    executed_base_qty=Decimal('0.001'),
                    executed_at=timezone.now(),
                ),
                'gross_qu…27371 tokens truncated…tegy_row = result['strategy_summary'][0]
        churn_row = result['churn']['by_strategy_version'][0]
        self.assertEqual(strategy_row['closed_trades_count'], 1)
        self.assertEqual(strategy_row['eligible_filled_sell_count'], 2)
        self.assertEqual(strategy_row['churn_frequency'], Decimal('50'))
        self.assertEqual(strategy_row['churn_frequency'], churn_row['same_symbol_reentry_frequency'])

    def test_operational_kpis_calculate_hold_buckets_churn_and_safe_fee_ratios(self):
        now = timezone.datetime(2026, 5, 17, 12, tzinfo=datetime_timezone.utc)
        result = _calculate_operational_kpis(
            closure_rows=[
                {'trade_operation_id': 1, 'lot_id': 'lot-1', 'realized_pnl': Decimal('5')},
                {'trade_operation_id': 2, 'lot_id': 'lot-2', 'realized_pnl': Decimal('-8')},
            ],
            sell_operations={
                1: {'id': 1, 'symbol': 'BTCUSDT', 'timestamp': now - timezone.timedelta(hours=3), 'strategy_version': 'v2', 'fee_amount_in_quote': Decimal('1'), 'manual_correction': False, 'sell_reason': 'take_profit_reached'},
                2: {'id': 2, 'symbol': 'ETHUSDT', 'timestamp': now - timezone.timedelta(hours=2), 'strategy_version': 'v2', 'fee_amount_in_quote': Decimal('1'), 'manual_correction': False, 'sell_reason': 'stop_loss_reached'},
            },
            opened_lots={
                'lot-1': now - timezone.timedelta(hours=4),
                'lot-2': now - timezone.timedelta(hours=2, minutes=10),
            },
            operations=[
                {'id': 1, 'symbol': 'BTCUSDT', 'side': 'SELL', 'timestamp': now - timezone.timedelta(hours=3), 'strategy_version': 'v2', 'manual_correction': False, 'sell_reason': 'take_profit_reached'},
                {'id': 11, 'symbol': 'BTCUSDT', 'side': 'BUY', 'timestamp': now - timezone.timedelta(hours=2, minutes=30), 'strategy_version': 'v2', 'manual_correction': False},
                {'id': 2, 'symbol': 'ETHUSDT', 'side': 'SELL', 'timestamp': now - timezone.timedelta(hours=2), 'strategy_version': 'v2', 'manual_correction': False, 'sell_reason': 'stop_loss_reached'},
                {'id': 12, 'symbol': 'ETHUSDT', 'side': 'BUY', 'timestamp': now - timezone.timedelta(hours=1, minutes=30), 'strategy_version': 'v2', 'manual_correction': False},
            ],
            churn_threshold_minutes=60,
        )

        self.assertEqual(result['hold_time']['closed_under_15m_count'], 1)
        self.assertEqual(result['hold_time']['buckets']['<15m'], 1)
        self.assertEqual(result['hold_time']['buckets']['1h-4h'], 1)
        self.assertEqual(result['churn']['eligible_filled_sell_count'], 2)
        self.assertEqual(result['churn']['same_symbol_reentry_count'], 2)
        self.assertEqual(result['churn']['stop_loss_reentry_churn_count'], 1)
        self.assertEqual(result['fee_efficiency']['gross_profit'], Decimal('5'))
        self.assertEqual(result['fee_efficiency']['net_realized_pnl'], Decimal('-5'))
        self.assertEqual(result['fee_efficiency']['fees_over_gross_profit'], Decimal('40'))
        self.assertEqual(result['fee_efficiency']['fees_over_absolute_net_pnl'], Decimal('40'))

    def test_operational_kpis_ignore_missing_timestamps_and_hide_misleading_fee_ratios(self):
        result = _calculate_operational_kpis(
            closure_rows=[
                {'trade_operation_id': 1, 'lot_id': 'lot-1', 'realized_pnl': Decimal('-1')},
            ],
            sell_operations={
                1: {'id': 1, 'symbol': 'BTCUSDT', 'timestamp': None, 'strategy_version': 'v2', 'fee_amount_in_quote': Decimal('0.5'), 'manual_correction': False},
            },
            opened_lots={'lot-1': timezone.now()},
            operations=[
                {'id': 1, 'symbol': 'BTCUSDT', 'side': 'SELL', 'timestamp': None, 'strategy_version': 'v2', 'manual_correction': False},
                {'id': 2, 'symbol': 'BTCUSDT', 'side': 'BUY', 'timestamp': timezone.now(), 'strategy_version': 'v2', 'manual_correction': False},
            ],
            churn_threshold_minutes=60,
        )

        self.assertIsNone(result['hold_time']['average_hold_duration'])
        self.assertEqual(result['churn']['eligible_filled_sell_count'], 0)
        self.assertIsNone(result['fee_efficiency']['fees_over_gross_profit'])
        self.assertEqual(result['fee_efficiency']['fees_over_absolute_net_pnl'], Decimal('33.33333333333333333333333333'))

    def test_analytics_context_is_cached_for_60_seconds(self):
        from dashboard.dashboard_read_model import get_dashboard_analytics_context
        from django.core.cache import cache

        cache.clear()
        with patch('dashboard.dashboard_read_model.get_dashboard_context') as context_builder:
            context_builder.return_value = SimpleNamespace(context={'performance_kpis': {'net_realized_pnl': Decimal('1')}})

            first = get_dashboard_analytics_context()
            second = get_dashboard_analytics_context()

        self.assertEqual(first.context, second.context)
        context_builder.assert_called_once_with(include_performance_kpis=True)

    def test_compact_performance_kpis_skip_history_tables(self):
        summary = _calculate_performance_kpis(
            [{'trade_operation_id': 1, 'realized_pnl': Decimal('3')}],
            {1: {'symbol': 'BTCUSDT', 'timestamp': timezone.now(), 'manual_correction': False}},
            [],
            [],
            include_history=False,
        )

        self.assertEqual(summary['gross_realized_pnl'], Decimal('3'))
        self.assertEqual(summary['pnl_by_symbol'], [])
        self.assertEqual(summary['pnl_by_day'], [])

    def test_dashboard_profile_flag_is_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_dashboard_profile_enabled())
        with patch.dict(os.environ, {'DASHBOARD_PROFILE': 'true'}):
            self.assertTrue(_dashboard_profile_enabled())

    def test_dashboard_context_works_when_profile_enabled(self):
        with patch.dict(os.environ, {'DASHBOARD_PROFILE': 'true'}):
            with patch('dashboard.dashboard_read_model._ensure_dashboard_profile_console_logging'):
                with patch('dashboard.dashboard_read_model.Portfolio.objects') as portfolio_manager:
                    portfolio_manager.all.return_value.order_by.return_value = []
                    with patch('dashboard.dashboard_read_model._build_bot_status', return_value={}):
                        with patch('dashboard.dashboard_read_model._build_fee_summary', return_value={}):
                            with patch('dashboard.dashboard_read_model._build_quote_fee_summary', return_value={}):
                                with patch('dashboard.dashboard_read_model._build_performance_kpis', return_value={}):
                                    with patch('dashboard.dashboard_read_model._build_recent_operations', return_value=[]):
                                        with patch('dashboard.dashboard_read_model._build_latest_trade_from_recent_operations', return_value=None):
                                            with patch('dashboard.dashboard_read_model._open_lots_by_symbol', return_value={}):
                                                with patch(
                                                    'dashboard.dashboard_read_model.get_dust_overview_context',
                                                    return_value={'data_error': None},
                                                ):
                                                    read_model = get_dashboard_context()

        self.assertEqual(read_model.context['position_exit_status']['rows'], [])

    def test_dashboard_profile_enables_local_console_logger(self):
        logger = logging.getLogger('dashboard.dashboard_read_model')
        existing_handlers = list(logger.handlers)
        existing_level = logger.level
        existing_propagate = logger.propagate
        try:
            logger.handlers = []
            logger.setLevel(logging.NOTSET)
            logger.propagate = True

            _ensure_dashboard_profile_console_logging()

            self.assertEqual(logger.level, logging.INFO)
            self.assertFalse(logger.propagate)
            self.assertTrue(any(getattr(handler, '_dashboard_profile_handler', False) for handler in logger.handlers))
        finally:
            logger.handlers = existing_handlers
            logger.setLevel(existing_level)
            logger.propagate = existing_propagate

    def test_position_exit_suggested_action_mapping(self):
        self.assertEqual(
            _position_exit_suggested_action(['quantity_below_min_qty']),
            'Dust: review/ignore or wait until reusable',
        )
        self.assertEqual(
            _position_exit_suggested_action(['stop_loss_not_reached', 'take_profit_not_reached']),
            'Hold: strategy thresholds not reached',
        )
        self.assertEqual(
            _position_exit_suggested_action(['exchange_filter_missing']),
            'Review exchange metadata',
        )

    def test_position_exit_reason_mapping_uses_requested_labels(self):
        open_lots = {
            'XRPUSDT': {'symbol': 'XRPUSDT', 'open_quantity': Decimal('4.56'), 'open_lot_count': 1},
            'ADAUSDT': {'symbol': 'ADAUSDT', 'open_quantity': Decimal('10'), 'open_lot_count': 1},
            'ETHUSDT': {'symbol': 'ETHUSDT', 'open_quantity': Decimal('0.0001'), 'open_lot_count': 1},
            'ORDIUSDT': {'symbol': 'ORDIUSDT', 'open_quantity': Decimal('3'), 'open_lot_count': 1},
        }
        portfolio_rows = [
            SimpleNamespace(symbol='XRPUSDT', asset='XRP', quantity=Decimal('4.56'), current_price=Decimal('1')),
            SimpleNamespace(symbol='ADAUSDT', asset='ADA', quantity=Decimal('10'), current_price=Decimal('1')),
            SimpleNamespace(symbol='ETHUSDT', asset='ETH', quantity=Decimal('0.0001'), current_price=Decimal('2000')),
            SimpleNamespace(symbol='ORDIUSDT', asset='ORDI', quantity=Decimal('3'), current_price=Decimal('6')),
        ]
        sell_events = {
            'XRPUSDT': SimpleNamespace(
                reason='stop_loss_not_reached',
                estimated_pnl_percent=Decimal('-0.14'),
                current_price=Decimal('1'),
                payload={},
                created_at=timezone.now(),
            ),
            'ETHUSDT': SimpleNamespace(
                reason='rounded_quantity_zero',
                estimated_pnl_percent=None,
                current_price=Decimal('2000'),
                payload={},
                created_at=timezone.now(),
            ),
            'ADAUSDT': SimpleNamespace(
                reason='take_profit_not_reached',
                estimated_pnl_percent=Decimal('1.25'),
                current_price=Decimal('1'),
                payload={},
                created_at=timezone.now(),
            ),
            'ORDIUSDT': SimpleNamespace(
                reason='insufficient_binance_balance',
                estimated_pnl_percent=None,
                current_price=Decimal('6'),
                payload={},
                created_at=timezone.now(),
            ),
        }

        rows = {row['symbol']: row for row in _build_position_exit_status(open_lots, portfolio_rows, sell_events)['rows']}

        self.assertEqual(rows['XRPUSDT']['status_label'], 'Holding')
        self.assertIn('Stop loss has not been reached', rows['XRPUSDT']['interpretation'])
        self.assertEqual(rows['ADAUSDT']['status_label'], 'Holding')
        self.assertIn('Take profit has not been reached yet', rows['ADAUSDT']['interpretation'])
        self.assertEqual(rows['ETHUSDT']['status_label'], 'Dust / Unsellable')
        self.assertEqual(rows['ORDIUSDT']['status_label'], 'Drift / Review needed')

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
            'valuation_consistency': {
                'portfolio_value': Decimal('0'),
                'lots_value': Decimal('0'),
                'drift_value': Decimal('0'),
                'portfolio_missing_price_count': 0,
                'lots_missing_price_count': 0,
                'missing_price_count': 0,
                'has_missing_prices': False,
                'portfolio_rows_count': 0,
                'open_lots_symbol_count': 0,
                'dust_positions_count': 0,
            },
            'fee_summary': {
                'asset_count': 0,
                'fill_count': 0,
                'rows': [],
            },
            'quote_fee_summary': {
                'total_fees_usdt': Decimal('0'),
                'total_operations': 0,
                'by_side': {
                    'BUY': {'total_fee_usdt': Decimal('0'), 'operations_count': 0},
                    'SELL': {'total_fee_usdt': Decimal('0'), 'operations_count': 0},
                },
            },
            'performance_kpis': {
                'gross_realized_pnl': Decimal('0'),
                'total_fees_usdt': Decimal('0'),
                'net_realized_pnl': Decimal('0'),
                'closures_count': 0,
                'winning_closures_count': 0,
                'losing_closures_count': 0,
                'breakeven_closures_count': 0,
                'win_rate': None,
                'average_win': None,
                'average_loss': None,
                'profit_factor': None,
                'gross_deployed_capital': Decimal('0'),
                'bot_realized_pnl': Decimal('0'),
                'manual_adjustment_pnl': Decimal('0'),
                'manual_corrections_split_available': False,
                'manual_corrections_note': 'Manual/accounting corrections are split only when identifiable from trade operation metadata; otherwise realized PnL remains included in totals.',
                'fee_limitations_note': 'USDT fees use fee_amount_in_quote for FILLED USDT-quote operations. Fees that cannot be normalized to USDT are excluded.',
                'pnl_by_symbol': [],
                'pnl_by_day': [],
            },
            'latest_trade': {'row': None, 'gross_quote': None, 'net_quote': None},
            'reconciliation': {
                'status': 'ok',
                'warning_count': 0,
                'warnings': [],
                'checked_count': 0,
                'tolerance': Decimal('0.00000001'),
            },
            'dust_summary': {
                'total_detections': 0,
                'critical_count': 0,
                'warning_count': 0,
                'info_count': 0,
                'latest_run_id': None,
                'latest_detected_at': None,
                'top_grouped_detections': [],
                'total_estimated_value_usdt': Decimal('0'),
                'informational_residuals': {
                    'count': 0,
                    'total_estimated_value_usdt': Decimal('0'),
                    'latest_detected_at': None,
                },
                'data_error': None,
            },
            'position_exit_status': {
                'rows': [],
                'material_count': 0,
                'dust_count': 0,
                'diagnostics_loaded': False,
                'data_error': None,
            },
            'inventory_scope': {
                'spot_assets_count': None,
                'bot_managed_lot_symbols_count': 0,
                'material_tradable_positions_count': 0,
                'dust_non_tradable_positions_count': 0,
                'excluded_balances_count': 0,
                'excluded_balances': [],
            },
            'data_error': None,
            'is_demo': False,
            'disk_usage': {
                'available': False,
                'filesystem': '/',
                'total_bytes': None,
                'used_bytes': None,
                'free_bytes': None,
                'used_percent': None,
                'free_gb': None,
                'status': 'unavailable',
                'status_label': 'Unavailable',
                'status_icon': '',
                'badge_class': 'badge-secondary',
                'source': None,
                'source_label': 'Unavailable',
            },
        }


class ManualCorrectionWorkflowTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(ManualCorrection)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(ManualCorrection)
        super().tearDownClass()

    def setUp(self):
        ManualCorrection.objects.all().delete()
        self.client = Client()
        self.url = reverse('manual_correction_new')
        self.user = get_user_model().objects.create_user(
            email='reviewer@example.com',
            password='TestPassword123',
            name='Reviewer User',
        )
        self.staff_user = get_user_model().objects.create_user(
            email='staff-reviewer@example.com',
            password='TestPassword123',
            name='Staff Reviewer',
            is_staff=True,
        )
        self.payload = {
            'correction_type': ManualCorrection.TYPE_CLOSE_LOTS_EXTERNAL_SELL,
            'symbol': 'BTCUSDT',
            'asset': 'BTC',
            'quantity': '0.000100000000000000',
            'price_usdt': '60000.000000000000000000',
            'reason': 'Manual Binance sell left lot accounting drift',
            'source_detection_id': '99',
            'review_note': 'Requested from dust review',
        }

    def test_unauthenticated_user_cannot_create_correction(self):
        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(ManualCorrection.objects.count(), 0)

    def test_non_staff_user_cannot_create_correction(self):
        self.client.force_login(self.user)

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(ManualCorrection.objects.count(), 0)

    def test_staff_user_can_create_pending_correction(self):
        self.client.force_login(self.staff_user)

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 302)
        correction = ManualCorrection.objects.get()
        self.assertEqual(correction.status, ManualCorrection.STATUS_PENDING)
        self.assertEqual(correction.correction_type, ManualCorrection.TYPE_CLOSE_LOTS_EXTERNAL_SELL)
        self.assertEqual(correction.symbol, 'BTCUSDT')
        self.assertEqual(correction.asset, 'BTC')
        self.assertEqual(correction.requested_by, 'staff-reviewer@example.com')
        self.assertEqual(correction.estimated_value_usdt, Decimal('6.000000000000000000000000000000000000'))
        self.assertEqual(correction.payload['source'], 'django_dashboard')

    def test_manual_correction_model_matches_bot_table_fields(self):
        fields = [field.name for field in ManualCorrection._meta.fields]

        self.assertEqual(fields, [
            'id',
            'created_at',
            'applied_at',
            'status',
            'correction_type',
            'symbol',
            'asset',
            'quantity',
            'price_usdt',
            'estimated_value_usdt',
            'reason',
            'requested_by',
            'reviewed_by',
            'review_note',
            'source_detection_id',
            'payload',
            'error_message',
        ])
        self.assertFalse(ManualCorrection._meta.managed)

    def test_create_form_does_not_expose_status_or_applied_fields(self):
        form = ManualCorrectionRequestForm()

        self.assertNotIn('status', form.fields)
        self.assertNotIn('applied_at', form.fields)
        self.assertNotIn('estimated_value_usdt', form.fields)

    def test_lots_greater_than_spot_prefills_quantity_to_close(self):
        quantity = _manual_correction_quantity({
            'latest_open_lot_quantity': Decimal('0.005'),
            'latest_spot_quantity': Decimal('0.002'),
            'latest_quantity_delta': Decimal('-99'),
        })

        self.assertEqual(quantity, Decimal('0.003'))

    def test_negative_quantity_delta_does_not_prefill_negative_quantity(self):
        quantity = _manual_correction_quantity({
            'latest_open_lot_quantity': None,
            'latest_spot_quantity': None,
            'latest_quantity_delta': Decimal('-0.003'),
        })

        self.assertEqual(quantity, Decimal('0.003'))

    def test_quantity_prefill_is_blank_when_drift_is_not_lots_greater_than_spot(self):
        self.assertEqual(_manual_correction_quantity({
            'latest_open_lot_quantity': Decimal('0.002'),
            'latest_spot_quantity': Decimal('0.005'),
            'latest_quantity_delta': Decimal('-99'),
        }), '')
        self.assertEqual(_manual_correction_quantity({
            'latest_quantity_delta': Decimal('0.003'),
        }), '')

    def test_correction_form_validates_positive_decimal_quantity(self):
        payload = dict(self.payload)
        payload['quantity'] = '0'

        form = ManualCorrectionRequestForm(data=payload)

        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)

        payload['quantity'] = '-0.0001'
        form = ManualCorrectionRequestForm(data=payload)

        self.assertFalse(form.is_valid())
        self.assertIn('quantity', form.errors)

    def test_get_confirmation_page_does_not_create_correction(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This does not execute Binance orders.')
        self.assertEqual(ManualCorrection.objects.count(), 0)

    @patch('dashboard.views.ManualCorrection.save', side_effect=DatabaseError('duplicate correction'))
    def test_bot_side_duplicate_rejection_error_is_user_friendly(self, mock_save):
        self.client.force_login(self.staff_user)

        response = self.client.post(self.url, self.payload)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'The correction request could not be saved.')
        self.assertContains(response, 'The bot remains the source of truth for duplicate correction validation.')
        self.assertEqual(ManualCorrection.objects.count(), 0)


class BuyStatusPnlSummaryTests(TestCase):
    def _render(
        self,
        *,
        portfolio_rows=None,
        material_symbols=None,
        realized_today=Decimal('0'),
    ):
        from dashboard.services.telegram_buy_status_formatter import (
            build_open_positions_pnl,
            render_buy_status_message,
        )

        portfolio_rows = portfolio_rows or []
        material_symbols = material_symbols or [row.symbol for row in portfolio_rows]
        exposure = build_buy_status_exposure(
            material_symbols,
            [],
            portfolio_rows,
        )
        return render_buy_status_message(
            emoji='🟢',
            raw_count=len(material_symbols),
            material_count=len(material_symbols),
            dust_count=0,
            unknown_count=0,
            effective_positions=len(material_symbols),
            max_positions=8,
            remaining_capacity=max(0, 8 - len(material_symbols)),
            free_usdt=Decimal('10'),
            latest_buy_state='available',
            latest_buy_reason='capacity_available',
            latest_buy_symbol=None,
            read_only=False,
            exposure=exposure,
            open_positions_pnl=build_open_positions_pnl(exposure),
            realized_today=realized_today,
            status_lines=['✅ Capacity available'],
        )

    def test_buy_status_pnl_renders_positive_realized_today(self):
        message = self._render(realized_today=Decimal('1.81'))

        self.assertIn('- Realized today (UTC): <code>+1.81 USDT</code>', message)

    def test_buy_status_pnl_renders_negative_realized_today(self):
        message = self._render(realized_today=Decimal('-1.81'))

        self.assertIn('- Realized today (UTC): <code>-1.81 USDT</code>', message)

    def test_buy_status_pnl_renders_zero_when_no_realized_trades_today(self):
        message = self._render(realized_today=Decimal('0'))

        self.assertIn('- Realized today (UTC): <code>+0.00 USDT</code>', message)

    def test_buy_status_pnl_combines_open_and_realized_values(self):
        message = self._render(
            portfolio_rows=[
                SimpleNamespace(
                    symbol='BTCUSDT',
                    quantity=Decimal('2'),
                    entry_price=Decimal('5'),
                    current_price=Decimal('5.05'),
                ),
                SimpleNamespace(
                    symbol='ETHUSDT',
                    quantity=Decimal('1'),
                    entry_price=Decimal('10'),
                    current_price=Decimal('9.95'),
                ),
            ],
            realized_today=Decimal('-1.81'),
        )

        self.assertIn('<b>PnL</b>', message)
        self.assertIn('- Open positions: <code>+0.05 USDT</code>', message)
        self.assertIn('- Realized today (UTC): <code>-1.81 USDT</code>', message)

    def test_buy_status_pnl_empty_portfolio_reports_zero_open_pnl(self):
        message = self._render()

        self.assertIn('- Open positions: <code>+0.00 USDT</code>', message)

    def test_buy_status_invalid_and_non_positive_prices_are_unavailable(self):
        from dashboard.services.telegram_buy_status_formatter import classify_buy_status_positions

        rows = [
            SimpleNamespace(symbol='ZEROUSDT', quantity=Decimal('1'), current_price=Decimal('0')),
            SimpleNamespace(symbol='BADUSDT', quantity=Decimal('1'), current_price='not-a-price'),
            SimpleNamespace(symbol='NANUSDT', quantity=Decimal('1'), current_price=Decimal('NaN')),
            SimpleNamespace(symbol='INFUSDT', quantity=Decimal('1'), current_price=Decimal('Infinity')),
        ]

        classification = classify_buy_status_positions(rows)

        self.assertEqual(classification['material_rows'], [])
        self.assertEqual(classification['dust_rows'], [])
        self.assertEqual(
            classification['unknown_symbols'],
            ['ZEROUSDT', 'BADUSDT', 'NANUSDT', 'INFUSDT'],
        )

    def test_buy_status_telegram_message_stays_within_limit_and_keeps_valid_html(self):
        from html.parser import HTMLParser
        from dashboard.services.telegram_buy_status_formatter import (
            build_open_positions_pnl,
            render_buy_status_message,
        )

        symbols = [f'ASSET{index:04d}USDT' for index in range(700)]
        exposure = build_buy_status_exposure([], [], [])
        message = render_buy_status_message(
            emoji='🟢', raw_count=700, material_count=0, dust_count=0,
            unknown_count=700, effective_positions=700, max_positions=8,
            remaining_capacity=0, free_usdt=Decimal('0'),
            latest_buy_state='unavailable', latest_buy_reason='unavailable',
            latest_buy_symbol=None, read_only=False, exposure=exposure,
            status_lines=['⚠️ ' + 'details ' * 900], open_positions_pnl=Decimal('0'),
            realized_today=Decimal('0'), unknown_value_symbols=symbols,
        )

        class TagTracker(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []

            def handle_starttag(self, tag, attrs):
                self.stack.append(tag)

            def handle_endtag(self, tag):
                self.assert_tag = tag
                if self.stack and self.stack[-1] == tag:
                    self.stack.pop()
                else:
                    raise AssertionError(f'unbalanced HTML closing tag: {tag}')

        parser = TagTracker()
        parser.feed(message)
        parser.close()
        self.assertLessEqual(len(message), 4096)
        self.assertEqual(parser.stack, [])
        self.assertIn('Additional diagnostics omitted', message)
        self.assertIn('<b>Latest BUY</b>', message)
        self.assertIn('Effective positions: <code>700 / 8</code>', message)

    def test_buy_status_length_fallback_preserves_operational_fields_and_escapes_multiline(self):
        from html.parser import HTMLParser
        from dashboard.services.telegram_buy_status_formatter import render_buy_status_message

        exposure = build_buy_status_exposure([], [], [])
        message = render_buy_status_message(
            emoji='🟢', raw_count=2, material_count=1, dust_count=1,
            unknown_count=0, effective_positions=1, max_positions=8,
            remaining_capacity=7, free_usdt=Decimal('12'),
            latest_buy_state='available', latest_buy_reason='no_candidate',
            latest_buy_symbol='BTCUSDT', read_only=False, exposure=exposure,
            status_lines=['line one\n<b>injected</b> ' + 'verbose ' * 1000],
            open_positions_pnl=Decimal('1.25'), realized_today=Decimal('-0.5'),
        )

        class StrictHTML(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack = []

            def handle_starttag(self, tag, attrs):
                self.stack.append(tag)

            def handle_endtag(self, tag):
                if not self.stack or self.stack.pop() != tag:
                    raise AssertionError(f'unbalanced HTML tag: {tag}')

        parser = StrictHTML()
        parser.feed(message)
        parser.close()
        self.assertEqual(parser.stack, [])
        self.assertLessEqual(len(message), 4096)
        for text in (
            '<b>Capacity</b>', '<b>Positions</b>', '<b>PnL</b>',
            '<b>Latest BUY</b>', '<b>Status</b>',
            'Effective positions: <code>1 / 8</code>',
            'Open positions: <code>+1.25 USDT</code>',
            'Realized today (UTC): <code>-0.50 USDT</code>',
            'Candidate: <code>BTCUSDT</code>',
            'Additional diagnostics omitted',
        ):
            self.assertIn(text, message)
        self.assertIn('&lt;b&gt;injected&lt;/b&gt;', message)

    def test_open_positions_pnl_includes_material_rows_beyond_display_cap(self):
        rows = [
            SimpleNamespace(
                symbol=f'ASSET{index}USDT',
                quantity=Decimal('1'),
                entry_price=Decimal('5'),
                current_price=Decimal('6'),
            )
            for index in range(9)
        ]

        message = self._render(portfolio_rows=rows)

        self.assertIn('- Open positions: <code>+9.00 USDT</code>', message)
        self.assertEqual(message.count(' | PnL '), 8)
        self.assertIn('- ... and 1 more', message)

    def test_open_positions_pnl_helper_sums_every_material_row(self):
        from dashboard.services.telegram_buy_status_formatter import (
            build_open_positions_pnl,
        )

        exposure = {
            'material_rows': [
                {
                    'symbol': f'ASSET{index}USDT',
                    'quantity': Decimal('1'),
                    'entry_price': Decimal('5'),
                    'current_price': Decimal('6'),
                }
                for index in range(9)
            ],
            'material_unavailable_symbols': [],
        }

        self.assertEqual(build_open_positions_pnl(exposure), Decimal('9'))

    def test_realized_today_label_explicitly_names_utc(self):
        message = self._render(realized_today=Decimal('1.81'))

        self.assertIn('Realized today (UTC):', message)
        self.assertNotIn('- Realized today: <code>', message)

    def test_open_positions_pnl_is_unavailable_when_material_entry_price_is_missing(self):
        message = self._render(portfolio_rows=[
            SimpleNamespace(
                symbol='BTCUSDT',
                quantity=Decimal('1'),
                entry_price=None,
                current_price=Decimal('10'),
            ),
        ])

        self.assertIn('- BTCUSDT ~ 10 USDT | PnL unavailable', message)
        self.assertIn('- Open positions: <code>unavailable</code>', message)

    def test_open_positions_pnl_is_unavailable_when_entry_price_is_non_finite(self):
        message = self._render(portfolio_rows=[
            SimpleNamespace(
                symbol='BTCUSDT',
                quantity=Decimal('1'),
                entry_price=Decimal('NaN'),
                current_price=Decimal('10'),
            ),
        ])

        self.assertIn('- BTCUSDT ~ 10 USDT | PnL unavailable', message)
        self.assertIn('- Open positions: <code>unavailable</code>', message)

    def test_open_positions_pnl_is_unavailable_when_material_valuation_is_missing(self):
        message = self._render(
            portfolio_rows=[],
            material_symbols=['BTCUSDT'],
        )

        self.assertIn('- Valuation unavailable: <code>BTCUSDT</code>', message)
        self.assertIn('- Open positions: <code>unavailable</code>', message)

    def test_buy_status_existing_section_order_remains_stable(self):
        message = self._render()

        self.assertLess(message.index('<b>Capacity</b>'), message.index('<b>Positions</b>'))
        self.assertLess(message.index('<b>Positions</b>'), message.index('<b>Material exposure'))
        self.assertLess(message.index('<b>Material exposure'), message.index('<b>PnL</b>'))
        self.assertLess(message.index('<b>PnL</b>'), message.index('<b>Dust exposure</b>'))
        self.assertLess(message.index('<b>Dust exposure</b>'), message.index('<b>Latest BUY</b>'))
        self.assertLess(message.index('<b>Latest BUY</b>'), message.index('<b>Status</b>'))
        self.assertIn(
            '<b>PnL</b>\n'
            '- Open positions: <code>+0.00 USDT</code>\n'
            '- Realized today (UTC): <code>+0.00 USDT</code>\n\n'
            '<b>Dust exposure</b>',
            message,
        )

    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('-1.81'))
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_format_buy_status_wires_open_and_realized_pnl(
        self,
        mock_health_manager,
        mock_portfolio_manager,
        _mock_realized_today,
    ):
        from core.telegram_diagnostics import format_buy_status

        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            details={
                'positions_count': 1,
                'material_positions_count': 1,
                'dust_positions_count': 0,
                'unknown_value_positions_count': 0,
                'material_symbols': ['BTCUSDT'],
                'dust_symbols': [],
                'unknown_value_symbols': [],
                'max_positions': 8,
            },
        )
        mock_portfolio_manager.filter.return_value = [
            SimpleNamespace(
                symbol='BTCUSDT',
                quantity=Decimal('2'),
                entry_price=Decimal('5'),
                current_price=Decimal('5.05'),
            ),
        ]

        message = format_buy_status()

        self.assertIn('- Open positions: <code>+0.10 USDT</code>', message)
        self.assertIn('- Realized today (UTC): <code>-1.81 USDT</code>', message)

    @patch('core.telegram_diagnostics.LotClosure.objects')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    def test_realized_today_uses_utc_boundaries_and_operation_timestamp_fallback(
        self,
        mock_trade_manager,
        mock_closure_manager,
    ):
        from core.telegram_diagnostics import realized_pnl_for_day

        operation_ids = [101, 102]
        mock_trade_manager.filter.return_value.values_list.return_value = operation_ids
        mock_closure_manager.filter.return_value.aggregate.return_value = {
            'total': Decimal('-1.81'),
        }

        result = realized_pnl_for_day(timezone.datetime(2026, 6, 12).date())

        self.assertEqual(result, Decimal('-1.81'))
        query = mock_trade_manager.filter.call_args.args[0]
        start = timezone.datetime(2026, 6, 12, tzinfo=datetime_timezone.utc)
        end = timezone.datetime(2026, 6, 13, tzinfo=datetime_timezone.utc)
        cases = [
            ({'executed_at': start, 'created_at': start}, True),
            ({'executed_at': end, 'created_at': start}, False),
            ({'executed_at': start - timezone.timedelta(seconds=1), 'created_at': start}, False),
            ({'executed_at': None, 'created_at': start}, True),
            ({'executed_at': None, 'created_at': end}, False),
        ]
        for operation, expected in cases:
            with self.subTest(operation=operation):
                self.assertEqual(self._matches_query(query, operation), expected)
        mock_closure_manager.filter.assert_called_once_with(
            trade_operation_id__in=operation_ids,
        )
        for manager in [mock_trade_manager, mock_closure_manager]:
            manager.create.assert_not_called()
            manager.bulk_create.assert_not_called()
            manager.update_or_create.assert_not_called()
            manager.filter.return_value.update.assert_not_called()

    def _matches_query(self, query, values):
        child_results = []
        for child in query.children:
            if hasattr(child, 'children'):
                child_results.append(self._matches_query(child, values))
                continue
            lookup, expected = child
            field, _, operator = lookup.partition('__')
            actual = values[field]
            if operator == 'gte':
                child_results.append(actual is not None and actual >= expected)
            elif operator == 'lt':
                child_results.append(actual is not None and actual < expected)
            elif operator == 'isnull':
                child_results.append((actual is None) is expected)
            else:
                self.fail(f'Unsupported query lookup in test: {lookup}')
        result = all(child_results) if query.connector == 'AND' else any(child_results)
        return not result if query.negated else result


class TelegramPortfolioStatusTests(TestCase):
    def _lot(self, symbol, quantity, entry_price):
        return SimpleNamespace(
            symbol=symbol,
            remaining_quantity=Decimal(quantity),
            entry_price=None if entry_price is None else Decimal(entry_price),
        )

    def _portfolio(self, symbol, current_price, updated_at=None):
        return SimpleNamespace(
            symbol=symbol,
            current_price=None if current_price is None else Decimal(current_price),
            updated_at=updated_at,
        )

    def _snapshot(self, created_at, equity):
        return self._canonical_snapshot(created_at, equity)

    def _snapshot_row(self, created_at, row_id, equity='100'):
        row = self._canonical_snapshot(created_at, equity)
        row.id = row_id
        return row

    def _snapshot_manager(self, rows):
        class SnapshotQuery:
            def __init__(self, source_rows):
                self.rows = source_rows
                self.filter_kwargs = None
                self.ordering = None
                self.slice = None

            def filter(self, **kwargs):
                self.filter_kwargs = kwargs
                return self

            def order_by(self, *fields):
                self.ordering = fields
                reverse = fields[0].startswith('-')
                self.rows = sorted(
                    self.rows,
                    key=lambda row: (row.created_at, row.id),
                    reverse=reverse,
                )
                return self

            def __getitem__(self, value):
                self.slice = value
                return self.rows[value]

        return SnapshotQuery(rows)

    def test_bounded_snapshot_query_returns_all_fewer_than_limit_in_chronological_order(self):
        from core.telegram_diagnostics import _bounded_portfolio_snapshot_rows

        now = timezone.now()
        query = self._snapshot_manager([
            self._snapshot_row(now - timezone.timedelta(minutes=5), 3),
            self._snapshot_row(now - timezone.timedelta(minutes=15), 1),
            self._snapshot_row(now - timezone.timedelta(minutes=10), 2),
        ])
        with patch('core.telegram_diagnostics.Snapshot.objects', query):
            rows = _bounded_portfolio_snapshot_rows(now, limit=5)

        self.assertEqual([row.id for row in rows], [1, 2, 3])
        self.assertEqual(query.ordering, ('-created_at', '-id'))
        self.assertEqual(query.slice, slice(None, 5, None))

    def test_bounded_snapshot_query_keeps_newest_rows_and_restores_chronology(self):
        from core.telegram_diagnostics import _bounded_portfolio_snapshot_rows

        now = timezone.now()
        query = self._snapshot_manager([
            self._snapshot_row(now - timezone.timedelta(minutes=index), index)
            for index in range(6)
        ])
        with patch('core.telegram_diagnostics.Snapshot.objects', query):
            rows = _bounded_portfolio_snapshot_rows(now, limit=3)

        self.assertEqual([row.id for row in rows], [2, 1, 0])
        self.assertNotIn(3, [row.id for row in rows])
        self.assertEqual(query.slice, slice(None, 3, None))

    def test_bounded_snapshot_query_uses_id_for_equal_timestamp_ordering(self):
        from core.telegram_diagnostics import _bounded_portfolio_snapshot_rows

        now = timezone.now()
        query = self._snapshot_manager([
            self._snapshot_row(now, 2),
            self._snapshot_row(now, 1),
            self._snapshot_row(now, 3),
        ])
        with patch('core.telegram_diagnostics.Snapshot.objects', query):
            rows = _bounded_portfolio_snapshot_rows(now, limit=2)

        self.assertEqual([row.id for row in rows], [2, 3])

    @override_settings(PORTFOLIO_STATUS_MAX_SNAPSHOTS=3)
    def test_portfolio_status_uses_fresh_snapshot_when_rows_exceed_limit(self):
        from core.telegram_diagnostics import format_portfolio_status

        now = timezone.now()
        query = self._snapshot_manager([
            self._snapshot_row(now - timezone.timedelta(days=10) + timezone.timedelta(minutes=index), index)
            for index in range(4)
        ] + [
            self._snapshot_row(now - timezone.timedelta(minutes=10), 9, '110'),
            self._snapshot_row(now - timezone.timedelta(minutes=5), 10, '120'),
        ])
        with patch('core.telegram_diagnostics.Snapshot.objects', query), \
             patch('core.telegram_diagnostics.BotHealthcheck.objects') as health, \
             patch('core.telegram_diagnostics.PositionLot.objects') as lots, \
             patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('0')), \
             patch('core.telegram_diagnostics._safe_realized_pnl_by_symbol_today', return_value=[]), \
             patch('core.telegram_diagnostics.timezone.now', return_value=now):
            health.order_by.return_value.first.return_value = None
            lots.filter.return_value.order_by.return_value = []
            result = format_portfolio_status()

        self.assertNotIn('Chart: unavailable, not enough history', result['text'])
        self.assertEqual(query.slice, slice(None, 3, None))

    @override_settings(PORTFOLIO_STATUS_MAX_SNAPSHOTS=0)
    def test_non_positive_snapshot_limit_falls_back_to_default_bound(self):
        from core.telegram_diagnostics import _portfolio_status_snapshot_limit

        self.assertEqual(_portfolio_status_snapshot_limit(), 512)

    def _canonical_snapshot(self, created_at, equity):
        return SimpleNamespace(
            created_at=created_at,
            source="bot_cycle",
            notes={"portfolio_equity_usdt": equity},
        )

    def _snapshot_with_source(self, created_at, equity, source):
        return SimpleNamespace(
            created_at=created_at,
            source=source,
            notes={"portfolio_equity_usdt": equity},
        )

    def _legacy_snapshot(self, created_at, data):
        return SimpleNamespace(
            created_at=created_at,
            data=data,
            notes={},
        )

    def _build(
        self,
        *,
        lots=None,
        portfolio=None,
        free_usdt='10',
        realized_today='0',
        realized_drivers=None,
        equity_history=None,
        as_of=None,
        stale_after=None,
    ):
        from dashboard.services.telegram_portfolio_status import build_portfolio_status

        return build_portfolio_status(
            open_lots=lots or [],
            portfolio_rows=portfolio or [],
            free_usdt=None if free_usdt is None else Decimal(free_usdt),
            realized_today=None if realized_today is None else Decimal(realized_today),
            realized_drivers=realized_drivers,
            equity_history=equity_history,
            as_of=as_of,
            stale_after=stale_after,
        )

    def test_empty_portfolio_reports_free_equity_and_zero_open_value(self):
        summary = self._build()

        self.assertEqual(summary['equity_usdt'], Decimal('10'))
        self.assertEqual(summary['open_value_usdt'], Decimal('0'))
        self.assertEqual(summary['unrealized_pnl_usdt'], Decimal('0'))
        self.assertEqual(summary['unrealized_pnl_pct'], Decimal('0'))
        self.assertIsNone(summary['best_contributor'])
        self.assertIsNone(summary['worst_contributor'])

    def test_equity_includes_valued_dust_but_contributors_remain_material_only(self):
        summary = self._build(
            lots=[self._lot('DUSTUSDT', '1', '0.5')],
            portfolio=[self._portfolio('DUSTUSDT', '1')],
        )

        self.assertEqual(summary['open_value_usdt'], Decimal('1'))
        self.assertEqual(summary['equity_usdt'], Decimal('11'))
        self.assertEqual(summary['unrealized_pnl_usdt'], Decimal('0'))
        self.assertIsNone(summary['best_contributor'])
        self.assertIsNone(summary['worst_contributor'])

    def test_positive_unrealized_pnl_uses_lot_quantity_and_projection_price(self):
        summary = self._build(
            lots=[self._lot('BTCUSDT', '2', '5')],
            portfolio=[self._portfolio('BTCUSDT', '6')],
        )

        self.assertEqual(summary['open_value_usdt'], Decimal('12'))
        self.assertEqual(summary['equity_usdt'], Decimal('22'))
        self.assertEqual(summary['unrealized_pnl_usdt'], Decimal('2'))
        self.assertEqual(summary['unrealized_pnl_pct'], Decimal('20'))
        self.assertEqual(summary['best_contributor']['symbol'], 'BTCUSDT')

    def test_negative_unrealized_pnl_is_preserved(self):
        summary = self._build(
            lots=[self._lot('WLDUSDT', '10', '1')],
            portfolio=[self._portfolio('WLDUSDT', '0.8')],
        )

        self.assertEqual(summary['unrealized_pnl_usdt'], Decimal('-2.0'))
        self.assertEqual(summary['unrealized_pnl_pct'], Decimal('-20.0'))

    def test_portfolio_status_renders_explicit_performance_sections(self):
        from dashboard.services.telegram_portfolio_status import render_portfolio_status

        summary = self._build(
            lots=[self._lot('BTCUSDT', '2', '5')],
            portfolio=[self._portfolio('BTCUSDT', '6')],
            realized_today='1.25',
        )

        message = render_portfolio_status(summary)

        self.assertIn('<b>Performance</b>', message)
        self.assertIn('<b>Portfolio equity</b>', message)
        self.assertIn('<b>Today&#x27;s trading (UTC)</b>', message)
        self.assertIn('<b>Open positions</b>', message)
        self.assertLess(message.index('<b>Performance</b>'), message.index('<b>Portfolio equity</b>'))
        self.assertLess(message.index('<b>Portfolio equity</b>'), message.index('<b>Today&#x27;s trading (UTC)</b>'))
        self.assertLess(message.index('<b>Today&#x27;s trading (UTC)</b>'), message.index('<b>Open positions</b>'))
        self.assertLess(message.index('<b>Portfolio equity</b>'), message.index('<b>24h equity drivers</b>'))
        self.assertLess(message.index('<b>24h equity drivers</b>'), message.index('<b>Today&#x27;s trading (UTC)</b>'))
        self.assertLess(message.index('<b>Open positions</b>'), message.index('<b>Current unrealized contributors</b>'))
        self.assertIn('- 24h: <code>unavailable</code>', message)
        self.assertIn('- 7d: <code>unavailable</code>', message)
        self.assertIn('- 30d: <code>unavailable</code>', message)
        self.assertIn('<b>24h equity drivers</b>', message)
        self.assertIn('unavailable', message)
        self.assertIn('- Realized PnL: <code>+1.25 USDT</code>', message)
        self.assertIn('- Unrealized now: <code>+2.00 USDT (+20.00%)</code>', message)
        self.assertNotIn('<b>PnL</b>', message)
        self.assertNotIn('<b>Change</b>', message)
        self.assertNotIn('<b>PnL context</b>', message)
        self.assertNotIn('<b>24h drivers</b>', message)
        self.assertNotIn('Realized today (UTC)', message)
        self.assertNotIn('- Unrealized: <code>', message)

    def test_portfolio_status_performance_keeps_unavailable_values(self):
        from dashboard.services.telegram_portfolio_status import render_portfolio_status

        summary = self._build(
            lots=[self._lot('BTCUSDT', '2', None)],
            portfolio=[self._portfolio('BTCUSDT', '6')],
            free_usdt=None,
            realized_today=None,
        )

        message = render_portfolio_status(summary)

        self.assertIn('- Equity: <code>unavailable</code>', message)
        self.assertIn('- Realized PnL: <code>unavailable</code>', message)
        self.assertIn('- Unrealized now: <code>unavailable</code>', message)

    def test_portfolio_status_performance_keeps_unavailable_for_empty_contributors(self):
        from dashboard.services.telegram_portfolio_status import render_portfolio_status

        summary = self._build()

        message = render_portfolio_status(summary)

        self.assertIn('- Best: <code>unavailable</code>', message)
        self.assertIn('- Worst: <code>unavailable</code>', message)
        self.assertIn('<b>Current unrealized contributors</b>', message)

    def test_missing_entry_price_makes_unrealized_and_contributors_unavailable(self):
        summary = self._build(
            lots=[self._lot('BTCUSDT', '2', None)],
            portfolio=[self._portfolio('BTCUSDT', '6')],
        )

        self.assertEqual(summary['open_value_usdt'], Decimal('12'))
        self.assertIsNone(summary['unrealized_pnl_usdt'])
        self.assertIsNone(summary['unrealized_pnl_pct'])
        self.assertIsNone(summary['best_contributor'])
        self.assertIsNone(summary['worst_contributor'])

    def test_missing_current_price_makes_equity_and_unrealized_unavailable(self):
        summary = self._build(
            lots=[self._lot('BTCUSDT', '2', '5')],
            portfolio=[self._portfolio('BTCUSDT', None)],
        )

        self.assertIsNone(summary['open_value_usdt'])
        self.assertIsNone(summary['equity_usdt'])
        self.assertIsNone(summary['unrealized_pnl_usdt'])
        self.assertEqual(summary['unavailable_symbols'], ['BTCUSDT'])

    def test_stale_current_price_makes_equity_and_unrealized_unavailable(self):
        now = timezone.now()
        summary = self._build(
            lots=[self._lot('BTCUSDT', '2', '5')],
            portfolio=[
                self._portfolio(
                    'BTCUSDT',
                    '6',
                    updated_at=now - timezone.timedelta(minutes=16),
                ),
            ],
            as_of=now,
            stale_after=timezone.timedelta(minutes=15),
        )

        self.assertIsNone(summary['open_value_usdt'])
        self.assertIsNone(summary['equity_usdt'])
        self.assertEqual(summary['unavailable_symbols'], ['BTCUSDT'])

    def test_best_and_worst_contributors_are_selected_by_unrealized_pnl(self):
        summary = self._build(
            lots=[
                self._lot('BTCUSDT', '2', '5'),
                self._lot('ETHUSDT', '5', '2'),
                self._lot('WLDUSDT', '10', '1'),
            ],
            portfolio=[
                self._portfolio('BTCUSDT', '6'),
                self._portfolio('ETHUSDT', '2.1'),
                self._portfolio('WLDUSDT', '0.8'),
            ],
        )

        self.assertEqual(summary['best_contributor']['symbol'], 'BTCUSDT')
        self.assertEqual(summary['best_contributor']['pnl_usdt'], Decimal('2'))
        self.assertEqual(summary['worst_contributor']['symbol'], 'WLDUSDT')
        self.assertEqual(summary['worst_contributor']['pnl_usdt'], Decimal('-2.0'))

    def test_render_marks_all_historical_changes_unavailable_without_verified_snapshots(self):
        from dashboard.services.telegram_portfolio_status import render_portfolio_status

        message = render_portfolio_status(self._build())

        self.assertIn('<b>📊 Portfolio status</b>', message)
        self.assertIn('- 24h: <code>unavailable</code>', message)
        self.assertIn('- 7d: <code>unavailable</code>', message)
        self.assertIn('- 30d: <code>unavailable</code>', message)

    def test_historical_change_24h_available_from_reliable_snapshots(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._snapshot(now - timezone.timedelta(hours=25), '100'),
            self._snapshot(now - timezone.timedelta(minutes=5), '125'),
        ])
        summary = self._build(equity_history=history)

        self.assertEqual(summary['changes']['24h']['amount_usdt'], Decimal('25'))
        self.assertEqual(summary['changes']['24h']['percent'], Decimal('25'))

    def test_portfolio_status_renders_24h_equity_drivers_unavailable_without_verified_symbol_source(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder, render_portfolio_status

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(hours=24), '100'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '105'),
        ])
        summary = self._build(
            lots=[
                self._lot('BTCUSDT', '10', '10'),
                self._lot('ETHUSDT', '10', '5'),
                self._lot('WLDUSDT', '10', '2'),
            ],
            portfolio=[
                self._portfolio('BTCUSDT', '9'),
                self._portfolio('ETHUSDT', '7'),
                self._portfolio('WLDUSDT', '1.5'),
            ],
            equity_history=history,
        )

        message = render_portfolio_status(summary)

        self.assertIn('<b>24h equity drivers</b>', message)
        self.assertIn('<b>24h equity drivers</b>\nunavailable', message)
        self.assertNotIn('Explained:', message)
        self.assertNotIn('Open-position contribution:', message)
        self.assertLess(message.index('<b>24h equity drivers</b>'), message.index('<b>Today&#x27;s trading (UTC)</b>'))

    def test_24h_equity_drivers_render_observational_contribution_label(self):
        from dashboard.services.telegram_portfolio_status import render_portfolio_status

        message = render_portfolio_status({
            "equity_usdt": Decimal("105"),
            "free_usdt": Decimal("10"),
            "open_value_usdt": Decimal("95"),
            "unrealized_pnl_usdt": Decimal("0"),
            "unrealized_pnl_pct": Decimal("0"),
            "realized_today": Decimal("0"),
            "changes": {"24h": {"amount_usdt": Decimal("5"), "percent": Decimal("5")}},
            "chart_available": True,
            "equity_drivers_24h": {
                "worst": {"symbol": "BTCUSDT", "delta_usdt": Decimal("-10"), "delta_pct": Decimal("-10")},
                "best": {"symbol": "ETHUSDT", "delta_usdt": Decimal("20"), "delta_pct": Decimal("40")},
                "open_position_contribution_usdt": Decimal("5"),
                "total_change_usdt": Decimal("5"),
            },
            "best_contributor": None,
            "worst_contributor": None,
        })

        self.assertIn('- Worst: BTCUSDT <code>-10.00 USDT (-10.00%)</code>', message)
        self.assertIn('- Best: ETHUSDT <code>+20.00 USDT (+40.00%)</code>', message)
        self.assertIn('- Open-position contribution: <code>+5.00 USDT of +5.00 USDT</code>', message)
        self.assertNotIn('Explained:', message)

    def test_24h_equity_drivers_unavailable_without_prior_symbol_values(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder, render_portfolio_status

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(hours=24), '100'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '90'),
        ])
        summary = self._build(
            lots=[self._lot('BTCUSDT', '10', '10')],
            portfolio=[self._portfolio('BTCUSDT', '9')],
            equity_history=history,
        )

        message = render_portfolio_status(summary)

        self.assertIsNone(summary['equity_drivers_24h'])
        self.assertIn('<b>24h equity drivers</b>\nunavailable', message)

    def test_24h_equity_drivers_do_not_change_equity_windows(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(hours=24), '100'),
            self._canonical_snapshot(now - timezone.timedelta(days=7), '80'),
            self._canonical_snapshot(now - timezone.timedelta(days=30), '50'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '120'),
        ])
        summary = self._build(
            lots=[self._lot('BTCUSDT', '10', '10')],
            portfolio=[self._portfolio('BTCUSDT', '12')],
            equity_history=history,
        )

        self.assertEqual(summary['changes']['24h']['amount_usdt'], Decimal('20'))
        self.assertEqual(summary['changes']['7d']['amount_usdt'], Decimal('40'))
        self.assertEqual(summary['changes']['30d']['amount_usdt'], Decimal('70'))
        self.assertIsNone(summary['equity_drivers_24h'])

    def test_snapshot_model_does_not_depend_on_portfolio_payload_column(self):
        from core.trading_models import Snapshot

        self.assertNotIn("portfolio", {field.name for field in Snapshot._meta.fields})

    def test_current_unrealized_contributors_are_not_labeled_as_24h_drivers(self):
        from dashboard.services.telegram_portfolio_status import render_portfolio_status

        message = render_portfolio_status(self._build(
            lots=[self._lot('BTCUSDT', '2', '5')],
            portfolio=[self._portfolio('BTCUSDT', '6')],
        ))

        self.assertIn('<b>24h equity drivers</b>\nunavailable', message)
        self.assertIn('<b>Current unrealized contributors</b>', message)
        self.assertNotIn('<b>Top contributors</b>', message)

    def test_historical_change_uses_canonical_snapshot_notes_equity(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(hours=25), '100'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '125'),
        ])
        summary = self._build(equity_history=history)

        self.assertEqual(summary['changes']['24h']['amount_usdt'], Decimal('25'))
        self.assertTrue(summary['chart_available'])

    def test_historical_change_uses_only_bot_cycle_source(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._snapshot_with_source(
                now - timezone.timedelta(hours=25),
                '1000',
                'portfolio_sync_from_api',
            ),
            self._canonical_snapshot(now - timezone.timedelta(hours=25), '100'),
            self._snapshot_with_source(
                now - timezone.timedelta(minutes=5),
                '9999',
                'portfolio_sync_from_api',
            ),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '125'),
        ])
        summary = self._build(equity_history=history)

        self.assertEqual(summary['changes']['24h']['amount_usdt'], Decimal('25'))
        self.assertEqual(summary['changes']['24h']['percent'], Decimal('25'))

    def test_historical_change_ignores_api_sync_source_even_with_canonical_equity(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._snapshot_with_source(
                now - timezone.timedelta(hours=25),
                '100',
                'portfolio_sync_from_api',
            ),
            self._snapshot_with_source(
                now - timezone.timedelta(minutes=5),
                '125',
                'portfolio_sync_from_api',
            ),
        ])
        summary = self._build(equity_history=history)

        self.assertIsNone(summary['changes']['24h'])
        self.assertFalse(summary['chart_available'])

    def test_historical_change_ignores_snapshots_without_canonical_equity(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            SimpleNamespace(created_at=now - timezone.timedelta(hours=25), notes={}),
            SimpleNamespace(created_at=now - timezone.timedelta(hours=23), notes={'portfolio_equity_usdt': ''}),
            SimpleNamespace(created_at=now - timezone.timedelta(hours=22), notes={'portfolio_equity_usdt': 'invalid'}),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '125'),
        ])
        summary = self._build(equity_history=history)

        self.assertIsNone(summary['changes']['24h'])
        self.assertFalse(summary['chart_available'])

    def test_historical_change_24h_available_from_valid_bot_cycle_history(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(hours=24), '100'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '120'),
        ])
        summary = self._build(equity_history=history)

        self.assertEqual(summary['changes']['24h']['amount_usdt'], Decimal('20'))
        self.assertTrue(summary['chart_available'])

    def test_historical_change_does_not_use_open_value_as_equity_fallback(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            SimpleNamespace(created_at=now - timezone.timedelta(hours=25), notes={'open_value_usdt': '100'}),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '125'),
        ])
        summary = self._build(equity_history=history)

        self.assertIsNone(summary['changes']['24h'])
        self.assertFalse(summary['chart_available'])

    def test_historical_change_does_not_read_legacy_snapshot_data_equity(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._legacy_snapshot(now - timezone.timedelta(hours=25), {'portfolio_equity_usdt': '100'}),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '125'),
        ])
        summary = self._build(equity_history=history)

        self.assertIsNone(summary['changes']['24h'])
        self.assertFalse(summary['chart_available'])

    def test_historical_change_24h_accepts_exact_and_slightly_offset_snapshots(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        for age in [
            timezone.timedelta(hours=24),
            timezone.timedelta(hours=23),
            timezone.timedelta(hours=25),
        ]:
            with self.subTest(age=age):
                history = PortfolioEquityHistoryBuilder(as_of=now).build([
                    self._snapshot(now - age, '100'),
                    self._snapshot(now - timezone.timedelta(minutes=5), '125'),
                ])
                summary = self._build(equity_history=history)

                self.assertEqual(summary['changes']['24h']['amount_usdt'], Decimal('25'))

    def test_historical_change_24h_rejects_too_old_and_too_recent_snapshots(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        for age in [
            timezone.timedelta(days=15),
            timezone.timedelta(hours=2),
        ]:
            with self.subTest(age=age):
                history = PortfolioEquityHistoryBuilder(as_of=now).build([
                    self._snapshot(now - age, '100'),
                    self._snapshot(now - timezone.timedelta(minutes=5), '125'),
                ])
                summary = self._build(equity_history=history)

                self.assertIsNone(summary['changes']['24h'])

    def test_historical_change_7d_available_and_30d_unavailable(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._snapshot(now - timezone.timedelta(days=8), '80'),
            self._snapshot(now - timezone.timedelta(days=7), '100'),
            self._snapshot(now - timezone.timedelta(minutes=5), '120'),
        ])
        summary = self._build(equity_history=history)

        self.assertEqual(summary['changes']['7d']['amount_usdt'], Decimal('20'))
        self.assertEqual(summary['changes']['7d']['percent'], Decimal('20'))
        self.assertIsNone(summary['changes']['30d'])

    def test_historical_change_7d_accepts_valid_tolerance_window(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        for age in [
            timezone.timedelta(days=7),
            timezone.timedelta(days=6),
            timezone.timedelta(days=8),
        ]:
            with self.subTest(age=age):
                history = PortfolioEquityHistoryBuilder(as_of=now).build([
                    self._snapshot(now - age, '100'),
                    self._snapshot(now - timezone.timedelta(minutes=5), '120'),
                ])
                summary = self._build(equity_history=history)

                self.assertEqual(summary['changes']['7d']['amount_usdt'], Decimal('20'))

    def test_historical_change_7d_rejects_stale_too_recent_and_insufficient_history(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        for snapshots in [
            [self._snapshot(now - timezone.timedelta(days=15), '100')],
            [self._snapshot(now - timezone.timedelta(days=2), '100')],
            [],
        ]:
            with self.subTest(snapshots=snapshots):
                history = PortfolioEquityHistoryBuilder(as_of=now).build([
                    *snapshots,
                    self._snapshot(now - timezone.timedelta(minutes=5), '120'),
                ])
                summary = self._build(equity_history=history)

                self.assertIsNone(summary['changes']['7d'])

    def test_historical_change_30d_accepts_valid_tolerance_window(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        for age in [
            timezone.timedelta(days=30),
            timezone.timedelta(days=28),
            timezone.timedelta(days=32),
        ]:
            with self.subTest(age=age):
                history = PortfolioEquityHistoryBuilder(as_of=now).build([
                    self._snapshot(now - age, '100'),
                    self._snapshot(now - timezone.timedelta(minutes=5), '130'),
                ])
                summary = self._build(equity_history=history)

                self.assertEqual(summary['changes']['30d']['amount_usdt'], Decimal('30'))

    def test_historical_change_30d_rejects_stale_too_recent_and_insufficient_history(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        for snapshots in [
            [self._snapshot(now - timezone.timedelta(days=40), '100')],
            [self._snapshot(now - timezone.timedelta(days=10), '100')],
            [],
        ]:
            with self.subTest(snapshots=snapshots):
                history = PortfolioEquityHistoryBuilder(as_of=now).build([
                    *snapshots,
                    self._snapshot(now - timezone.timedelta(minutes=5), '130'),
                ])
                summary = self._build(equity_history=history)

                self.assertIsNone(summary['changes']['30d'])

    def test_historical_changes_unavailable_without_snapshots(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        history = PortfolioEquityHistoryBuilder(as_of=timezone.now()).build([])
        summary = self._build(equity_history=history)

        self.assertEqual(summary['changes'], {'24h': None, '7d': None, '30d': None})
        self.assertFalse(summary['chart_available'])

    def test_stale_and_incomplete_snapshots_do_not_create_changes(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            SimpleNamespace(created_at=now - timezone.timedelta(days=1), data={}),
            self._snapshot(now - timezone.timedelta(hours=8), '100'),
            self._snapshot(now - timezone.timedelta(days=2), '80'),
        ])
        summary = self._build(equity_history=history)

        self.assertEqual(summary['changes'], {'24h': None, '7d': None, '30d': None})
        self.assertFalse(summary['chart_available'])

    def test_chart_availability_does_not_require_all_change_horizons(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history_7d_only = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._snapshot(now - timezone.timedelta(days=7), '100'),
            self._snapshot(now - timezone.timedelta(minutes=5), '120'),
        ])
        summary_7d_only = self._build(equity_history=history_7d_only)
        self.assertIsNone(summary_7d_only['changes']['24h'])
        self.assertIsNotNone(summary_7d_only['changes']['7d'])
        self.assertTrue(summary_7d_only['chart_available'])

        history_24h_only = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._snapshot(now - timezone.timedelta(hours=24), '100'),
            self._snapshot(now - timezone.timedelta(minutes=5), '120'),
        ])
        summary_24h_only = self._build(equity_history=history_24h_only)
        self.assertIsNotNone(summary_24h_only['changes']['24h'])
        self.assertIsNone(summary_24h_only['changes']['7d'])
        self.assertTrue(summary_24h_only['chart_available'])

    def test_chart_points_do_not_mix_incompatible_snapshot_sources(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(days=1), '100'),
            self._snapshot_with_source(
                now - timezone.timedelta(hours=12),
                '10000',
                'portfolio_sync_from_api',
            ),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '120'),
        ])
        summary = self._build(equity_history=history)

        self.assertTrue(summary['chart_available'])
        self.assertEqual(
            [point['equity_usdt'] for point in summary['chart_points']],
            [Decimal('100'), Decimal('120')],
        )

    def test_chart_points_ignore_snapshots_without_canonical_equity(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(days=1), '100'),
            SimpleNamespace(
                created_at=now - timezone.timedelta(hours=12),
                source='bot_cycle',
                notes={},
            ),
            SimpleNamespace(
                created_at=now - timezone.timedelta(hours=6),
                source='bot_cycle',
                notes={'portfolio_equity_usdt': 'invalid'},
            ),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '120'),
        ])

        self.assertTrue(history['chart_points'])
        self.assertEqual(
            [point['equity_usdt'] for point in history['chart_points']],
            [Decimal('100'), Decimal('120')],
        )

    def test_chart_downsampling_caps_dense_history_to_configured_max_points(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        snapshots = [
            self._canonical_snapshot(
                now - timezone.timedelta(days=7) + timezone.timedelta(minutes=30 * index),
                str(100 + index),
            )
            for index in range(337)
        ]

        history = PortfolioEquityHistoryBuilder(as_of=now, max_chart_points=96).build(snapshots)

        self.assertTrue(history['chart_available'])
        self.assertLessEqual(len(history['chart_points']), 96)

    def test_chart_downsampling_keeps_last_valid_point_per_bucket(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        start = now - timezone.timedelta(days=7)
        history = PortfolioEquityHistoryBuilder(as_of=now, max_chart_points=2).build([
            self._canonical_snapshot(start, '100'),
            self._canonical_snapshot(start + timezone.timedelta(days=1), '101'),
            self._canonical_snapshot(start + timezone.timedelta(days=2), '102'),
            self._canonical_snapshot(start + timezone.timedelta(days=5), '105'),
            self._canonical_snapshot(start + timezone.timedelta(days=6), '106'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '107'),
        ])

        self.assertEqual(
            [point['equity_usdt'] for point in history['chart_points']],
            [Decimal('102'), Decimal('107')],
        )

    def test_chart_visual_filter_excludes_outlier_jumps_above_threshold(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(days=1), '100'),
            self._canonical_snapshot(now - timezone.timedelta(hours=12), '200'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '105'),
        ])

        self.assertTrue(history['chart_available'])
        self.assertEqual(
            [point['equity_usdt'] for point in history['chart_points']],
            [Decimal('100'), Decimal('105')],
        )

    def test_chart_visual_filter_ignores_consecutive_outliers(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(hours=4), '100'),
            self._canonical_snapshot(now - timezone.timedelta(hours=3), '200'),
            self._canonical_snapshot(now - timezone.timedelta(hours=2), '210'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '105'),
        ])

        self.assertTrue(history['chart_available'])
        self.assertEqual(
            [point['equity_usdt'] for point in history['chart_points']],
            [Decimal('100'), Decimal('105')],
        )

    def test_chart_visual_filter_outlier_chain_does_not_poison_future_valid_points(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(hours=5), '100'),
            self._canonical_snapshot(now - timezone.timedelta(hours=4), '200'),
            self._canonical_snapshot(now - timezone.timedelta(hours=3), '210'),
            self._canonical_snapshot(now - timezone.timedelta(hours=2), '220'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '110'),
        ])

        self.assertTrue(history['chart_available'])
        self.assertEqual(
            [point['equity_usdt'] for point in history['chart_points']],
            [Decimal('100'), Decimal('110')],
        )

    def test_chart_visual_filter_does_not_affect_textual_change_calculations(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityHistoryBuilder

        now = timezone.now()
        history = PortfolioEquityHistoryBuilder(as_of=now).build([
            self._canonical_snapshot(now - timezone.timedelta(hours=24), '100'),
            self._canonical_snapshot(now - timezone.timedelta(hours=12), '200'),
            self._canonical_snapshot(now - timezone.timedelta(minutes=5), '105'),
        ])

        self.assertEqual(history['changes']['24h']['amount_usdt'], Decimal('5'))
        self.assertEqual(history['changes']['24h']['percent'], Decimal('5'))
        self.assertEqual(
            [point['equity_usdt'] for point in history['chart_points']],
            [Decimal('100'), Decimal('105')],
        )

    @patch('core.telegram_diagnostics.PortfolioEquityChartRenderer.render_png')
    @patch('core.telegram_diagnostics._safe_realized_pnl_by_symbol_today', return_value=[])
    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('0'))
    @patch('core.telegram_diagnostics.Snapshot.objects')
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.PositionLot.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_portfolio_status_does_not_attempt_png_when_visual_filter_leaves_one_point(
        self,
        mock_health_manager,
        mock_lot_manager,
        mock_portfolio_manager,
        mock_snapshot_manager,
        _mock_realized_today,
        _mock_realized_drivers,
        mock_render_png,
    ):
        from core.telegram_diagnostics import format_portfolio_status

        now = timezone.now()
        mock_health_manager.order_by.return_value.first.return_value = None
        mock_lot_manager.filter.return_value.order_by.return_value = []
        mock_snapshot_manager.filter.return_value.order_by.return_value = [
            self._canonical_snapshot(now - timezone.timedelta(hours=24), '100'),
            self._canonical_snapshot(now - timezone.timedelta(hours=12), '200'),
        ]

        with patch('core.telegram_diagnostics.timezone.now', return_value=now):
            result = format_portfolio_status()

        self.assertIn('Chart: unavailable, not enough history', result['text'])
        self.assertIsNone(result['photo'])
        mock_render_png.assert_not_called()
        mock_portfolio_manager.filter.assert_not_called()

    def test_chart_renderer_returns_valid_png_bytes(self):
        from dashboard.services.telegram_portfolio_status import PortfolioEquityChartRenderer

        now = timezone.now()
        points = [
            {'timestamp': now - timezone.timedelta(days=1), 'equity_usdt': Decimal('100')},
            {'timestamp': now, 'equity_usdt': Decimal('125')},
        ]
        png = PortfolioEquityChartRenderer().render_png(points)

        self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertIn(b'IEND', png)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_photo')
    @patch('core.views.send_message')
    @patch(
        'core.telegram_diagnostics.format_portfolio_status',
        return_value={'text': '<b>portfolio</b>', 'photo': b'\x89PNG\r\n\x1a\nimage'},
    )
    def test_portfolio_status_routes_through_allowlisted_diagnostics(
        self,
        mock_format_portfolio_status,
        mock_send_message,
        mock_send_photo,
    ):
        client = Client()
        payload = {
            'message': {
                'text': '/portfolio_status',
                'message_id': 987,
                'chat': {'id': 999},
                'from': {'id': 777, 'username': 'operator'},
            },
        }

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = client.post(
                reverse('listener'),
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-webhook-token',
            )

        self.assertEqual(response.status_code, 200)
        mock_format_portfolio_status.assert_called_once_with()
        mock_send_photo.assert_called_once_with(b'\x89PNG\r\n\x1a\nimage', 999, caption='<b>portfolio</b>')
        mock_send_message.assert_not_called()

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_photo', side_effect=RuntimeError('telegram down'))
    @patch('core.views.send_message')
    @patch(
        'core.telegram_diagnostics.format_portfolio_status',
        return_value={'text': '<b>portfolio</b>', 'photo': b'\x89PNG\r\n\x1a\nimage'},
    )
    def test_portfolio_status_falls_back_to_text_when_photo_send_fails(
        self,
        _mock_format_portfolio_status,
        mock_send_message,
        _mock_send_photo,
    ):
        client = Client()
        payload = {
            'message': {
                'text': '/portfolio_status',
                'message_id': 987,
                'chat': {'id': 999},
                'from': {'id': 777, 'username': 'operator'},
            },
        }

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = client.post(
                reverse('listener'),
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-webhook-token',
            )

        self.assertEqual(response.status_code, 200)
        mock_send_message.assert_called_once_with('<b>portfolio</b>', 999)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_photo')
    @patch('core.views.send_message')
    @patch(
        'core.telegram_diagnostics.format_portfolio_status',
        return_value={'text': '<b>portfolio</b>\nChart: unavailable, not enough history', 'photo': None},
    )
    def test_portfolio_status_sends_text_only_when_history_unavailable(
        self,
        _mock_format_portfolio_status,
        mock_send_message,
        mock_send_photo,
    ):
        client = Client()
        payload = {
            'message': {
                'text': '/portfolio_status',
                'message_id': 987,
                'chat': {'id': 999},
                'from': {'id': 777, 'username': 'operator'},
            },
        }

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            response = client.post(
                reverse('listener'),
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN='test-webhook-token',
            )

        self.assertEqual(response.status_code, 200)
        mock_send_photo.assert_not_called()
        mock_send_message.assert_called_once_with(
            '<b>portfolio</b>\nChart: unavailable, not enough history',
            999,
        )

    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('1.25'))
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.PositionLot.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_format_portfolio_status_wires_free_usdt_lots_prices_and_realized_today(
        self,
        mock_health_manager,
        mock_lot_manager,
        mock_portfolio_manager,
        _mock_realized_today,
    ):
        from core.telegram_diagnostics import format_portfolio_status

        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            created_at=timezone.now(),
            details={'free_usdt': '10'},
        )
        mock_lot_manager.filter.return_value.order_by.return_value = [
            self._lot('BTCUSDT', '2', '5'),
        ]
        mock_portfolio_manager.filter.return_value = [
            self._portfolio('BTCUSDT', '6', updated_at=timezone.now()),
        ]

        message = format_portfolio_status()['text']

        self.assertIn('- Equity: <code>22.00 USDT</code>', message)
        self.assertIn('- Open value: <code>12.00 USDT</code>', message)
        self.assertIn('<b>Performance</b>', message)
        self.assertIn('<b>Portfolio equity</b>', message)
        self.assertIn('<b>Today&#x27;s trading (UTC)</b>', message)
        self.assertIn('<b>Open positions</b>', message)
        self.assertLess(message.index('<b>Portfolio equity</b>'), message.index('<b>Today&#x27;s trading (UTC)</b>'))
        self.assertLess(message.index('<b>Today&#x27;s trading (UTC)</b>'), message.index('<b>Open positions</b>'))
        self.assertNotIn('<b>Change</b>', message)
        self.assertNotIn('<b>PnL context</b>', message)
        self.assertNotIn('<b>24h drivers</b>', message)
        self.assertIn('<b>Current unrealized contributors</b>', message)
        self.assertNotIn('- Invested:', message)
        self.assertIn('- Unrealized now: <code>+2.00 USDT (+20.00%)</code>', message)
        self.assertIn('- Realized PnL: <code>+1.25 USDT</code>', message)
        self.assertNotIn('Realized today (UTC)', message)

    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('0'))
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.PositionLot.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_format_portfolio_status_rejects_stale_healthcheck_free_usdt(
        self,
        mock_health_manager,
        mock_lot_manager,
        mock_portfolio_manager,
        _mock_realized_today,
    ):
        from core.telegram_diagnostics import format_portfolio_status

        now = timezone.now()
        mock_health_manager.order_by.return_value.first.return_value = SimpleNamespace(
            created_at=now - timezone.timedelta(minutes=16),
            details={'free_usdt': '10'},
        )
        mock_lot_manager.filter.return_value.order_by.return_value = []

        with patch('core.telegram_diagnostics.timezone.now', return_value=now):
            message = format_portfolio_status()['text']

        self.assertIn('- Free USDT: <code>unavailable</code>', message)
        self.assertIn('- Equity: <code>unavailable</code>', message)
        mock_portfolio_manager.filter.assert_not_called()

    @patch('core.telegram_diagnostics.Snapshot.objects')
    @patch('core.telegram_diagnostics._safe_realized_pnl_today', return_value=Decimal('0'))
    @patch('core.telegram_diagnostics.Portfolio.objects')
    @patch('core.telegram_diagnostics.PositionLot.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_portfolio_status_does_not_write_bot_owned_tables(
        self,
        mock_health_manager,
        mock_lot_manager,
        mock_portfolio_manager,
        _mock_realized_today,
        mock_snapshot_manager,
    ):
        from core.telegram_diagnostics import format_portfolio_status

        mock_health_manager.order_by.return_value.first.return_value = None
        mock_lot_manager.filter.return_value.order_by.return_value = []
        mock_snapshot_manager.filter.return_value.order_by.return_value = []

        format_portfolio_status()

        for manager in [mock_health_manager, mock_lot_manager, mock_portfolio_manager, mock_snapshot_manager]:
            manager.create.assert_not_called()
            manager.bulk_create.assert_not_called()
            manager.update_or_create.assert_not_called()
            manager.filter.return_value.update.assert_not_called()

    @patch('core.telegram_diagnostics.LotClosure.objects')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    def test_realized_today_by_symbol_uses_utc_boundaries_and_operation_timestamp_fallback(
        self,
        mock_trade_manager,
        mock_closure_manager,
    ):
        from core.telegram_diagnostics import realized_pnl_by_symbol_for_day

        operation_ids = [101, 102]
        mock_trade_manager.filter.return_value.values_list.return_value = operation_ids
        mock_closure_manager.filter.return_value.values.return_value.annotate.return_value.order_by.return_value = [
            {'symbol': 'ETHUSDT', 'total': Decimal('-3.25')},
            {'symbol': 'BTCUSDT', 'total': Decimal('1.10')},
        ]

        result = realized_pnl_by_symbol_for_day(timezone.datetime(2026, 6, 12).date())

        self.assertEqual(result, [
            {'symbol': 'ETHUSDT', 'pnl_usdt': Decimal('-3.25')},
            {'symbol': 'BTCUSDT', 'pnl_usdt': Decimal('1.10')},
        ])
        query = mock_trade_manager.filter.call_args.args[0]
        start = timezone.datetime(2026, 6, 12, tzinfo=datetime_timezone.utc)
        end = timezone.datetime(2026, 6, 13, tzinfo=datetime_timezone.utc)
        cases = [
            ({'executed_at': start, 'created_at': start}, True),
            ({'executed_at': end, 'created_at': start}, False),
            ({'executed_at': None, 'created_at': start}, True),
            ({'executed_at': None, 'created_at': end}, False),
        ]
        for operation, expected in cases:
            with self.subTest(operation=operation):
                self.assertEqual(self._matches_query(query, operation), expected)
        mock_closure_manager.filter.assert_called_once_with(
            trade_operation_id__in=operation_ids,
        )

    def _matches_query(self, query, values):
        child_results = []
        for child in query.children:
            if hasattr(child, 'children'):
                child_results.append(self._matches_query(child, values))
                continue
            lookup, expected = child
            field, _, operator = lookup.partition('__')
            actual = values[field]
            if operator == 'gte':
                child_results.append(actual is not None and actual >= expected)
            elif operator == 'lt':
                child_results.append(actual is not None and actual < expected)
            elif operator == 'isnull':
                child_results.append((actual is None) is expected)
            else:
                self.fail(f'Unsupported query lookup in test: {lookup}')
        result = all(child_results) if query.connector == 'AND' else any(child_results)
        return not result if query.negated else result


class LastOperationsCommandTests(TransactionTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cursor:
            cursor.execute("ATTACH DATABASE ':memory:' AS bot")
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(TradeOperation)
            schema_editor.create_model(LotClosure)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(LotClosure)
            schema_editor.delete_model(TradeOperation)
        with connection.cursor() as cursor:
            cursor.execute("DETACH DATABASE bot")
        super().tearDownClass()

    def setUp(self):
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM "bot"."lot_closures"')
            cursor.execute('DELETE FROM "bot"."trade_operations"')

    def _insert_operation(self, symbol, executed_at):
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "bot"."trade_operations" (symbol, side, status, executed_at, created_at, raw_payload) VALUES (%s, %s, %s, %s, %s, %s)',
                [symbol, 'SELL', 'FILLED', executed_at, executed_at, '{}'],
            )
            return cursor.lastrowid

    def _insert_closure(self, operation_id, pnl, index):
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "bot"."lot_closures" (sell_fill_id, lot_id, symbol, trade_operation_id, quantity_closed, realized_pnl) VALUES (%s, %s, %s, %s, %s, %s)',
                [index, f'lot-{index}', 'REALUSDT', operation_id, Decimal('1'), pnl],
            )

    def test_real_orm_multi_lot_sell_is_one_row_and_sums_pnl(self):
        from core.telegram_diagnostics import format_last_operations
        when = timezone.now()
        operation_id = self._insert_operation('REALUSDT', when)
        self._insert_closure(operation_id, Decimal('-0.50'), 1)
        self._insert_closure(operation_id, Decimal('-0.75'), 2)
        result = format_last_operations('10')
        self.assertEqual(result.count('REALUSDT'), 1)
        self.assertIn('-1.25', result)
        self.assertIn('Realized PnL: -1.25 USDT', result)

    def test_real_orm_latest_n_uses_operations_not_closures(self):
        from core.telegram_diagnostics import format_last_operations
        base = timezone.now()
        oldest = self._insert_operation('OLDUSDT', base - timedelta(minutes=2))
        middle = self._insert_operation('MIDUSDT', base - timedelta(minutes=1))
        newest = self._insert_operation('NEWUSDT', base)
        self._insert_closure(oldest, Decimal('1.00'), 3)
        self._insert_closure(middle, Decimal('2.00'), 4)
        self._insert_closure(newest, Decimal('3.00'), 5)
        self._insert_closure(newest, Decimal('4.00'), 6)
        result = format_last_operations('2')
        self.assertIn('NEWUSDT', result)
        self.assertIn('MIDUSDT', result)
        self.assertNotIn('OLDUSDT', result)
        self.assertEqual(result.count('NEWUSDT'), 1)
        self.assertLess(result.index('NEWUSDT'), result.index('MIDUSDT'))
        self.assertIn('7 USDT', result)
    def _operation(self, operation_id, symbol, reason=None, when=None):
        return SimpleNamespace(id=operation_id, symbol=symbol, executed_at=when or timezone.now(), raw_payload=({'sell_reason': reason} if reason else {}))

    @patch('core.telegram_diagnostics.LotClosure.objects')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    def test_latest_bounded_filled_sell_operations_are_aggregated_once(self, trades, closures):
        from core.telegram_diagnostics import format_last_operations
        now = timezone.now()
        trades.filter.return_value.order_by.return_value.__getitem__.return_value = [
            self._operation(3, 'NEWUSDT', 'take_profit_reached', now),
            self._operation(2, 'MULTIUSDT', 'stop_loss_reached', now - timezone.timedelta(minutes=1)),
        ]
        closures.filter.return_value.values.return_value.annotate.return_value = [
            {'trade_operation_id': 2, 'realized_pnl': Decimal('-1.25')},
        ]
        result = format_last_operations('2')
        self.assertIn('Last 2 SELL operations', result)
        self.assertEqual(result.count('MULTIUSDT'), 1)
        self.assertIn('-1.25', result)
        self.assertIn('unknown', result)
        trades.filter.assert_called_once_with(side='SELL', status='FILLED')
        trades.filter.return_value.order_by.assert_called_once_with('-executed_at', '-created_at', '-id')
        trades.filter.return_value.order_by.return_value.__getitem__.assert_any_call(slice(None, 2, None))
        closures.filter.assert_called_once_with(trade_operation_id__in=[3, 2])
        self.assertEqual(closures.filter.call_count, 1)

    @patch('core.telegram_diagnostics.LotClosure.objects')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    def test_default_and_maximum_limits_and_empty_result(self, trades, closures):
        from core.telegram_diagnostics import format_last_operations
        trades.filter.return_value.order_by.return_value.__getitem__.return_value = []
        closures.filter.return_value.values.return_value.annotate.return_value = []
        self.assertIn('Last 10', format_last_operations())
        self.assertIn('Last 50', format_last_operations('999'))
        self.assertIn('Usage:', format_last_operations('0'))
        self.assertIn('Usage:', format_last_operations('-1'))

    def test_limit_parser_and_extra_argument_validation(self):
        from core.telegram_diagnostics import _last_operations_limit, diagnostic_response
        self.assertEqual(_last_operations_limit(None), 10)
        self.assertEqual(_last_operations_limit('10'), 10)
        self.assertEqual(_last_operations_limit('50'), 50)
        self.assertEqual(_last_operations_limit('999'), 50)
        self.assertIsNone(_last_operations_limit('0'))
        self.assertIsNone(_last_operations_limit('-1'))
        self.assertIsNone(_last_operations_limit('abc'))
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.assertIn('Usage:', diagnostic_response('/last_operations 10 extra', '999'))

    @patch('core.telegram_diagnostics.format_last_operations', return_value='ok')
    def test_command_dispatches_last_operations(self, formatter):
        from core.telegram_diagnostics import diagnostic_response
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS='999'):
            self.assertEqual(diagnostic_response('/last_operations 10', '999'), 'ok')
        formatter.assert_called_once_with('10')
