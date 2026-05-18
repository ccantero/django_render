from django.test import TestCase, TransactionTestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from django.db import DatabaseError, connection
from decimal import Decimal
from types import SimpleNamespace
import inspect
import json
import logging
import os
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
        mock_portfolio_manager.filter.return_value = []
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
        mock_portfolio_manager.filter.return_value = []
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
        mock_portfolio_manager.filter.return_value = []
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
        self.assertIn('Cooldown remaining: <code>42</code>', message)
        self.assertIn('Dust positions are non-blocking', message)

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
            SimpleNamespace(symbol='BTCUSDT', quantity=Decimal('1'), current_price=Decimal('1.24')),
            SimpleNamespace(symbol='ETHUSDT', quantity=Decimal('2'), current_price=Decimal('5.41')),
            SimpleNamespace(symbol='SOLUSDT', quantity=Decimal('1'), current_price=Decimal('3.91')),
            SimpleNamespace(symbol='XRPUSDT', quantity=Decimal('2'), current_price=Decimal('0.56')),
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
        self.assertIn('<b>Material exposure (~15.97 USDT)</b>', message)
        self.assertLess(message.index('ETHUSDT ~ 10.82 USDT'), message.index('SOLUSDT ~ 3.91 USDT'))
        self.assertLess(message.index('SOLUSDT ~ 3.91 USDT'), message.index('BTCUSDT ~ 1.24 USDT'))
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
        mock_portfolio_manager.filter.return_value = []
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
        from core.trading_models import SellDecisionEvent

        self.assertFalse(SellDecisionEvent._meta.managed)
        self.assertEqual(SellDecisionEvent._meta.db_table, '"bot"."sell_decision_events"')
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

        mock_logger.debug.assert_called_once_with('Could not read portfolio rows for Telegram BUY status exposure')
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
                        'date': timezone.datetime(2026, 5, 1, tzinfo=timezone.utc).date(),
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
                'gross_quote': Decimal('20.00'),
                'net_quote': Decimal('20.00'),
            },
            'recent_operations': [
                SimpleNamespace(
                    side='BUY',
                    symbol='BTCUSDT',
                    status='FILLED',
                    executed_base_qty=Decimal('0.001'),
                    gross_quote=Decimal('20.00'),
                    net_quote=Decimal('20.00'),
                    executed_at=timezone.now(),
                    created_at=timezone.now(),
                ),
            ],
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
        self.assertContains(response, 'Reconciliation: <strong>warning</strong>', html=True)
        self.assertContains(response, 'Historical KPIs are deferred')
        self.assertContains(response, 'Analytics')
        self.assertContains(response, 'Portfolio vs lots drift')
        self.assertContains(response, '0.75 USDT')
        self.assertContains(response, '0.00100000')
        self.assertContains(response, 'Dust / Residuals')
        self.assertContains(response, 'Active issues first')
        self.assertNotContains(response, 'Net realized PnL')
        self.assertNotContains(response, '12.25')
        self.assertNotContains(response, 'Win rate')
        self.assertNotContains(response, 'Average win')
        self.assertNotContains(response, 'Average loss')
        self.assertNotContains(response, 'Profit factor')
        self.assertNotContains(response, '6.00')
        self.assertNotContains(response, 'Gross deployed capital')
        self.assertNotContains(response, 'PnL by symbol')
        self.assertNotContains(response, 'PnL by day')
        self.assertContains(response, 'BTCUSDT')

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_home_is_operational_overview_without_pnl_tables(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        context['performance_kpis'].update({
            'net_realized_pnl': Decimal('12.25'),
            'total_fees_usdt': Decimal('0.25'),
            'win_rate': Decimal('50'),
            'average_win': Decimal('15.00'),
            'average_loss': Decimal('-2.50'),
            'gross_deployed_capital': Decimal('120.00'),
            'pnl_by_symbol': [
                {'symbol': 'BTCUSDT', 'realized_pnl': Decimal('12.50'), 'closures_count': 2},
            ],
            'pnl_by_day': [
                {
                    'date': timezone.datetime(2026, 5, 1, tzinfo=timezone.utc).date(),
                    'realized_pnl': Decimal('12.50'),
                    'closures_count': 2,
                },
            ],
        })
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operations Console')
        self.assertContains(response, 'Historical KPIs are deferred')
        self.assertNotContains(response, 'Net realized PnL')
        self.assertContains(response, 'Analytics')
        self.assertContains(response, 'Dust Dashboard')
        self.assertNotContains(response, 'PnL by symbol')
        self.assertNotContains(response, 'PnL by day')
        self.assertNotContains(response, 'Profit factor')
        self.assertNotContains(response, 'Average win')
        self.assertNotContains(response, 'Average loss')
        self.assertNotContains(response, 'Gross deployed capital')
        self.assertNotContains(response, 'Manual/accounting adjustment PnL')

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_home_shows_max_four_recent_operations(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        context['recent_operations'] = [
            SimpleNamespace(
                side='BUY',
                symbol=f'OP{index}USDT',
                status='FILLED',
                executed_base_qty=Decimal('1.00000000'),
                gross_quote=Decimal('10.00'),
                net_quote=Decimal('10.00'),
                executed_at=timezone.now() - timezone.timedelta(minutes=index),
                created_at=timezone.now() - timezone.timedelta(minutes=index),
            )
            for index in range(6)
        ]
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recent Trades')
        self.assertEqual(content.count('dashboard-recent-operation-row'), 4)
        self.assertContains(response, 'OP0USDT')
        self.assertContains(response, 'OP3USDT')
        self.assertNotContains(response, 'OP4USDT')

    def test_analytics_dashboard_requires_authentication(self):
        response = self.client.get('/dashboard/analytics/')

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    def test_exit_status_dashboard_requires_authentication(self):
        response = self.client.get(reverse('dashboard_exit_status'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    def test_churn_dashboard_requires_authentication(self):
        response = self.client.get(reverse('dashboard_churn'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    def test_operational_kpis_dashboard_requires_authentication(self):
        response = self.client.get(reverse('dashboard_operational_kpis'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    @patch('dashboard.views.get_dashboard_context')
    def test_analytics_dashboard_renders_performance_tables(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        context['fee_summary'] = {
            'asset_count': 1,
            'fill_count': 2,
            'rows': [{'asset': 'USDT', 'total': Decimal('0.25'), 'fill_count': 2}],
        }
        context['quote_fee_summary'] = {
            'total_fees_usdt': Decimal('0.25'),
            'total_operations': 2,
            'by_side': {
                'BUY': {'total_fee_usdt': Decimal('0.10'), 'operations_count': 1},
                'SELL': {'total_fee_usdt': Decimal('0.15'), 'operations_count': 1},
            },
        }
        context['performance_kpis'].update({
            'gross_realized_pnl': Decimal('12.50'),
            'total_fees_usdt': Decimal('0.25'),
            'net_realized_pnl': Decimal('12.25'),
            'win_rate': Decimal('50'),
            'average_win': Decimal('15.00'),
            'average_loss': Decimal('-2.50'),
            'profit_factor': Decimal('6'),
            'gross_deployed_capital': Decimal('120.00'),
            'manual_adjustment_pnl': Decimal('0'),
            'pnl_by_symbol': [
                {'symbol': 'BTCUSDT', 'realized_pnl': Decimal('12.50'), 'closures_count': 2},
            ],
            'pnl_by_day': [
                {
                    'date': timezone.datetime(2026, 5, 1, tzinfo=timezone.utc).date(),
                    'realized_pnl': Decimal('12.50'),
                    'closures_count': 2,
                },
            ],
        })
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get('/dashboard/analytics/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Analytics Dashboard')
        self.assertContains(response, 'Performance KPIs')
        self.assertContains(response, 'PnL by symbol')
        self.assertContains(response, 'PnL by day')
        self.assertContains(response, 'Fees (USDT)')
        self.assertContains(response, 'Total Fees')
        self.assertContains(response, 'Profit factor')
        self.assertContains(response, 'Manual/accounting adjustment PnL')

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_shows_dust_summary(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        context['dust_summary'] = {
            'total_detections': 6,
            'critical_count': 2,
            'warning_count': 3,
            'info_count': 1,
            'latest_run_id': 'run-dust-001',
            'latest_detected_at': timezone.now(),
            'top_grouped_detections': [
                {
                    'symbol': 'SOLUSDT',
                    'asset': 'SOL',
                    'severity': 'critical',
                    'event_type': 'dust_candidate_detected',
                    'reason': 'below_min_notional',
                    'detections_count': 2,
                    'latest_detected_at': timezone.now(),
                    'latest_run_id': 'run-dust-001',
                    'latest_estimated_value_usdt': Decimal('4.20'),
                    'latest_estimated_delta_value_usdt': Decimal('0'),
                    'latest_suggested_action': 'monitor',
                },
            ],
            'active_operational_issues': [
                {
                    'symbol': 'SOLUSDT',
                    'severity': 'critical',
                    'latest_detected_at': timezone.now(),
                    'latest_estimated_value_usdt': Decimal('4.20'),
                    'latest_estimated_delta_value_usdt': Decimal('0'),
                    'display_reason': 'Below min notional',
                    'operator_badge': 'badge-danger',
                    'detail_querystring': 'symbol=SOLUSDT&asset=SOL&reason=below_min_notional&event_type=dust_candidate_detected&severity=critical',
                },
            ],
            'total_estimated_value_usdt': Decimal('4.20'),
            'data_error': None,
        }
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dust / Residuals')
        self.assertContains(response, 'Critical')
        self.assertContains(response, 'Warning')
        self.assertContains(response, 'Info residuals')
        self.assertContains(response, 'SOLUSDT')
        self.assertContains(response, 'Below min notional')
        self.assertContains(response, reverse('dust_dashboard'))

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_shows_active_operational_issues_without_full_dust_table(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        issue_rows = []
        for index in range(6):
            issue_rows.append({
                'symbol': f'ISSUE{index}USDT',
                'asset': f'ISSUE{index}',
                'severity': 'critical' if index == 0 else 'warning',
                'event_type': 'lot_balance_drift_detected',
                'reason': 'lot_balance_drift',
                'detections_count': 1,
                'latest_detected_at': timezone.now() - timezone.timedelta(minutes=index),
                'latest_run_id': 'run-home-001',
                'latest_estimated_value_usdt': Decimal(str(index + 1)),
                'latest_estimated_delta_value_usdt': Decimal('0.25'),
                'latest_suggested_action': 'review_recent_sell',
                'operator_label': 'Lots > Binance',
                'operator_badge': 'badge-danger' if index == 0 else 'badge-warning',
                'detail_querystring': f'symbol=ISSUE{index}USDT&asset=ISSUE{index}&reason=lot_balance_drift&event_type=lot_balance_drift_detected&severity=warning',
            })
        context['dust_summary'] = {
            'total_detections': 6,
            'critical_count': 1,
            'warning_count': 5,
            'info_count': 0,
            'latest_run_id': 'run-home-001',
            'latest_detected_at': timezone.now(),
            'active_operational_issues': issue_rows,
            'top_grouped_detections': issue_rows,
            'total_estimated_value_usdt': Decimal('21'),
            'data_error': None,
        }
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Active Operational Issues')
        self.assertContains(response, 'Dust Dashboard')
        self.assertContains(response, 'Reason / short label')
        self.assertContains(response, 'Approx USDT')
        self.assertEqual(content.count('dashboard-operational-issue-row'), 5)
        self.assertContains(response, 'ISSUE0USDT')
        self.assertContains(response, 'ISSUE4USDT')
        self.assertNotContains(response, 'ISSUE5USDT')
        self.assertNotContains(response, '<th>Asset</th>', html=True)
        self.assertNotContains(response, '<th>Event type</th>', html=True)
        self.assertNotContains(response, '<th>Latest run</th>', html=True)

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_shows_position_exit_status_card(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        context['position_exit_status'] = {
            'rows': [
                {
                    'symbol': 'ZECUSDT',
                    'status_label': 'Holding',
                    'status_badge': 'badge-info',
                    'main_reason': 'stop_loss not reached, take_profit not reached',
                    'interpretation': 'Stop loss has not been reached. Current loss is still inside the configured stop-loss threshold.',
                    'estimated_value_usdt': Decimal('42.25'),
                    'open_lot_quantity': Decimal('0.50000000'),
                    'current_price': Decimal('84.50'),
                    'suggested_action': 'Hold: strategy thresholds not reached',
                },
                {
                    'symbol': 'ORDIUSDT',
                    'status_label': 'Review needed',
                    'status_badge': 'badge-warning',
                    'main_reason': 'insufficient Binance balance',
                    'estimated_value_usdt': Decimal('18.00'),
                    'open_lot_quantity': Decimal('3.00000000'),
                    'current_price': Decimal('6.00'),
                    'suggested_action': 'Review drift: Binance balance lower than lots',
                },
            ],
            'material_count': 2,
            'dust_count': 0,
            'data_error': None,
        }
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Open FIFO lot exit status')
        self.assertContains(response, 'ZECUSDT')
        self.assertContains(response, 'Holding')
        self.assertContains(response, 'stop_loss not reached, take_profit not reached')
        self.assertContains(response, 'Stop loss has not been reached. Current loss is still inside the configured stop-loss threshold.')
        self.assertContains(response, 'Hold: strategy thresholds not reached')
        self.assertContains(response, 'ORDIUSDT')
        self.assertContains(response, 'Review drift: Binance balance lower than lots')

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_links_to_full_exit_status_instead_of_diagnostics_not_loaded_copy(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertContains(response, 'Open Exit Status')
        self.assertNotContains(response, 'SELL diagnostics are not loaded')

    @patch('dashboard.views.get_exit_status_context')
    def test_exit_status_dashboard_renders_full_table(self, mock_get_exit_status_context):
        context = self.empty_dashboard_context()
        context['position_exit_status']['rows'] = [{
            'symbol': 'BTCUSDT',
            'status_label': 'Holding',
            'status_badge': 'badge-info',
            'main_reason': 'stop_loss not reached',
            'open_lot_quantity': Decimal('0.01'),
        }]
        mock_get_exit_status_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard_exit_status'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Exit Status')
        self.assertContains(response, 'BTCUSDT')

    @patch('dashboard.views.get_churn_context')
    def test_churn_dashboard_renders_summary(self, mock_get_churn_context):
        mock_get_churn_context.return_value.context = {
            'churn_summary': {
                'reentries_under_15m_24h': 1,
                'reentries_under_15m_48h': 2,
                'economically_questionable_count': 1,
                'rows': [],
            },
            'data_error': None,
        }
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard_churn'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Churn / Cooldown')
        self.assertContains(response, 'SELL→BUY under 15m')

    @patch('dashboard.views.get_operational_kpis_context')
    def test_operational_kpis_dashboard_renders_tables(self, mock_get_operational_kpis_context):
        mock_get_operational_kpis_context.return_value.context = {
            'filters': OperationalKpiFilters(churn_threshold_minutes=60),
            'strategy_summary': [{
                'strategy_version': 'v2',
                'closed_trades_count': 1,
                'eligible_filled_sell_count': 1,
                'net_realized_pnl': Decimal('5'),
                'win_rate': Decimal('100'),
                'average_hold_duration': timezone.timedelta(minutes=30),
                'churn_count': 1,
                'churn_frequency': Decimal('100'),
                'total_normalized_fees': Decimal('0.2'),
                'fee_efficiency': Decimal('4'),
            }],
            'hold_time': {
                'average_hold_duration': timezone.timedelta(minutes=30),
                'median_hold_duration': timezone.timedelta(minutes=30),
                'shortest_hold_duration': timezone.timedelta(minutes=30),
                'longest_hold_duration': timezone.timedelta(minutes=30),
                'closed_under_15m_count': 0,
                'buckets': {'<15m': 0, '15m-1h': 1, '1h-4h': 0, '4h-24h': 0, '>24h': 0},
            },
            'churn': {
                'eligible_filled_sell_count': 1,
                'same_symbol_reentry_count': 1,
                'same_symbol_reentry_frequency': Decimal('100'),
                'stop_loss_reentry_churn_count': 0,
                'by_strategy_version': [],
            },
            'fee_efficiency': {
                'total_normalized_fees': Decimal('0.2'),
                'gross_profit': Decimal('5'),
                'net_realized_pnl': Decimal('4.8'),
                'fees_over_gross_profit': Decimal('4'),
                'fees_over_absolute_net_pnl': Decimal('4.1666666667'),
                'average_fee_per_closed_trade': Decimal('0.2'),
                'by_symbol': [],
            },
            'data_error': None,
        }
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard_operational_kpis'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Operational Trading KPIs v2')
        self.assertContains(response, 'Strategy Version Summary')
        self.assertContains(response, 'Hold-Time Analytics')
        self.assertContains(response, 'Churn Metrics')
        self.assertContains(response, 'Fee Efficiency')
        self.assertContains(response, '100%')

    def test_demo_dashboard_is_public_and_read_only(self):
        response = self.client.get(reverse('dashboard_demo'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public demo')
        self.assertContains(response, 'Historical KPIs are deferred')
        self.assertNotContains(response, 'Total Fees')
        self.assertNotContains(response, 'Fees (USDT)')
        self.assertNotContains(response, 'Control seguro')
        self.assertNotContains(response, 'Stop')
        self.assertNotContains(response, 'Resume')

    def test_dust_dashboard_requires_authentication(self):
        response = self.client.get(reverse('dust_dashboard'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    def test_dust_detail_requires_authentication(self):
        response = self.client.get(reverse('dust_detail'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response['Location'])

    @patch('dashboard.views.get_dust_dashboard_context')
    def test_dust_dashboard_authenticated_user_gets_page(self, mock_get_dust_context):
        mock_get_dust_context.return_value.context = {
            'data_error': None,
            'grouped_detections': [
                {
                    'symbol': 'BTCUSDT',
                    'asset': 'BTC',
                    'severity': 'info',
                    'event_type': 'dust_candidate_detected',
                    'reason': 'below_min_notional',
                    'detections_count': 1,
                    'latest_detected_at': timezone.now(),
                    'latest_run_id': 'run-123',
                    'latest_estimated_value_usdt': Decimal('0.77962320'),
                    'latest_estimated_delta_value_usdt': None,
                    'latest_suggested_action': 'monitor',
                    'operator_label': 'Below min notional',
                    'operator_badge': 'badge-info',
                    'operator_priority': 'informational',
                    'operator_action': 'Monitor / optionally ignore',
                    'review_status': 'ignored',
                    'correction_status_label': 'No correction',
                    'correction_badge': 'badge-light',
                    'correction_statuses': [],
                    'has_blocking_correction': False,
                    'is_actionable': False,
                    'detail_querystring': 'symbol=BTCUSDT&asset=BTC&reason=below_min_notional&event_type=dust_candidate_detected&severity=info',
                },
                {
                    'symbol': 'ETHUSDT',
                    'asset': 'ETH',
                    'severity': 'warning',
                    'event_type': 'lot_below_min_notional_detected',
                    'reason': 'possible_incomplete_sell',
                    'detections_count': 1,
                    'latest_detected_at': timezone.now(),
                    'latest_run_id': 'run-123',
                    'latest_estimated_value_usdt': Decimal('0.415022396'),
                    'latest_estimated_delta_value_usdt': Decimal('0'),
                    'latest_suggested_action': 'review_recent_sell',
                    'operator_label': 'Possible incomplete sell',
                    'operator_badge': 'badge-warning',
                    'operator_priority': 'warning',
                    'operator_action': 'Inspect Binance history, then create correction request if external operation confirmed',
                    'review_status': 'pending',
                    'correction_status_label': 'Pending correction',
                    'correction_badge': 'badge-warning',
                    'correction_statuses': ['PENDING'],
                    'has_blocking_correction': True,
                    'correction_block_message': 'A correction request is already pending for this detection.',
                    'is_actionable': False,
                    'detail_querystring': 'symbol=ETHUSDT&asset=ETH&reason=possible_incomplete_sell&event_type=lot_below_min_notional_detected&severity=warning',
                },
            ],
            'top_risk_signals': [{
                'symbol': 'ETHUSDT',
                'severity': 'info',
                'event_type': 'lot_below_min_notional_detected',
                'reason': 'possible_incomplete_sell',
                'latest_estimated_value_usdt': Decimal('0.415022396'),
                'operator_label': 'Possible incomplete sell',
                'operator_badge': 'badge-warning',
                'operator_priority': 'warning',
                'operator_action': 'Inspect Binance history, then create correction request if external operation confirmed',
            }],
            'active_filters': [{'label': 'Severity', 'value': 'critical'}],
            'filters': {'symbol': '', 'severity': '', 'event_type': '', 'reason': ''},
            'filter_options': {
                'symbols': [],
                'severities': [],
                'event_types': [],
                'reasons': [],
                'review_statuses': DustSignalReview.STATUS_CHOICES,
            },
            'summary': {
                'total_detections': 3,
                'critical_count': 1,
                'warning_count': 2,
                'info_count': 0,
                'total_estimated_value_usdt': Decimal('3.25'),
                'latest_run_id': 'run-123',
                'latest_detected_at': timezone.now(),
            },
        }
        self.client.force_login(self.user)

        response = self.client.get(reverse('dust_dashboard'), {'severity': 'critical'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dust / Residuals')
        self.assertContains(response, 'run-123')
        self.assertContains(response, 'Back to Dashboard')
        self.assertContains(response, 'Top risk signals')
        self.assertContains(response, 'ETHUSDT')
        self.assertContains(response, 'possible_incomplete_sell')
        self.assertContains(response, 'Top grouped detections')
        self.assertContains(response, 'data-sort-index')
        self.assertContains(response, 'Reset')
        self.assertContains(response, 'Active filters')
        self.assertContains(response, 'Severity')
        self.assertContains(response, 'ignored')
        self.assertContains(response, 'dust-row-ignored')
        self.assertContains(response, 'View details')
        self.assertContains(response, 'Do not correct from DB directly. Use manual correction workflow.')
        self.assertContains(response, 'Pending for pending review')
        self.assertContains(response, 'Below min notional')
        self.assertContains(response, 'informational')
        self.assertContains(response, 'Monitor / optionally ignore')
        self.assertContains(response, 'Possible incomplete sell')
        self.assertContains(response, 'Inspect Binance history')
        self.assertContains(response, 'No correction')
        self.assertContains(response, 'Pending correction')
        self.assertContains(response, 'A correction request is already pending for this detection.')
        mock_get_dust_context.assert_called_once()

    @patch('dashboard.views.get_dust_dashboard_context')
    def test_dust_dashboard_renders_pagination_controls(self, mock_get_dust_context):
        rows = []
        for index in range(25):
            rows.append({
                'symbol': f'PAGE{index}USDT',
                'asset': f'PAGE{index}',
                'severity': 'info',
                'event_type': 'dust_candidate_detected',
                'reason': 'below_min_notional',
                'detections_count': 1,
                'latest_detected_at': timezone.now(),
                'latest_run_id': 'run-page-001',
                'latest_estimated_value_usdt': Decimal('0.25'),
                'latest_estimated_delta_value_usdt': Decimal('0'),
                'latest_suggested_action': 'monitor',
                'operator_label': 'Below min notional',
                'operator_badge': 'badge-info',
                'operator_priority': 'informational',
                'operator_action': 'Monitor / optionally ignore',
                'review_status': 'pending',
                'correction_status_label': 'No correction',
                'correction_badge': 'badge-light',
                'correction_statuses': [],
                'has_blocking_correction': False,
                'is_actionable': True,
                'detail_querystring': f'symbol=PAGE{index}USDT&asset=PAGE{index}&reason=below_min_notional&event_type=dust_candidate_detected&severity=info',
            })
        mock_get_dust_context.return_value.context = {
            'data_error': None,
            'grouped_detections': rows,
            'top_risk_signals': [],
            'active_filters': [],
            'filters': {'symbol': '', 'severity': '', 'event_type': '', 'reason': '', 'review_status': '', 'page': '2'},
            'filter_options': {
                'symbols': [],
                'severities': [],
                'event_types': [],
                'reasons': [],
                'review_statuses': DustSignalReview.STATUS_CHOICES,
            },
            'summary': {
                'total_detections': 51,
                'critical_count': 0,
                'warning_count': 0,
                'info_count': 51,
                'total_estimated_value_usdt': Decimal('12.75'),
                'latest_run_id': 'run-page-001',
                'latest_detected_at': timezone.now(),
            },
            'page_obj': SimpleNamespace(
                number=2,
                paginator=SimpleNamespace(num_pages=3, count=51),
                has_previous=lambda: True,
                has_next=lambda: True,
                previous_page_number=lambda: 1,
                next_page_number=lambda: 3,
            ),
            'pagination_querystring': 'severity=info',
        }
        self.client.force_login(self.user)

        response = self.client.get(reverse('dust_dashboard'), {'page': '2', 'severity': 'info'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Page 2 of 3')
        self.assertContains(response, '51 grouped signals')
        self.assertContains(response, 'page=1')
        self.assertContains(response, 'page=3')

    def test_dust_dashboard_unknown_filters_do_not_crash(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('dust_dashboard'), {
            'symbol': 'UNKNOWNUSDT',
            'severity': 'unknown',
            'reason': 'unknown_reason',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dust / Residuals')

    @patch('dashboard.views.get_dust_detail_context')
    def test_dust_detail_renders_latest_rows_and_null_payload(self, mock_get_detail_context):
        mock_get_detail_context.return_value.context = {
            'data_error': None,
            'filters': {
                'symbol': 'ETHUSDT',
                'asset': 'ETH',
                'reason': 'possible_incomplete_sell',
                'event_type': 'lot_below_min_notional_detected',
                'severity': 'info',
            },
            'group_identity': [
                {'label': 'Symbol', 'value': 'ETHUSDT'},
                {'label': 'Asset', 'value': 'ETH'},
                {'label': 'Reason', 'value': 'possible_incomplete_sell'},
                {'label': 'Event type', 'value': 'lot_below_min_notional_detected'},
                {'label': 'Severity', 'value': 'info'},
            ],
            'group_summary': {
                'detections_count': 2,
                'latest_detection_id': 9,
                'latest_detected_at': timezone.now(),
                'latest_run_id': 'run-detail-001',
                'latest_estimated_value_usdt': Decimal('0.415022396'),
                'latest_estimated_delta_value_usdt': Decimal('0'),
                'latest_suggested_action': 'review_recent_sell',
                'correction_status_label': 'No correction',
                'correction_badge': 'badge-light',
                'correction_statuses': [],
                'has_blocking_correction': False,
                'is_actionable': True,
            },
            'review': None,
            'review_status': DustSignalReview.STATUS_PENDING,
            'review_status_choices': DustSignalReview.STATUS_CHOICES,
            'raw_detections': [
                {
                    'row': SimpleNamespace(
                        id=9,
                        detected_at=timezone.now(),
                        run_id='run-detail-001',
                        spot_quantity=None,
                        open_lot_quantity=Decimal('0.00017708'),
                        quantity_delta=None,
                        price_usdt=Decimal('2343.70'),
                        estimated_value_usdt=Decimal('0.415022396'),
                        estimated_delta_value_usdt=None,
                        suggested_action='review_recent_sell',
                        source='dust_detection_service',
                    ),
                    'payload_text': 'No payload',
                    'has_payload': False,
                },
            ],
            'back_querystring': 'symbol=ETHUSDT&asset=ETH&reason=possible_incomplete_sell&event_type=lot_below_min_notional_detected&severity=info',
        }
        self.client.force_login(self.user)

        response = self.client.get(reverse('dust_detail'), {
            'symbol': 'ETHUSDT',
            'asset': 'ETH',
            'reason': 'possible_incomplete_sell',
            'event_type': 'lot_below_min_notional_detected',
            'severity': 'info',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dust Signal Detail')
        self.assertContains(response, 'Dashboard')
        self.assertContains(response, 'Dust / Residuals')
        self.assertContains(response, 'Back to Dust / Residuals')
        self.assertContains(response, 'ETHUSDT')
        self.assertContains(response, 'possible_incomplete_sell')
        self.assertContains(response, 'run-detail-001')
        self.assertContains(response, 'review_recent_sell')
        self.assertContains(response, 'dust_detection_service')
        self.assertContains(response, 'No payload')
        self.assertContains(response, 'Manual review')
        self.assertContains(response, 'Mark ignored')
        self.assertContains(response, 'Review later')
        self.assertContains(response, 'No correction')
        self.assertNotContains(response, 'Stop')
        self.assertNotContains(response, 'Resume')
        mock_get_detail_context.assert_called_once()

    def test_dust_detail_get_does_not_mutate_review_state(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('dust_detail'), {
            'symbol': 'BTCUSDT',
            'asset': 'BTC',
            'reason': 'below_min_notional',
            'event_type': 'dust_candidate_detected',
            'severity': 'info',
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(DustSignalReview.objects.count(), 0)

    def test_dust_detail_post_marks_signal_ignored(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('dust_detail'), {
            'symbol': 'BTCUSDT',
            'asset': 'BTC',
            'reason': 'below_min_notional',
            'event_type': 'dust_candidate_detected',
            'severity': 'info',
            'status': DustSignalReview.STATUS_IGNORED,
            'note': 'Known dust from old sell',
            'group_querystring': 'symbol=BTCUSDT&asset=BTC&reason=below_min_notional&event_type=dust_candidate_detected&severity=info',
        })

        self.assertEqual(response.status_code, 302)
        review = DustSignalReview.objects.get(
            symbol='BTCUSDT',
            asset='BTC',
            reason='below_min_notional',
            event_type='dust_candidate_detected',
            severity='info',
        )
        self.assertEqual(review.status, DustSignalReview.STATUS_IGNORED)
        self.assertEqual(review.note, 'Known dust from old sell')
        self.assertEqual(review.reviewed_by, self.user)
        self.assertIsNotNone(review.reviewed_at)

    def test_reviews_for_rows_handles_null_identity_without_name_error(self):
        review = DustSignalReview.objects.create(
            symbol='BTCUSDT',
            asset='',
            reason='below_min_notional',
            event_type='dust_candidate_detected',
            severity='info',
            status=DustSignalReview.STATUS_IGNORED,
        )

        reviews = _reviews_for_rows([{
            'symbol': 'BTCUSDT',
            'asset': None,
            'reason': 'below_min_notional',
            'event_type': 'dust_candidate_detected',
            'severity': 'info',
        }])

        self.assertEqual(
            reviews[('BTCUSDT', '', 'info', 'dust_candidate_detected', 'below_min_notional')],
            review,
        )

    def test_reviews_for_rows_missing_review_table_falls_back_to_pending(self):
        with patch(
            'dashboard.dust_read_model.DustSignalReview.objects.filter',
            side_effect=DatabaseError('relation "dust_signal_reviews" does not exist'),
        ):
            reviews = _reviews_for_rows([{
                'symbol': 'BTCUSDT',
                'asset': 'BTC',
                'reason': 'below_min_notional',
                'event_type': 'dust_candidate_detected',
                'severity': 'info',
            }])

        self.assertEqual(reviews, {})

    def test_dust_review_null_identity_does_not_create_duplicates(self):
        update_dust_signal_review({
            'symbol': 'BTCUSDT',
            'asset': '__null__',
            'reason': 'below_min_notional',
            'event_type': 'dust_candidate_detected',
            'severity': 'info',
        }, DustSignalReview.STATUS_IGNORED, 'First note', self.user)

        update_dust_signal_review({
            'symbol': 'BTCUSDT',
            'asset': '',
            'reason': 'below_min_notional',
            'event_type': 'dust_candidate_detected',
            'severity': 'info',
        }, DustSignalReview.STATUS_REVIEWED, 'Updated note', self.user)

        self.assertEqual(DustSignalReview.objects.count(), 1)
        review = DustSignalReview.objects.get()
        self.assertEqual(review.asset, '')
        self.assertEqual(review.status, DustSignalReview.STATUS_REVIEWED)
        self.assertEqual(review.note, 'Updated note')

    def test_dust_review_update_missing_review_table_does_not_crash(self):
        with patch(
            'dashboard.dust_read_model.DustSignalReview.objects.get_or_create',
            side_effect=DatabaseError('relation "dust_signal_reviews" does not exist'),
        ):
            review = update_dust_signal_review({
                'symbol': 'BTCUSDT',
                'asset': 'BTC',
                'reason': 'below_min_notional',
                'event_type': 'dust_candidate_detected',
                'severity': 'info',
            }, DustSignalReview.STATUS_REVIEWED, 'note', self.user)

        self.assertIsNone(review)

    def test_unauthenticated_user_cannot_update_dust_review(self):
        response = self.client.post(reverse('dust_detail'), {
            'symbol': 'BTCUSDT',
            'asset': 'BTC',
            'reason': 'below_min_notional',
            'event_type': 'dust_candidate_detected',
            'severity': 'info',
            'status': DustSignalReview.STATUS_REVIEWED,
        })

        self.assertEqual(response.status_code, 302)
        self.assertEqual(DustSignalReview.objects.count(), 0)

    def test_dust_review_migration_exists(self):
        migration_path = Path('core/migrations/0004_dustsignalreview.py')

        self.assertTrue(migration_path.exists())

    @patch('dashboard.views.get_dust_detail_context')
    def test_dust_detail_empty_group_state(self, mock_get_detail_context):
        mock_get_detail_context.return_value.context = {
            'data_error': None,
            'filters': {},
            'group_identity': [],
            'group_summary': None,
            'review': None,
            'review_status': DustSignalReview.STATUS_PENDING,
            'review_status_choices': DustSignalReview.STATUS_CHOICES,
            'raw_detections': [],
            'back_querystring': '',
        }
        self.client.force_login(self.user)

        response = self.client.get(reverse('dust_detail'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No detections found for this dust signal.')

    def test_dust_filters_are_cleaned(self):
        filters = _clean_filters({
            'symbol': ' BTCUSDT ',
            'severity': 'critical',
            'event_type': ' dust_candidate_detected ',
            'reason': ' below_min_notional ',
        })

        self.assertEqual(filters['symbol'], 'BTCUSDT')
        self.assertEqual(filters['severity'], 'critical')
        self.assertEqual(filters['event_type'], 'dust_candidate_detected')
        self.assertEqual(filters['reason'], 'below_min_notional')

    def test_dust_detail_filters_by_exact_group_fields(self):
        class FakeDustQuerySet:
            def __init__(self):
                self.filters = []

            def filter(self, **kwargs):
                self.filters.append(kwargs)
                return self

        query = FakeDustQuerySet()
        with patch('dashboard.dust_read_model.DustDetection.objects') as manager:
            manager.all.return_value = query
            _filtered_group_detections({
                'symbol': 'BTCUSDT',
                'asset': 'BTC',
                'reason': 'below_min_notional',
                'event_type': 'dust_candidate_detected',
                'severity': 'info',
            })

        self.assertEqual(query.filters, [
            {'symbol': 'BTCUSDT'},
            {'asset': 'BTC'},
            {'severity': 'info'},
            {'event_type': 'dust_candidate_detected'},
            {'reason': 'below_min_notional'},
        ])

    def test_dust_detail_null_group_filter_uses_isnull(self):
        class FakeDustQuerySet:
            def __init__(self):
                self.filters = []

            def filter(self, **kwargs):
                self.filters.append(kwargs)
                return self

        query = FakeDustQuerySet()
        with patch('dashboard.dust_read_model.DustDetection.objects') as manager:
            manager.all.return_value = query
            _filtered_group_detections({
                'symbol': 'BTCUSDT',
                'asset': None,
                'reason': 'below_min_notional',
                'event_type': 'dust_candidate_detected',
                'severity': 'info',
            })

        self.assertIn({'asset__isnull': True}, query.filters)

    def test_payload_formatting_is_safe(self):
        self.assertEqual(_format_payload(None), 'No payload')
        self.assertIn('"asset": "BTC"', _format_payload({'asset': 'BTC'}))
        self.assertIn('"asset": "BTC"', _format_payload('{"asset": "BTC"}'))
        self.assertEqual(_format_payload('not-json'), 'not-json')

    def test_dust_dashboard_default_scope_uses_latest_run_id(self):
        class FakeDustQuerySet:
            def __init__(self):
                self.filters = []

            def filter(self, **kwargs):
                self.filters.append(kwargs)
                return self

        query = FakeDustQuerySet()
        with patch('dashboard.dust_read_model._filtered_detections', return_value=query):
            with patch('dashboard.dust_read_model._latest_run_id', return_value='latest-run-001'):
                scoped = _dashboard_queryset({
                    'symbol': '',
                    'severity': '',
                    'event_type': '',
                    'reason': '',
                })

        self.assertIs(scoped, query)
        self.assertEqual(query.filters, [{'run_id': 'latest-run-001'}])

    def test_dust_dashboard_empty_table_uses_empty_queryset(self):
        class FakeDustQuerySet:
            def __init__(self):
                self.none_called = False

            def none(self):
                self.none_called = True
                return 'empty-queryset'

        query = FakeDustQuerySet()
        with patch('dashboard.dust_read_model._filtered_detections', return_value=query):
            with patch('dashboard.dust_read_model._latest_run_id', return_value=None):
                scoped = _dashboard_queryset({
                    'symbol': '',
                    'severity': '',
                    'event_type': '',
                    'reason': '',
                })

        self.assertEqual(scoped, 'empty-queryset')
        self.assertTrue(query.none_called)

    def test_dust_dashboard_filters_do_not_force_latest_run_scope(self):
        class FakeDustQuerySet:
            def __init__(self):
                self.filters = []

            def filter(self, **kwargs):
                self.filters.append(kwargs)
                return self

        query = FakeDustQuerySet()
        with patch('dashboard.dust_read_model._filtered_detections', return_value=query):
            with patch('dashboard.dust_read_model._latest_run_id') as mock_latest_run_id:
                scoped = _dashboard_queryset({
                    'symbol': 'BTCUSDT',
                    'severity': '',
                    'event_type': '',
                    'reason': '',
                })

        self.assertIs(scoped, query)
        self.assertEqual(query.filters, [])
        mock_latest_run_id.assert_not_called()

    def test_operator_guidance_labels_dust_and_drift_signals(self):
        below_min = _operator_guidance({
            'reason': 'below_min_notional',
            'event_type': 'dust_candidate_detected',
        })
        lots_greater = _operator_guidance({
            'reason': 'lot_balance_drift',
            'event_type': 'lot_balance_drift_detected',
            'latest_open_lot_quantity': Decimal('0.5'),
            'latest_spot_quantity': Decimal('0.2'),
        })
        binance_greater = _operator_guidance({
            'reason': 'balance_without_lot_coverage',
            'event_type': 'balance_without_lot_coverage_detected',
        })
        incomplete_sell = _operator_guidance({
            'reason': 'possible_incomplete_sell',
            'event_type': 'lot_below_min_notional_detected',
        })

        self.assertEqual(below_min['operator_label'], 'Below min notional')
        self.assertIn('Usually no action', below_min['operator_action'])
        self.assertEqual(lots_greater['operator_label'], 'Lots > Binance')
        self.assertEqual(lots_greater['operator_priority'], 'accounting drift, needs review')
        self.assertEqual(binance_greater['operator_label'], 'Binance balance without bot lot')
        self.assertIn('CREATE_EXTERNAL_LOT', binance_greater['operator_action'])
        self.assertEqual(incomplete_sell['operator_label'], 'Possible incomplete sell')
        self.assertIn('Review urgently', incomplete_sell['operator_action'])

    @patch('dashboard.dust_read_model._reviews_for_rows')
    def test_reviewed_dust_signal_suppresses_paging_but_keeps_history_row(self, mock_reviews):
        mock_reviews.return_value = {
            ('XRPUSDT', 'XRP', 'warning', 'lot_balance_drift_detected', 'manual_external_operation'):
                SimpleNamespace(
                    status=DustSignalReview.STATUS_IGNORED,
                    note='tiny dust',
                    reviewed_by=None,
                    reviewed_at=timezone.now(),
                )
        }
        rows = _with_review_state([{
            'symbol': 'XRPUSDT',
            'asset': 'XRP',
            'reason': 'manual_external_operation',
            'event_type': 'lot_balance_drift_detected',
            'severity': 'warning',
        }])

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['telegram_paging_suppressed'])
        self.assertIn('detections remain in history', rows[0]['review_effect_text'])

    @patch('dashboard.dust_read_model.ManualCorrection.objects')
    def test_detection_with_no_correction_shows_create_action_state(self, manager):
        manager.filter.return_value.order_by.return_value = []
        rows = _with_correction_state([{
            'latest_detection_id': 101,
            'latest_suggested_action': 'review_recent_sell',
            'operator_priority': 'warning',
            'review_status': DustSignalReview.STATUS_PENDING,
        }])

        self.assertEqual(rows[0]['correction_status_label'], 'No correction')
        self.assertFalse(rows[0]['has_blocking_correction'])
        self.assertTrue(rows[0]['is_actionable'])
        manager.filter.assert_called_once_with(source_detection_id__in=[101])

    @patch('dashboard.dust_read_model.ManualCorrection.objects')
    def test_pending_correction_disables_create_action_state(self, manager):
        manager.filter.return_value.order_by.return_value = [
            SimpleNamespace(source_detection_id=102, status=ManualCorrection.STATUS_PENDING, id=1)
        ]
        rows = _with_correction_state([{'latest_detection_id': 102}])

        self.assertEqual(rows[0]['correction_status_label'], 'Pending correction')
        self.assertTrue(rows[0]['has_blocking_correction'])
        self.assertFalse(rows[0]['is_actionable'])
        self.assertEqual(rows[0]['correction_block_message'], 'A correction request is already pending for this detection.')

    @patch('dashboard.dust_read_model.ManualCorrection.objects')
    def test_applied_correction_disables_create_action_state(self, manager):
        manager.filter.return_value.order_by.return_value = [
            SimpleNamespace(source_detection_id=103, status=ManualCorrection.STATUS_APPLIED, id=2)
        ]
        rows = _with_correction_state([{'latest_detection_id': 103}])

        self.assertEqual(rows[0]['correction_status_label'], 'Applied correction')
        self.assertTrue(rows[0]['has_blocking_correction'])
        self.assertFalse(rows[0]['is_actionable'])
        self.assertEqual(rows[0]['correction_block_message'], 'A correction was already applied for this detection.')

    @patch('dashboard.dust_read_model.ManualCorrection.objects')
    def test_rejected_correction_allows_new_request_state(self, manager):
        manager.filter.return_value.order_by.return_value = [
            SimpleNamespace(source_detection_id=104, status=ManualCorrection.STATUS_REJECTED, id=3)
        ]
        rows = _with_correction_state([{'latest_detection_id': 104}])

        self.assertEqual(rows[0]['correction_status_label'], 'Rejected correction')
        self.assertFalse(rows[0]['has_blocking_correction'])
        self.assertTrue(rows[0]['is_actionable'])

    @patch('dashboard.dust_read_model.ManualCorrection.objects')
    def test_failed_correction_allows_new_request_state(self, manager):
        manager.filter.return_value.order_by.return_value = [
            SimpleNamespace(source_detection_id=105, status=ManualCorrection.STATUS_FAILED, id=4)
        ]
        rows = _with_correction_state([{'latest_detection_id': 105}])

        self.assertEqual(rows[0]['correction_status_label'], 'Failed correction')
        self.assertFalse(rows[0]['has_blocking_correction'])
        self.assertTrue(rows[0]['is_actionable'])

    @patch('dashboard.dust_read_model.ManualCorrection.objects')
    def test_correction_state_batches_by_source_detection_id(self, manager):
        manager.filter.return_value.order_by.return_value = []
        _with_correction_state([
            {'latest_detection_id': 201},
            {'latest_detection_id': 202},
            {'latest_detection_id': 201},
            {'latest_detection_id': None},
        ])

        manager.filter.assert_called_once_with(source_detection_id__in=[201, 202])

    def test_pending_review_filter_keeps_only_pending_rows(self):
        rows = [
            {'symbol': 'BTCUSDT', 'review_status': DustSignalReview.STATUS_PENDING},
            {'symbol': 'ETHUSDT', 'review_status': DustSignalReview.STATUS_IGNORED},
        ]

        filtered = _filter_by_review_status(rows, DustSignalReview.STATUS_PENDING)

        self.assertEqual(filtered, [{'symbol': 'BTCUSDT', 'review_status': DustSignalReview.STATUS_PENDING}])

    def test_active_operational_issues_exclude_info_below_min_when_warnings_exist(self):
        now = timezone.now()
        rows = [
            {
                'symbol': 'INFOUSDT',
                'severity': 'info',
                'reason': 'below_min_notional',
                'display_reason': 'Below min notional',
                'latest_detected_at': now,
                'latest_estimated_value_usdt': Decimal('0.25'),
                'review_status': DustSignalReview.STATUS_PENDING,
                'has_blocking_correction': False,
            },
            {
                'symbol': 'WARNUSDT',
                'severity': 'warning',
                'reason': 'lot_balance_drift',
                'display_reason': 'Lots > Binance',
                'latest_detected_at': now - timezone.timedelta(minutes=5),
                'latest_estimated_value_usdt': Decimal('3.00'),
                'review_status': DustSignalReview.STATUS_PENDING,
                'has_blocking_correction': False,
            },
        ]

        issues = _active_operational_issues(rows)

        self.assertEqual([row['symbol'] for row in issues], ['WARNUSDT'])

    def test_active_operational_issues_do_not_fallback_to_info_only_residuals(self):
        rows = [
            {
                'symbol': 'INFOUSDT',
                'severity': 'info',
                'reason': 'below_min_notional',
                'display_reason': 'Below min notional',
                'latest_detected_at': timezone.now(),
                'latest_estimated_value_usdt': Decimal('0.25'),
                'review_status': DustSignalReview.STATUS_PENDING,
                'has_blocking_correction': False,
            },
        ]

        issues = _active_operational_issues(rows)

        self.assertEqual(issues, [])

    def test_informational_residual_summary_counts_info_only_residuals(self):
        now = timezone.now()
        rows = [
            {
                'symbol': 'INFOUSDT',
                'severity': 'info',
                'reason': 'below_min_notional',
                'latest_detected_at': now,
                'latest_estimated_value_usdt': Decimal('0.25'),
                'review_status': DustSignalReview.STATUS_PENDING,
                'has_blocking_correction': False,
            },
            {
                'symbol': 'IGNOREDUSDT',
                'severity': 'info',
                'reason': 'below_min_notional',
                'latest_detected_at': now - timezone.timedelta(minutes=5),
                'latest_estimated_value_usdt': Decimal('0.75'),
                'review_status': DustSignalReview.STATUS_IGNORED,
                'has_blocking_correction': False,
            },
        ]

        summary = _informational_residual_summary(rows)

        self.assertEqual(summary['count'], 1)
        self.assertEqual(summary['total_estimated_value_usdt'], Decimal('0.25'))
        self.assertEqual(summary['latest_detected_at'], now)

    def test_active_operational_issues_exclude_reviewed_ignored_and_blocked_signals(self):
        now = timezone.now()
        rows = [
            {
                'symbol': 'ACTIVEUSDT',
                'severity': 'critical',
                'reason': 'lot_balance_drift',
                'latest_detected_at': now,
                'review_status': DustSignalReview.STATUS_PENDING,
                'has_blocking_correction': False,
            },
            {
                'symbol': 'IGNOREDUSDT',
                'severity': 'critical',
                'reason': 'lot_balance_drift',
                'latest_detected_at': now,
                'review_status': DustSignalReview.STATUS_IGNORED,
                'has_blocking_correction': False,
            },
            {
                'symbol': 'REVIEWEDUSDT',
                'severity': 'warning',
                'reason': 'possible_incomplete_sell',
                'latest_detected_at': now,
                'review_status': DustSignalReview.STATUS_REVIEWED,
                'has_blocking_correction': False,
            },
            {
                'symbol': 'BLOCKEDUSDT',
                'severity': 'warning',
                'reason': 'lot_balance_drift',
                'latest_detected_at': now,
                'review_status': DustSignalReview.STATUS_PENDING,
                'has_blocking_correction': True,
            },
        ]

        issues = _active_operational_issues(rows)

        self.assertEqual([row['symbol'] for row in issues], ['ACTIVEUSDT'])

    def test_dust_dashboard_timeout_returns_safe_defaults(self):
        with patch('dashboard.dust_read_model._dashboard_queryset', return_value=object()):
            with patch('dashboard.dust_read_model._build_filter_options', return_value={
                'symbols': [],
                'severities': [],
                'event_types': [],
                'reasons': [],
            }):
                with patch('dashboard.dust_read_model._grouped_detections', side_effect=DatabaseError('statement timeout')):
                    read_model = get_dust_dashboard_context({})

        self.assertEqual(read_model.context['dust_error'], 'Query too slow')
        self.assertEqual(read_model.context['grouped_detections'], [])
        self.assertEqual(read_model.context['summary']['critical_count'], 0)

    def test_dust_detection_model_is_read_only_bot_table(self):
        self.assertFalse(DustDetection._meta.managed)
        self.assertEqual(DustDetection._meta.db_table, '"bot"."dust_detections"')
        fields = [field.name for field in DustDetection._meta.fields]
        self.assertIn('spot_quantity', fields)
        self.assertIn('open_lot_quantity', fields)
        self.assertIn('price_usdt', fields)
        self.assertIn('payload', fields)
        self.assertIn('created_at', fields)
        self.assertIn('estimated_value_usdt', fields)
        self.assertIn('estimated_delta_value_usdt', fields)

    def test_dust_summary_uses_latest_grouped_exposure(self):
        class FakeDustQuerySet:
            def count(self):
                return 5

        latest = SimpleNamespace(
            run_id='latest-run',
            detected_at=timezone.now(),
        )
        grouped_rows = [
            {
                'severity': 'critical',
                'latest_estimated_value_usdt': Decimal('1.25'),
            },
            {
                'severity': 'warning',
                'latest_estimated_value_usdt': Decimal('2.50'),
            },
            {
                'severity': 'warning',
                'latest_estimated_value_usdt': None,
            },
            {
                'severity': 'info',
                'latest_estimated_value_usdt': Decimal('0.05'),
            },
        ]

        with patch('dashboard.dust_read_model._grouped_detections', return_value=grouped_rows):
            with patch('dashboard.dust_read_model._latest_detection_row', return_value=latest):
                summary = _build_summary(FakeDustQuerySet())

        self.assertEqual(summary['total_detections'], 5)
        self.assertEqual(summary['critical_count'], 1)
        self.assertEqual(summary['warning_count'], 2)
        self.assertEqual(summary['info_count'], 1)
        self.assertEqual(summary['total_estimated_value_usdt'], Decimal('3.80'))
        self.assertEqual(summary['latest_run_id'], 'latest-run')

    def test_stale_healthcheck_detection(self):
        stale_row = SimpleNamespace(
            status='ok',
            probe_message='old heartbeat',
            created_at=timezone.now() - timezone.timedelta(minutes=16),
            details={'read_only': True},
        )
        with patch('dashboard.dashboard_read_model.BotHealthcheck.objects') as manager:
            manager.order_by.return_value.first.return_value = stale_row

            status = _build_bot_status()

        self.assertTrue(status['is_stale'])
        self.assertEqual(status['read_only'], True)
        self.assertEqual(status['badge_label'], 'stale')
        self.assertEqual(status['badge_class'], 'badge-warning')

    def test_bot_health_badge_normalizes_uppercase_ok_to_healthy(self):
        row = SimpleNamespace(
            status='OK',
            probe_message='heartbeat',
            created_at=timezone.now(),
            details={'read_only': True},
        )
        with patch('dashboard.dashboard_read_model.BotHealthcheck.objects') as manager:
            manager.order_by.return_value.first.return_value = row

            status = _build_bot_status()

        self.assertEqual(status['badge_label'], 'healthy')
        self.assertEqual(status['badge_class'], 'badge-success')

    def test_bot_health_badge_normalizes_lowercase_ok_to_healthy(self):
        row = SimpleNamespace(
            status='ok',
            probe_message='heartbeat',
            created_at=timezone.now(),
            details={'read_only': True},
        )
        with patch('dashboard.dashboard_read_model.BotHealthcheck.objects') as manager:
            manager.order_by.return_value.first.return_value = row

            status = _build_bot_status()

        self.assertEqual(status['badge_label'], 'healthy')
        self.assertEqual(status['badge_class'], 'badge-success')

    def test_bot_health_badge_maps_missing_row_to_unknown(self):
        with patch('dashboard.dashboard_read_model.BotHealthcheck.objects') as manager:
            manager.order_by.return_value.first.return_value = None

            status = _build_bot_status()

        self.assertEqual(status['badge_label'], 'unknown')
        self.assertEqual(status['badge_class'], 'badge-secondary')

    def test_bot_health_badge_maps_error_to_error(self):
        row = SimpleNamespace(
            status='error',
            probe_message='failed',
            created_at=timezone.now(),
            details={'read_only': True},
        )
        with patch('dashboard.dashboard_read_model.BotHealthcheck.objects') as manager:
            manager.order_by.return_value.first.return_value = row

            status = _build_bot_status()

        self.assertEqual(status['badge_label'], 'error')
        self.assertEqual(status['badge_class'], 'badge-danger')

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
        with patch('dashboard.dashboard_read_model.TradeOperation.objects', query):
            summary = _build_fee_summary()

        self.assertEqual(summary['asset_count'], 2)
        self.assertEqual(summary['fill_count'], 7)
        self.assertEqual(summary['rows'][0]['asset'], 'BNB')
        self.assertIn(('filter', {'fee_amount__isnull': False}), query.calls)
        self.assertIn(('values', ('fee_asset',)), query.calls)
        self.assertIn(('order_by', ('fee_asset',)), query.calls)

    def test_quote_fee_summary_uses_filled_usdt_trade_operations(self):
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
                    {
                        'side': 'BUY',
                        'total_fee_usdt': Decimal('2.10'),
                        'operations_count': 3,
                    },
                    {
                        'side': 'SELL',
                        'total_fee_usdt': Decimal('1.32'),
                        'operations_count': 2,
                    },
                ]

        query = FakeTradeOperationQuery()
        with patch('dashboard.dashboard_read_model.TradeOperation.objects', query):
            summary = _build_quote_fee_summary()

        self.assertEqual(summary['total_fees_usdt'], Decimal('3.42'))
        self.assertEqual(summary['total_operations'], 5)
        self.assertEqual(summary['by_side']['BUY']['total_fee_usdt'], Decimal('2.10'))
        self.assertEqual(summary['by_side']['SELL']['operations_count'], 2)
        self.assertIn(('filter', {'status': 'FILLED', 'quote_asset': 'USDT'}), query.calls)
        self.assertIn(('values', ('side',)), query.calls)
        self.assertIn(('order_by', ('side',)), query.calls)

    def test_performance_kpi_read_model_does_not_query_lot_closure_timestamp(self):
        class FakeLotClosureQuery:
            def __init__(self):
                self.values_fields = None
                self.order_fields = None

            def values(self, *fields):
                self.values_fields = fields
                return self

            def order_by(self, *fields):
                self.order_fields = fields
                return [
                    {'trade_operation_id': 1, 'realized_pnl': Decimal('3')},
                ]

        class FakeTradeOperationQuery:
            def __init__(self):
                self.values_calls = []

            def filter(self, **kwargs):
                return self

            def values(self, *fields):
                self.values_calls.append(fields)
                if 'id' in fields:
                    return [
                        {
                            'id': 1,
                            'symbol': 'BTCUSDT',
                            'client_order_id': '',
                            'raw_payload': {},
                            'executed_at': timezone.datetime(2026, 5, 1, 9, tzinfo=timezone.utc),
                            'created_at': timezone.datetime(2026, 5, 1, 8, tzinfo=timezone.utc),
                        },
                    ]
                if 'fee_amount_in_quote' in fields:
                    return []
                return []

        lot_query = FakeLotClosureQuery()
        trade_query = FakeTradeOperationQuery()

        with patch('dashboard.dashboard_read_model.LotClosure.objects', lot_query):
            with patch('dashboard.dashboard_read_model.TradeOperation.objects', trade_query):
                summary = _build_performance_kpis()

        self.assertEqual(lot_query.values_fields, ('trade_operation_id', 'realized_pnl'))
        self.assertNotIn('timestamp', lot_query.order_fields)
        self.assertIn(
            ('id', 'symbol', 'client_order_id', 'raw_payload', 'executed_at', 'created_at'),
            trade_query.values_calls,
        )
        self.assertEqual(summary['pnl_by_day'][0]['date'].isoformat(), '2026-05-01')

    def test_lot_closure_model_does_not_map_missing_timestamp_column(self):
        self.assertNotIn('timestamp', [field.name for field in LotClosure._meta.fields])

    def test_operational_kpis_lot_link_models_use_lot_id_fields(self):
        self.assertIn('lot_id', [field.name for field in LotClosure._meta.fields])
        self.assertIn('lot_id', [field.name for field in PositionLot._meta.fields])

    def test_performance_kpis_calculate_realized_pnl_fees_and_deployed_capital(self):
        closure_rows = [
            {
                'trade_operation_id': 1,
                'realized_pnl': Decimal('12.50'),
            },
            {
                'trade_operation_id': 2,
                'realized_pnl': Decimal('-4.25'),
            },
        ]
        operation_rows = {
            1: {'symbol': 'BTCUSDT', 'manual_correction': False},
            2: {'symbol': 'ETHUSDT', 'manual_correction': False},
        }
        fee_rows = [
            {'fee_amount_in_quote': Decimal('0.50')},
            {'fee_amount_in_quote': Decimal('0.25')},
            {'fee_amount_in_quote': None},
        ]
        buy_rows = [
            {'gross_quote': Decimal('100.00')},
            {'gross_quote': Decimal('25.25')},
            {'gross_quote': None},
        ]

        summary = _calculate_performance_kpis(
            closure_rows,
            operation_rows,
            fee_rows,
            buy_rows,
        )

        self.assertEqual(summary['gross_realized_pnl'], Decimal('8.25'))
        self.assertEqual(summary['total_fees_usdt'], Decimal('0.75'))
        self.assertEqual(summary['net_realized_pnl'], Decimal('7.50'))
        self.assertEqual(summary['gross_deployed_capital'], Decimal('125.25'))

    def test_performance_kpis_calculate_win_rate_averages_and_profit_factor(self):
        closure_rows = [
            {'trade_operation_id': 1, 'realized_pnl': Decimal('10')},
            {'trade_operation_id': 1, 'realized_pnl': Decimal('5')},
            {'trade_operation_id': 2, 'realized_pnl': Decimal('-3')},
            {'trade_operation_id': 3, 'realized_pnl': Decimal('0')},
        ]

        summary = _calculate_performance_kpis(closure_rows, {}, [], [])

        self.assertEqual(summary['winning_closures_count'], 2)
        self.assertEqual(summary['losing_closures_count'], 1)
        self.assertEqual(summary['breakeven_closures_count'], 1)
        self.assertEqual(summary['win_rate'], Decimal('66.66666666666666666666666667'))
        self.assertEqual(summary['average_win'], Decimal('7.5'))
        self.assertEqual(summary['average_loss'], Decimal('-3'))
        self.assertEqual(summary['profit_factor'], Decimal('5'))

    def test_performance_kpis_zero_loss_profit_factor_is_none(self):
        closure_rows = [
            {'trade_operation_id': 1, 'realized_pnl': Decimal('10')},
            {'trade_operation_id': 1, 'realized_pnl': Decimal('2')},
        ]

        summary = _calculate_performance_kpis(closure_rows, {}, [], [])

        self.assertIsNone(summary['profit_factor'])

    def test_performance_kpis_ignore_nulls_without_crashing(self):
        closure_rows = [
            {'trade_operation_id': None, 'realized_pnl': None},
            {'trade_operation_id': 1, 'realized_pnl': Decimal('2')},
        ]
        fee_rows = [{'fee_amount_in_quote': None}]
        buy_rows = [{'gross_quote': None}]

        summary = _calculate_performance_kpis(closure_rows, {}, fee_rows, buy_rows)

        self.assertEqual(summary['closures_count'], 1)
        self.assertEqual(summary['gross_realized_pnl'], Decimal('2'))
        self.assertEqual(summary['total_fees_usdt'], Decimal('0'))
        self.assertEqual(summary['gross_deployed_capital'], Decimal('0'))

    def test_performance_kpis_split_identifiable_manual_corrections(self):
        closure_rows = [
            {'trade_operation_id': 1, 'realized_pnl': Decimal('8')},
            {'trade_operation_id': 2, 'realized_pnl': Decimal('-2')},
        ]
        operation_rows = {
            1: {'symbol': 'BTCUSDT', 'manual_correction': False},
            2: {'symbol': 'ETHUSDT', 'manual_correction': True},
        }

        summary = _calculate_performance_kpis(closure_rows, operation_rows, [], [])

        self.assertEqual(summary['bot_realized_pnl'], Decimal('8'))
        self.assertEqual(summary['manual_adjustment_pnl'], Decimal('-2'))
        self.assertTrue(summary['manual_corrections_split_available'])

    def test_performance_kpis_group_pnl_by_symbol_and_day_from_operation_timestamp(self):
        closure_rows = [
            {
                'trade_operation_id': 1,
                'realized_pnl': Decimal('3'),
            },
            {
                'trade_operation_id': 1,
                'realized_pnl': Decimal('4'),
            },
            {
                'trade_operation_id': 2,
                'realized_pnl': Decimal('-1'),
            },
            {
                'trade_operation_id': 3,
                'realized_pnl': Decimal('2'),
            },
        ]
        operation_rows = {
            1: {
                'symbol': 'BTCUSDT',
                'manual_correction': False,
                'timestamp': timezone.datetime(2026, 5, 1, 9, tzinfo=timezone.utc),
            },
            2: {
                'symbol': 'ETHUSDT',
                'manual_correction': False,
                'timestamp': timezone.datetime(2026, 5, 2, 9, tzinfo=timezone.utc),
            },
            3: {'symbol': 'SOLUSDT', 'manual_correction': False, 'timestamp': None},
        }

        summary = _calculate_performance_kpis(closure_rows, operation_rows, [], [])

        self.assertEqual(summary['pnl_by_symbol'][0]['symbol'], 'BTCUSDT')
        self.assertEqual(summary['pnl_by_symbol'][0]['realized_pnl'], Decimal('7'))
        self.assertEqual(summary['pnl_by_symbol'][0]['closures_count'], 2)
        self.assertEqual(summary['pnl_by_day'][0]['date'].isoformat(), '2026-05-01')
        self.assertEqual(summary['pnl_by_day'][0]['realized_pnl'], Decimal('7'))
        self.assertEqual(summary['pnl_by_day'][1]['date'].isoformat(), '2026-05-02')
        self.assertEqual(summary['gross_realized_pnl'], Decimal('8'))
        self.assertEqual(len(summary['pnl_by_day']), 2)

    def test_valuation_consistency_matching_portfolio_and_lots_values(self):
        portfolio_rows = [
            SimpleNamespace(
                symbol='BTCUSDT',
                quantity=Decimal('0.001'),
                current_price=Decimal('20000.00'),
            ),
        ]
        open_lots = {
            'BTCUSDT': {'open_quantity': Decimal('0.001'), 'open_lot_count': 1},
        }

        summary = _build_valuation_consistency(portfolio_rows, open_lots)

        self.assertEqual(summary['portfolio_value'], Decimal('20.00000'))
        self.assertEqual(summary['lots_value'], Decimal('20.00000'))
        self.assertEqual(summary['drift_value'], Decimal('0.00000'))
        self.assertEqual(summary['portfolio_missing_price_count'], 0)
        self.assertEqual(summary['lots_missing_price_count'], 0)

    def test_valuation_consistency_surfaces_drift(self):
        portfolio_rows = [
            SimpleNamespace(
                symbol='ETHUSDT',
                quantity=Decimal('0.010'),
                current_price=Decimal('2000.00'),
            ),
        ]
        open_lots = {
            'ETHUSDT': {'open_quantity': Decimal('0.009'), 'open_lot_count': 1},
        }

        summary = _build_valuation_consistency(portfolio_rows, open_lots)

        self.assertEqual(summary['portfolio_value'], Decimal('20.00000'))
        self.assertEqual(summary['lots_value'], Decimal('18.00000'))
        self.assertEqual(summary['drift_value'], Decimal('2.00000'))

    def test_valuation_consistency_counts_missing_current_prices(self):
        portfolio_rows = [
            SimpleNamespace(
                symbol='BNBUSDT',
                quantity=Decimal('0.25'),
                current_price=None,
            ),
        ]
        open_lots = {
            'BNBUSDT': {'open_quantity': Decimal('0.25'), 'open_lot_count': 1},
            'ADAUSDT': {'open_quantity': Decimal('10'), 'open_lot_count': 1},
        }

        summary = _build_valuation_consistency(portfolio_rows, open_lots)

        self.assertEqual(summary['portfolio_value'], Decimal('0'))
        self.assertEqual(summary['lots_value'], Decimal('0'))
        self.assertEqual(summary['drift_value'], Decimal('0'))
        self.assertEqual(summary['portfolio_missing_price_count'], 1)
        self.assertEqual(summary['lots_missing_price_count'], 2)
        self.assertTrue(summary['has_missing_prices'])

    def test_valuation_consistency_handles_empty_portfolio_and_lots(self):
        summary = _build_valuation_consistency([], {})

        self.assertEqual(summary['portfolio_value'], Decimal('0'))
        self.assertEqual(summary['lots_value'], Decimal('0'))
        self.assertEqual(summary['drift_value'], Decimal('0'))
        self.assertEqual(summary['portfolio_rows_count'], 0)
        self.assertEqual(summary['open_lots_symbol_count'], 0)

    def test_valuation_consistency_uses_decimal_safe_calculations(self):
        portfolio_rows = [
            SimpleNamespace(
                symbol='SOLUSDT',
                quantity=Decimal('0.333333333333333333'),
                current_price=Decimal('19.700000000000000000'),
            ),
        ]
        open_lots = {
            'SOLUSDT': {
                'open_quantity': Decimal('0.333333333333333333'),
                'open_lot_count': 1,
            },
        }

        summary = _build_valuation_consistency(portfolio_rows, open_lots)

        self.assertIsInstance(summary['portfolio_value'], Decimal)
        self.assertEqual(
            summary['portfolio_value'],
            Decimal('6.566666666666666660100000000000000000'),
        )

    def test_position_exit_status_classifies_hold_dust_and_drift(self):
        open_lots = {
            'ZECUSDT': {'symbol': 'ZECUSDT', 'open_quantity': Decimal('0.5'), 'open_lot_count': 1},
            'ETHUSDT': {'symbol': 'ETHUSDT', 'open_quantity': Decimal('0.001'), 'open_lot_count': 1},
            'ORDIUSDT': {'symbol': 'ORDIUSDT', 'open_quantity': Decimal('3'), 'open_lot_count': 2},
        }
        portfolio_rows = [
            SimpleNamespace(symbol='ZECUSDT', asset='ZEC', quantity=Decimal('0.5'), current_price=Decimal('84.50')),
            SimpleNamespace(symbol='ETHUSDT', asset='ETH', quantity=Decimal('0.001'), current_price=Decimal('2300')),
            SimpleNamespace(symbol='ORDIUSDT', asset='ORDI', quantity=Decimal('2'), current_price=Decimal('6')),
        ]
        sell_events = {
            'ZECUSDT': SimpleNamespace(
                symbol='ZECUSDT',
                reason='strategy_thresholds_not_reached',
                current_price=Decimal('84.50'),
                stop_loss_threshold=Decimal('-3'),
                take_profit_threshold=Decimal('5'),
                created_at=timezone.now(),
                payload={'reasons': ['stop_loss_not_reached', 'take_profit_not_reached'], 'run_id': 'run-1'},
            ),
            'ETHUSDT': SimpleNamespace(
                symbol='ETHUSDT',
                reason='quantity_below_min_notional',
                current_price=Decimal('2300'),
                stop_loss_threshold=None,
                take_profit_threshold=None,
                created_at=timezone.now(),
                payload={'reasons': ['quantity_below_min_notional', 'dust_residual_protection']},
            ),
            'ORDIUSDT': SimpleNamespace(
                symbol='ORDIUSDT',
                reason='insufficient_binance_balance',
                current_price=Decimal('6'),
                stop_loss_threshold=None,
                take_profit_threshold=None,
                created_at=timezone.now(),
                payload={'reason': 'insufficient_binance_balance'},
            ),
        }

        summary = _build_position_exit_status(open_lots, portfolio_rows, sell_events)
        rows_by_symbol = {row['symbol']: row for row in summary['rows']}

        self.assertEqual(rows_by_symbol['ZECUSDT']['status_label'], 'Holding')
        self.assertEqual(rows_by_symbol['ZECUSDT']['main_reason'], 'stop_loss not reached, take_profit not reached')
        self.assertEqual(rows_by_symbol['ZECUSDT']['suggested_action'], 'No action. Continue monitoring.')
        self.assertEqual(rows_by_symbol['ETHUSDT']['status_label'], 'Dust / Below minNotional')
        self.assertEqual(rows_by_symbol['ETHUSDT']['estimated_value_usdt'], Decimal('2.300'))
        self.assertEqual(rows_by_symbol['ETHUSDT']['suggested_action'], 'Review as dust. It may become reusable if future buys increase the balance.')
        self.assertEqual(rows_by_symbol['ORDIUSDT']['status_label'], 'Drift / Review needed')
        self.assertEqual(rows_by_symbol['ORDIUSDT']['suggested_action'], 'Review for manual/external operation, Earn movement, fee residual, or incomplete sell.')
        self.assertEqual(summary['material_count'], 2)
        self.assertEqual(summary['dust_count'], 1)

    def test_inventory_scope_summary_distinguishes_lots_from_excluded_balances(self):
        portfolio_rows = [
            SimpleNamespace(symbol='ZECUSDT', asset='ZEC', quantity=Decimal('0.5'), current_price=Decimal('84.50')),
            SimpleNamespace(symbol='USDCUSDT', asset='USDC', quantity=Decimal('25'), current_price=Decimal('1')),
            SimpleNamespace(symbol='ABCUSDT', asset='ABC', quantity=Decimal('2'), current_price=Decimal('3')),
        ]
        open_lots = {
            'ZECUSDT': {'symbol': 'ZECUSDT', 'open_quantity': Decimal('0.5')},
        }
        position_exit_status = {'material_count': 1, 'dust_count': 0}

        summary = _build_inventory_scope_summary(portfolio_rows, open_lots, position_exit_status)

        self.assertIsNone(summary['spot_assets_count'])
        self.assertEqual(summary['bot_managed_lot_symbols_count'], 1)
        self.assertEqual(summary['material_tradable_positions_count'], 1)
        self.assertEqual(summary['excluded_balances_count'], 2)
        self.assertEqual(
            [row['symbol'] for row in summary['excluded_balances']],
            ['ABCUSDT', 'USDCUSDT'],
        )
        self.assertEqual(summary['excluded_balances'][1]['reason'], 'stablecoin cash balance')

    def test_latest_sell_events_by_symbol_keeps_latest_open_lot_event_only(self):
        older = SimpleNamespace(symbol='ZECUSDT', id=1)
        latest = SimpleNamespace(symbol='ZECUSDT', id=2)
        unrelated = SimpleNamespace(symbol='BTCUSDT', id=3)
        eth = SimpleNamespace(symbol='ETHUSDT', id=4)

        class FakeSellDecisionEventQuery:
            def __init__(self):
                self.filter_kwargs = None
                self.order_fields = None

            def filter(self, **kwargs):
                self.filter_kwargs = kwargs
                return self

            def order_by(self, *fields):
                self.order_fields = fields
                return self

            def __getitem__(self, item):
                self.slice = item
                return [latest, eth, older]

        query = FakeSellDecisionEventQuery()
        open_lots = {'ZECUSDT': {}, 'ETHUSDT': {}, 'ADAUSDT': {}}

        with patch('dashboard.dashboard_read_model.SellDecisionEvent.objects', query):
            events = _latest_sell_events_by_symbol(open_lots)

        self.assertEqual(query.filter_kwargs, {'symbol__in': ['ZECUSDT', 'ETHUSDT', 'ADAUSDT']})
        self.assertEqual(query.order_fields, ('-created_at', '-id'))
        self.assertEqual(query.slice, slice(None, 200, None))
        self.assertEqual(events, {'ZECUSDT': latest, 'ETHUSDT': eth})
        self.assertNotIn('ADAUSDT', events)
        self.assertNotIn(unrelated.symbol, events)

    def test_latest_sell_events_by_symbol_returns_empty_mapping_when_query_fails(self):
        class FailingSellDecisionEventQuery:
            def filter(self, **kwargs):
                raise DatabaseError('missing diagnostics table')

        with patch('dashboard.dashboard_read_model.logger') as logger:
            with patch('dashboard.dashboard_read_model.SellDecisionEvent.objects', FailingSellDecisionEventQuery()):
                events = _latest_sell_events_by_symbol({'ZECUSDT': {}})

        self.assertEqual(events, {})
        logger.warning.assert_called_once()
        logger.exception.assert_not_called()

    def test_latest_sell_events_for_exit_status_uses_bounded_recent_window_without_n_plus_one(self):
        older = SimpleNamespace(symbol='BTCUSDT', id=1)
        latest = SimpleNamespace(symbol='BTCUSDT', id=2)
        eth = SimpleNamespace(symbol='ETHUSDT', id=3)

        class FakeSellDecisionEventQuery:
            def __init__(self):
                self.filter_calls = 0

            def filter(self, **kwargs):
                self.filter_calls += 1
                self.filter_kwargs = kwargs
                return self

            def order_by(self, *fields):
                self.order_fields = fields
                return self

            def __getitem__(self, item):
                self.slice = item
                return [latest, eth, older]

        query = FakeSellDecisionEventQuery()
        with patch('dashboard.dashboard_read_model.SellDecisionEvent.objects', query):
            events = _latest_sell_events_for_exit_status({'BTCUSDT': {}, 'ETHUSDT': {}})

        self.assertEqual(query.filter_calls, 0)
        self.assertEqual(query.order_fields, ('-created_at', '-id'))
        self.assertEqual(query.slice, slice(None, 1000, None))
        self.assertEqual(events, {'BTCUSDT': latest, 'ETHUSDT': eth})

    def test_homepage_skips_sell_diagnostics_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(_homepage_sell_diagnostics_enabled())

    def test_homepage_env_flag_enables_sell_diagnostics(self):
        with patch.dict(os.environ, {'DASHBOARD_INCLUDE_SELL_DIAGNOSTICS': 'true'}):
            self.assertTrue(_homepage_sell_diagnostics_enabled())

    def test_position_exit_rows_render_without_loaded_diagnostics(self):
        summary = _build_position_exit_status(
            {'ZECUSDT': {'open_quantity': Decimal('1'), 'open_lot_count': 1}},
            [SimpleNamespace(symbol='ZECUSDT', asset='ZEC', quantity=Decimal('1'), current_price=Decimal('5'))],
            {},
            diagnostics_loaded=False,
        )

        row = summary['rows'][0]
        self.assertEqual(row['status_label'], 'Open Exit Status')
        self.assertEqual(row['main_reason'], 'open full page')

    def test_unknown_sell_reason_maps_to_review(self):
        rows = _build_position_exit_status(
            {'BTCUSDT': {'open_quantity': Decimal('1'), 'open_lot_count': 1}},
            [SimpleNamespace(symbol='BTCUSDT', asset='BTC', quantity=Decimal('1'), current_price=Decimal('10'))],
            {'BTCUSDT': SimpleNamespace(reason='brand_new_reason', payload={}, created_at=timezone.now())},
        )['rows']

        self.assertEqual(rows[0]['status_label'], 'Review')

    def test_missing_exit_status_diagnostic_maps_to_review_when_query_succeeds(self):
        row = _build_position_exit_status(
            {'BTCUSDT': {'open_quantity': Decimal('1'), 'open_lot_count': 1}},
            [SimpleNamespace(symbol='BTCUSDT', asset='BTC', quantity=Decimal('1'), current_price=Decimal('10'))],
            {},
            diagnostics_loaded=True,
        )['rows'][0]

        self.assertEqual(row['status_label'], 'Review')

    def test_exit_status_context_keeps_open_lots_when_diagnostics_query_fails(self):
        with patch('dashboard.dashboard_read_model.Portfolio.objects') as portfolio_manager:
            portfolio_manager.all.return_value.order_by.return_value = [
                SimpleNamespace(symbol='BTCUSDT', asset='BTC', quantity=Decimal('1'), current_price=Decimal('10'))
            ]
            with patch(
                'dashboard.dashboard_read_model._open_lots_by_symbol',
                return_value={'BTCUSDT': {'open_quantity': Decimal('1'), 'open_lot_count': 1}},
            ):
                with patch(
                    'dashboard.dashboard_read_model._latest_sell_events_for_exit_status',
                    side_effect=DatabaseError('diagnostics unavailable'),
                ):
                    context = get_exit_status_context().context

        self.assertEqual(context['position_exit_status']['rows'][0]['symbol'], 'BTCUSDT')
        self.assertEqual(context['position_exit_status']['rows'][0]['status_label'], 'Diagnostics unavailable')

    def test_exit_status_page_returns_200_when_diagnostics_query_fails(self):
        self.client.force_login(self.user)
        with patch('dashboard.dashboard_read_model.Portfolio.objects') as portfolio_manager:
            portfolio_manager.all.return_value.order_by.return_value = [
                SimpleNamespace(symbol='BTCUSDT', asset='BTC', quantity=Decimal('1'), current_price=Decimal('10'))
            ]
            with patch(
                'dashboard.dashboard_read_model._open_lots_by_symbol',
                return_value={'BTCUSDT': {'open_quantity': Decimal('1'), 'open_lot_count': 1}},
            ):
                with patch(
                    'dashboard.dashboard_read_model._latest_sell_events_for_exit_status',
                    side_effect=DatabaseError('diagnostics unavailable'),
                ):
                    response = self.client.get(reverse('dashboard_exit_status'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'BTCUSDT')
        self.assertContains(response, 'Diagnostics unavailable')

    def test_recent_operations_provide_latest_trade_without_second_query(self):
        latest = SimpleNamespace(gross_quote=Decimal('10'), net_quote=Decimal('9'))

        latest_trade = _build_latest_trade_from_recent_operations([latest])

        self.assertEqual(latest_trade['row'], latest)
        self.assertEqual(latest_trade['gross_quote'], Decimal('10'))
        self.assertEqual(latest_trade['net_quote'], Decimal('9'))

    def test_dust_homepage_summary_can_skip_count_query(self):
        class CountShouldNotRun:
            def count(self):
                raise AssertionError('homepage dust summary must not call count()')

        latest = SimpleNamespace(run_id='latest-run', detected_at=timezone.now())
        summary = _build_homepage_summary(
            CountShouldNotRun(),
            [{'severity': 'warning', 'latest_estimated_value_usdt': Decimal('2')}],
            latest=latest,
        )

        self.assertIsNone(summary['total_detections'])
        self.assertEqual(summary['warning_count'], 1)

    def test_dashboard_context_keeps_rendering_when_sell_diagnostics_query_fails(self):
        class FailingSellDecisionEventQuery:
            def filter(self, **kwargs):
                raise DatabaseError('missing diagnostics table')

        with patch('dashboard.dashboard_read_model.logger'):
            with patch('dashboard.dashboard_read_model.Portfolio.objects') as portfolio_manager:
                portfolio_manager.all.return_value.order_by.return_value = []
                with patch('dashboard.dashboard_read_model._build_bot_status', return_value={}):
                    with patch('dashboard.dashboard_read_model._build_fee_summary', return_value={}):
                        with patch('dashboard.dashboard_read_model._build_quote_fee_summary', return_value={}):
                            with patch('dashboard.dashboard_read_model._build_performance_kpis', return_value={}):
                                with patch('dashboard.dashboard_read_model._build_recent_operations', return_value=[]):
                                    with patch('dashboard.dashboard_read_model._build_latest_trade_from_recent_operations', return_value=None):
                                        with patch(
                                            'dashboard.dashboard_read_model._open_lots_by_symbol',
                                            return_value={'ZECUSDT': {'open_quantity': Decimal('1')}},
                                        ):
                                            with patch(
                                                'dashboard.dashboard_read_model.SellDecisionEvent.objects',
                                                FailingSellDecisionEventQuery(),
                                            ):
                                                with patch(
                                                    'dashboard.dashboard_read_model.get_dust_overview_context',
                                                    return_value={'data_error': None},
                                                ):
                                                    read_model = get_dashboard_context()

        self.assertEqual(read_model.context['position_exit_status']['rows'][0]['symbol'], 'ZECUSDT')

    def test_dashboard_context_keeps_rendering_when_dust_summary_fails(self):
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
                                            side_effect=DatabaseError('dust unavailable'),
                                        ):
                                            read_model = get_dashboard_context()

        self.assertIn('dust detections: dust unavailable', read_model.context['data_error'])

    @patch('dashboard.views.get_dashboard_context')
    def test_homepage_requests_compact_performance_context(self, mock_get_dashboard_context):
        mock_get_dashboard_context.return_value.context = self.empty_dashboard_context()
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        mock_get_dashboard_context.assert_called_once_with(include_performance_kpis=False)

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_explains_position_exit_scope_and_excluded_balances(self, mock_get_dashboard_context):
        context = self.empty_dashboard_context()
        context['inventory_scope'] = {
            'spot_assets_count': None,
            'bot_managed_lot_symbols_count': 1,
            'material_tradable_positions_count': 1,
            'dust_non_tradable_positions_count': 0,
            'excluded_balances_count': 1,
            'excluded_balances': [
                {
                    'symbol': 'USDCUSDT',
                    'asset': 'USDC',
                    'reason': 'stablecoin cash balance',
                },
            ],
        }
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertContains(response, 'Open FIFO lot exit status')
        self.assertContains(response, 'Only symbols with open FIFO lots appear here.')
        self.assertContains(response, 'Stablecoin cash balances are intentionally excluded.')
        self.assertContains(response, 'Pure SPOT balances without open lots are not SELL candidates.')
        self.assertContains(response, 'Excluded balances')
        self.assertContains(response, 'USDCUSDT')

    @patch('dashboard.views.get_dashboard_analytics_context')
    def test_analytics_requests_full_performance_context(self, mock_get_dashboard_context):
        mock_get_dashboard_context.return_value.context = self.empty_dashboard_context()
        self.client.force_login(self.user)

        response = self.client.get(reverse('dashboard_analytics'))

        self.assertEqual(response.status_code, 200)
        mock_get_dashboard_context.assert_called_once_with()

    def test_homepage_context_skips_kpi_builder(self):
        with patch('dashboard.dashboard_read_model.Portfolio.objects') as portfolio_manager:
            portfolio_manager.all.return_value.order_by.return_value = []
            with patch('dashboard.dashboard_read_model._build_bot_status', return_value={}):
                with patch('dashboard.dashboard_read_model._build_fee_summary', return_value={}):
                    with patch('dashboard.dashboard_read_model._build_quote_fee_summary', return_value={}):
                        with patch('dashboard.dashboard_read_model._build_performance_kpis') as kpis:
                            with patch('dashboard.dashboard_read_model._build_recent_operations', return_value=[]):
                                with patch('dashboard.dashboard_read_model._build_latest_trade_from_recent_operations', return_value=None):
                                    with patch('dashboard.dashboard_read_model._open_lots_by_symbol', return_value={}):
                                        with patch(
                                            'dashboard.dashboard_read_model.get_dust_overview_context',
                                            return_value={'data_error': None},
                                        ):
                                            get_dashboard_context(include_performance_kpis=False)

        kpis.assert_not_called()

    def test_buy_status_summary_exposes_cooldown_reason_and_details(self):
        summary = _build_buy_status_summary({
            'latest_buy_state': 'rejected',
            'latest_buy_reason': 'take_profit_reentry_cooldown_active',
            'latest_buy_symbol': 'ETHUSDT',
            'material_positions_count': 2,
            'unknown_value_positions_count': 1,
            'dust_positions_count': 3,
            'max_positions': 5,
            'free_usdt': '11.5',
            'latest_sell_operation_id': 91,
            'cooldown_remaining_minutes': 14,
        })

        self.assertEqual(summary['latest_buy_human_reason'], 'Re-entry blocked after take-profit cooldown')
        self.assertEqual(summary['effective_positions_count'], Decimal('3'))
        self.assertEqual(summary['remaining_buy_capacity'], Decimal('2'))
        self.assertEqual(summary['latest_sell_operation_id'], 91)

    def test_churn_summary_handles_no_data_safely(self):
        summary = _build_churn_summary([], {})

        self.assertEqual(summary['reentries_under_15m_24h'], 0)
        self.assertEqual(summary['reentries_under_15m_48h'], 0)
        self.assertEqual(summary['economically_questionable_count'], 0)
        self.assertEqual(summary['rows'], [])

    def test_operational_kpis_group_unversioned_and_exclude_manual_corrections(self):
        now = timezone.datetime(2026, 5, 17, 12, tzinfo=timezone.utc)
        result = _calculate_operational_kpis(
            closure_rows=[
                {'trade_operation_id': 1, 'lot_id': 'lot-1', 'realized_pnl': Decimal('10')},
                {'trade_operation_id': 2, 'lot_id': 'lot-2', 'realized_pnl': Decimal('-2')},
                {'trade_operation_id': 3, 'lot_id': 'lot-3', 'realized_pnl': Decimal('99')},
            ],
            sell_operations={
                1: {'id': 1, 'symbol': 'BTCUSDT', 'timestamp': now, 'strategy_version': 'v2', 'fee_amount_in_quote': Decimal('0.5'), 'manual_correction': False},
                2: {'id': 2, 'symbol': 'ETHUSDT', 'timestamp': now, 'strategy_version': 'unversioned', 'fee_amount_in_quote': Decimal('0.25'), 'manual_correction': False},
                3: {'id': 3, 'symbol': 'SOLUSDT', 'timestamp': now, 'strategy_version': 'v2', 'fee_amount_in_quote': Decimal('0.1'), 'manual_correction': True},
            },
            opened_lots={
                'lot-1': now - timezone.timedelta(hours=2),
                'lot-2': now - timezone.timedelta(minutes=30),
                'lot-3': now - timezone.timedelta(minutes=10),
            },
            operations=[],
            churn_threshold_minutes=60,
        )

        versions = {row['strategy_version']: row for row in result['strategy_summary']}
        self.assertEqual(set(versions), {'unversioned', 'v2'})
        self.assertEqual(versions['v2']['closed_trades_count'], 1)
        self.assertEqual(versions['v2']['net_realized_pnl'], Decimal('9.5'))
        self.assertEqual(versions['v2']['eligible_filled_sell_count'], 0)
        self.assertIsNone(versions['v2']['churn_frequency'])
        self.assertEqual(versions['unversioned']['closed_trades_count'], 1)
        self.assertEqual(result['fee_efficiency']['total_normalized_fees'], Decimal('0.75'))

    def test_operational_kpis_strategy_churn_uses_eligible_sell_denominator(self):
        now = timezone.datetime(2026, 5, 17, 12, tzinfo=timezone.utc)
        result = _calculate_operational_kpis(
            closure_rows=[
                {'trade_operation_id': 1, 'lot_id': 'lot-1', 'realized_pnl': Decimal('3')},
            ],
            sell_operations={
                1: {'id': 1, 'symbol': 'BTCUSDT', 'timestamp': now - timezone.timedelta(hours=3), 'strategy_version': 'v2', 'fee_amount_in_quote': Decimal('0.2'), 'manual_correction': False},
            },
            opened_lots={'lot-1': now - timezone.timedelta(hours=4)},
            operations=[
                {'id': 1, 'symbol': 'BTCUSDT', 'side': 'SELL', 'timestamp': now - timezone.timedelta(hours=3), 'strategy_version': 'v2', 'manual_correction': False},
                {'id': 2, 'symbol': 'BTCUSDT', 'side': 'BUY', 'timestamp': now - timezone.timedelta(hours=2, minutes=30), 'strategy_version': 'v2', 'manual_correction': False},
                {'id': 3, 'symbol': 'ETHUSDT', 'side': 'SELL', 'timestamp': now - timezone.timedelta(hours=2), 'strategy_version': 'v2', 'manual_correction': False},
            ],
            churn_threshold_minutes=60,
        )

        strategy_row = result['strategy_summary'][0]
        churn_row = result['churn']['by_strategy_version'][0]
        self.assertEqual(strategy_row['closed_trades_count'], 1)
        self.assertEqual(strategy_row['eligible_filled_sell_count'], 2)
        self.assertEqual(strategy_row['churn_frequency'], Decimal('50'))
        self.assertEqual(strategy_row['churn_frequency'], churn_row['same_symbol_reentry_frequency'])

    def test_operational_kpis_calculate_hold_buckets_churn_and_safe_fee_ratios(self):
        now = timezone.datetime(2026, 5, 17, 12, tzinfo=timezone.utc)
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
