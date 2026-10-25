from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from unittest.mock import patch

from core.trading_models import BotHealthcheck, TradeOperation
from dashboard.dashboard_read_model import ANALYTICS_CACHE_KEY


class AnalyticsCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            email="analytics@example.com",
            password="TestPassword123",
            name="Analytics User",
        )
        self.client.force_login(self.user)

    def tearDown(self):
        cache.clear()

    def test_second_analytics_request_does_not_500_when_context_has_bot_rows(self):
        context = _analytics_context_with_bot_rows()
        with patch("dashboard.dashboard_read_model.get_dashboard_context") as builder:
            builder.return_value = SimpleNamespace(context=context)
            first = self.client.get(reverse("dashboard_analytics"))
            second = self.client.get(reverse("dashboard_analytics"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "12.34")
        builder.assert_called_once_with(include_performance_kpis=True)

    def test_unreadable_analytics_cache_entry_rebuilds_instead_of_500(self):
        cache.set(
            ANALYTICS_CACHE_KEY,
            {"bot_status": {"row": BotHealthcheck(status="ok", created_at=timezone.now())}},
            60,
        )
        context = _analytics_context_with_bot_rows()
        with patch("dashboard.dashboard_read_model.get_dashboard_context") as builder:
            builder.return_value = SimpleNamespace(context=context)
            response = self.client.get(reverse("dashboard_analytics"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "12.34")
        builder.assert_called_once_with(include_performance_kpis=True)


def _analytics_context_with_bot_rows():
    operation = TradeOperation(symbol="BTCUSDT", side="BUY", status="FILLED")
    return {
        "data_error": None,
        "quote_fee_summary": {
            "total_fees_usdt": Decimal("1.00"),
            "total_operations": 1,
            "by_side": {
                "BUY": {"total_fee_usdt": Decimal("1.00"), "operations_count": 1},
                "SELL": {"total_fee_usdt": Decimal("0"), "operations_count": 0},
            },
        },
        "fee_summary": {"asset_count": 0, "fill_count": 0, "rows": []},
        "performance_kpis": {
            "net_realized_pnl": Decimal("12.34"),
            "total_fees_usdt": Decimal("1.00"),
            "win_rate": None,
            "breakeven_closures_count": 0,
            "average_win": None,
            "winning_closures_count": 0,
            "average_loss": None,
            "profit_factor": None,
            "gross_deployed_capital": Decimal("10"),
            "manual_adjustment_pnl": Decimal("0"),
            "manual_corrections_split_available": False,
            "fee_limitations_note": "fee note",
            "manual_corrections_note": "manual note",
            "pnl_by_symbol": [],
            "pnl_by_day": [],
        },
        "bot_status": {
            "row": BotHealthcheck(status="ok", created_at=timezone.now(), details={}),
        },
        "recent_operations": [operation],
        "latest_trade": {
            "row": operation,
            "gross_quote": Decimal("10"),
            "net_quote": Decimal("10"),
        },
    }
