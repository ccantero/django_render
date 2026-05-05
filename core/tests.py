from django.test import TestCase, TransactionTestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from django.db import DatabaseError, connection
from decimal import Decimal
from types import SimpleNamespace
import json
from pathlib import Path
from unittest.mock import patch

from dashboard.dashboard_read_model import (
    _build_bot_status,
    _build_fee_summary,
    _build_quote_fee_summary,
)
from dashboard.dust_read_model import (
    _build_summary,
    _clean_filters,
    _dashboard_queryset,
    _filtered_group_detections,
    _format_payload,
    _operator_guidance,
    _filter_by_review_status,
    _reviews_for_rows,
    get_dust_dashboard_context,
    update_dust_signal_review,
)
from dashboard.forms import ManualCorrectionRequestForm
from core.models import DustSignalReview, ManualCorrection
from core.trading_models import DustDetection
from dashboard.views import _manual_correction_quantity

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

    def test_dashboard_route_is_owned_by_dashboard_app(self):
        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.resolver_match.func.__module__, "dashboard.views")

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_authenticated_user_gets_dashboard(self, mock_get_dashboard_context):
        mock_get_dashboard_context.return_value.context = self.empty_dashboard_context()
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Trading Dashboard')
        mock_get_dashboard_context.assert_called_once()

    @patch('dashboard.views.get_dashboard_context')
    def test_dashboard_loads_when_bot_tables_are_empty(self, mock_get_dashboard_context):
        mock_get_dashboard_context.return_value.context = self.empty_dashboard_context()
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No data yet.')
        self.assertContains(response, 'Portfolio Summary')

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
        self.assertContains(response, 'Fees (USDT)')
        self.assertContains(response, '0.25000000')
        self.assertContains(response, '0.25 USDT')
        self.assertContains(response, 'Dust / Residuals')
        self.assertContains(response, 'Latest grouped values, not PnL')

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
            'total_estimated_value_usdt': Decimal('4.20'),
            'data_error': None,
        }
        mock_get_dashboard_context.return_value.context = context
        self.client.force_login(self.user)

        response = self.client.get(self.dashboard_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dust / Residuals')
        self.assertContains(response, 'Critical detections')
        self.assertContains(response, 'Warning detections')
        self.assertContains(response, 'Info detections')
        self.assertContains(response, 'run-dust-001')
        self.assertContains(response, 'SOLUSDT')
        self.assertContains(response, 'below_min_notional')
        self.assertContains(response, 'monitor')
        self.assertContains(response, reverse('dust_dashboard'))

    def test_demo_dashboard_is_public_and_read_only(self):
        response = self.client.get(reverse('dashboard_demo'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public demo')
        self.assertContains(response, 'Total Fees')
        self.assertContains(response, 'Fees (USDT)')
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
        mock_get_dust_context.assert_called_once()

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
                'latest_detected_at': timezone.now(),
                'latest_run_id': 'run-detail-001',
                'latest_estimated_value_usdt': Decimal('0.415022396'),
                'latest_estimated_delta_value_usdt': Decimal('0'),
                'latest_suggested_action': 'review_recent_sell',
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

    def test_pending_review_filter_keeps_only_pending_rows(self):
        rows = [
            {'symbol': 'BTCUSDT', 'review_status': DustSignalReview.STATUS_PENDING},
            {'symbol': 'ETHUSDT', 'review_status': DustSignalReview.STATUS_IGNORED},
        ]

        filtered = _filter_by_review_status(rows, DustSignalReview.STATUS_PENDING)

        self.assertEqual(filtered, [{'symbol': 'BTCUSDT', 'review_status': DustSignalReview.STATUS_PENDING}])

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
            'quote_fee_summary': {
                'total_fees_usdt': Decimal('0'),
                'total_operations': 0,
                'by_side': {
                    'BUY': {'total_fee_usdt': Decimal('0'), 'operations_count': 0},
                    'SELL': {'total_fee_usdt': Decimal('0'), 'operations_count': 0},
                },
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
