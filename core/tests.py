from django.test import TestCase, TransactionTestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from django.db import DatabaseError, connection
from decimal import Decimal
from types import SimpleNamespace
import inspect
import json
import os
from pathlib import Path
from unittest.mock import patch

from dashboard.dashboard_read_model import (
    _build_bot_status,
    _build_fee_summary,
    _build_performance_kpis,
    _build_position_exit_status,
    _build_quote_fee_summary,
    _build_valuation_consistency,
    _calculate_performance_kpis,
    _position_exit_suggested_action,
)
from dashboard.dust_read_model import (
    _active_operational_issues,
    _build_summary,
    _clean_filters,
    _dashboard_queryset,
    _filtered_group_detections,
    _format_payload,
    _operator_guidance,
    _filter_by_review_status,
    _informational_residual_summary,
    _with_correction_state,
    _reviews_for_rows,
    get_dust_dashboard_context,
    update_dust_signal_review,
)
from dashboard.forms import ManualCorrectionRequestForm
from core.models import DustSignalReview, ManualCorrection
from core.trading_models import DustDetection, TradeOperation
from dashboard.views import _manual_correction_quantity


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
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_returns_capacity_with_runtime_max_positions_fallback(
        self,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
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
        self.assertIn('Raw/material/dust/unknown: <code>17/5/12/0</code>', message)
        self.assertIn('Effective positions: <code>5/10</code>', message)
        self.assertIn('Remaining capacity: <code>5</code>', message)
        self.assertIn('Max positions: <code>10</code>', message)
        self.assertIn('Material: <code>BTCUSDT</code>', message)
        self.assertIn('Dust: <code>SAGAUSDT, ETHUSDT</code>', message)
        self.assertIn('Dust positions: <code>non-blocking</code>', message)
        self.assertIn('Unknown: <code>none</code>', message)
        self.assertIn('Free USDT: <code>123.45 USDT</code>', message)
        self.assertIn('Latest BUY reason: <code>capacity available</code>', message)
        self.assertIn('BUY state: <code>available</code>', message)
        self.assertIn('Reason: <code>capacity available</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.TradeOperation.objects')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_keeps_capacity_when_optional_fields_are_missing(
        self,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
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
        self.assertIn('Effective positions: <code>5/10</code>', message)
        self.assertIn('Remaining capacity: <code>5</code>', message)
        self.assertIn('Free USDT: <code>diagnostic unavailable</code>', message)
        self.assertIn('Latest BUY reason: <code>unavailable</code>', message)
        self.assertIn('BUY state: <code>available</code>', message)
        self.assertIn('Reason: <code>capacity available</code>', message)

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
        self.assertIn('BUY state: <code>diagnostic_unavailable</code>', message)
        self.assertIn('Reason: <code>latest healthcheck missing</code>', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_displays_blocked_when_effective_positions_reach_max(self, mock_health_manager, mock_send_message):
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
        self.assertIn('BUY state: <code>blocked_by_positions</code>', message)
        self.assertIn('effective positions at max capacity', message)

    @patch('core.views.TELEGRAM_WEBHOOK_TOKEN', 'test-webhook-token')
    @patch('core.views.send_message')
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_treats_dust_as_non_blocking_when_raw_positions_exceed_max(self, mock_health_manager, mock_send_message):
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
        self.assertIn('BUY state: <code>available</code>', message)
        self.assertIn('Dust positions: <code>non-blocking</code>', message)

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
        self.assertIn('<b>Summary</b>', message)
        self.assertIn('• Profit guard blocked', message)
        self.assertNotIn('<pre>', message)
        self.assertIn('Profit guard blocked', message)
        self.assertIn('Exchange minNotional blocked', message)

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
    @patch('core.telegram_diagnostics.BotHealthcheck.objects')
    def test_buy_status_command_does_not_write_bot_owned_tables(
        self,
        mock_health_manager,
        mock_trade_manager,
        mock_send_message,
    ):
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
        self.assertContains(response, 'Performance Snapshot')
        self.assertContains(response, 'Analytics')
        self.assertContains(response, 'Portfolio vs lots drift')
        self.assertContains(response, '0.75 USDT')
        self.assertContains(response, '0.00100000')
        self.assertContains(response, '0.25')
        self.assertContains(response, 'Dust / Residuals')
        self.assertContains(response, 'Active issues first')
        self.assertContains(response, 'Net realized PnL')
        self.assertContains(response, '12.25')
        self.assertContains(response, 'Win rate')
        self.assertNotContains(response, 'Average win')
        self.assertNotContains(response, 'Average loss')
        self.assertContains(response, 'Profit factor')
        self.assertContains(response, '6.00')
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
        self.assertContains(response, 'Performance Snapshot')
        self.assertContains(response, 'Net realized PnL')
        self.assertContains(response, 'Analytics')
        self.assertContains(response, 'Dust Dashboard')
        self.assertNotContains(response, 'PnL by symbol')
        self.assertNotContains(response, 'PnL by day')
        self.assertContains(response, 'Profit factor')
        self.assertContains(response, 'N/A')
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
        self.assertContains(response, 'Why positions are not selling')
        self.assertContains(response, 'ZECUSDT')
        self.assertContains(response, 'Holding')
        self.assertContains(response, 'stop_loss not reached, take_profit not reached')
        self.assertContains(response, 'Hold: strategy thresholds not reached')
        self.assertContains(response, 'ORDIUSDT')
        self.assertContains(response, 'Review drift: Binance balance lower than lots')

    def test_demo_dashboard_is_public_and_read_only(self):
        response = self.client.get(reverse('dashboard_demo'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public demo')
        self.assertContains(response, 'Performance Snapshot')
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
        self.assertEqual(below_min['operator_action'], 'Monitor / optionally ignore')
        self.assertEqual(lots_greater['operator_label'], 'Lots > Binance')
        self.assertEqual(lots_greater['operator_priority'], 'accounting drift, needs review')
        self.assertEqual(binance_greater['operator_label'], 'Binance > Lots')
        self.assertEqual(binance_greater['operator_action'], 'Investigate manual buy/deposit/Earn return')
        self.assertEqual(incomplete_sell['operator_label'], 'Possible incomplete sell')
        self.assertIn('Inspect Binance history', incomplete_sell['operator_action'])

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
        self.assertEqual(rows_by_symbol['ZECUSDT']['suggested_action'], 'Hold: strategy thresholds not reached')
        self.assertEqual(rows_by_symbol['ETHUSDT']['status_label'], 'Dust residual')
        self.assertEqual(rows_by_symbol['ETHUSDT']['estimated_value_usdt'], Decimal('2.300'))
        self.assertEqual(rows_by_symbol['ETHUSDT']['suggested_action'], 'Dust: review/ignore or wait until reusable')
        self.assertEqual(rows_by_symbol['ORDIUSDT']['status_label'], 'Review needed')
        self.assertEqual(rows_by_symbol['ORDIUSDT']['suggested_action'], 'Review drift: Binance balance lower than lots')
        self.assertEqual(summary['material_count'], 2)
        self.assertEqual(summary['dust_count'], 1)

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
                'data_error': None,
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
