import pickle
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import BotControl
from core.trading_models import BotHealthcheck, TradeOperation
from dashboard.dashboard_read_model import ANALYTICS_CACHE_KEY, _cache_safe_value


ANALYTICS_TEMPLATE = Path("dashboard/templates/dashboard/analytics.html")

# Attribute paths analytics.html actually resolves from the cached context.
# These are dict and scalar fields. The template does not call model methods,
# properties, or relations.
CONSUMED_TEMPLATE_PATHS = (
    "data_error",
    "quote_fee_summary.total_fees_usdt",
    "quote_fee_summary.by_side.BUY.total_fee_usdt",
    "quote_fee_summary.by_side.SELL.total_fee_usdt",
    "quote_fee_summary.total_operations",
    "fee_summary.rows",
    "fee_summary.asset_count",
    "fee_summary.fill_count",
    "fee.total",
    "fee.asset",
    "fee.fill_count",
    "performance_kpis.net_realized_pnl",
    "performance_kpis.total_fees_usdt",
    "performance_kpis.win_rate",
    "performance_kpis.breakeven_closures_count",
    "performance_kpis.average_win",
    "performance_kpis.winning_closures_count",
    "performance_kpis.average_loss",
    "performance_kpis.profit_factor",
    "performance_kpis.gross_deployed_capital",
    "performance_kpis.manual_adjustment_pnl",
    "performance_kpis.manual_corrections_split_available",
    "performance_kpis.fee_limitations_note",
    "performance_kpis.manual_corrections_note",
    "performance_kpis.pnl_by_symbol",
    "row.symbol",
    "row.realized_pnl",
    "row.closures_count",
    "performance_kpis.pnl_by_day",
    "row.date",
)

# Cached model objects the analytics view stores but the template does not read.
UNCONSUMED_MODEL_REFERENCES = (
    "bot_control",
    "bot_status",
    "recent_operations",
    "latest_trade",
    ".save",
    ".delete",
    "updated_by",
)


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

    def test_analytics_cache_key_is_v2(self):
        self.assertEqual(ANALYTICS_CACHE_KEY, "dashboard:analytics_context:v2")

    def test_cold_and_warm_analytics_renders_match(self):
        context = _analytics_context_with_bot_rows()
        template = ANALYTICS_TEMPLATE.read_text()
        for path in CONSUMED_TEMPLATE_PATHS:
            self.assertIn(path, template, path)
        for reference in UNCONSUMED_MODEL_REFERENCES:
            self.assertNotIn(reference, template, reference)

        with patch("dashboard.dashboard_read_model.get_dashboard_context") as builder:
            builder.return_value = SimpleNamespace(context=context)
            cold = self.client.get(reverse("dashboard_analytics"))
            warm = self.client.get(reverse("dashboard_analytics"))

        self.assertEqual(cold.status_code, 200)
        self.assertEqual(warm.status_code, 200)
        self.assertEqual(_analytics_markup(cold), _analytics_markup(warm))
        for snippet in _expected_analytics_snippets():
            self.assertContains(warm, snippet)
        builder.assert_called_once_with(include_performance_kpis=True)
        cached = cache.get(ANALYTICS_CACHE_KEY)
        self.assertNotIsInstance(cached["bot_status"]["row"], BotHealthcheck)
        self.assertEqual(cached["bot_status"]["row"].status, "ok")
        self.assertEqual(cached["bot_status"]["row"].probe_message, "heartbeat")
        self.assertFalse(hasattr(cached["bot_status"]["row"], "save"))
        self.assertFalse(hasattr(cached["latest_trade"]["row"], "delete"))
        self.assertFalse(hasattr(cached["bot_control"], "updated_by"))

    def test_second_analytics_request_does_not_500_when_context_has_bot_rows(self):
        context = _analytics_context_with_bot_rows()
        with patch("dashboard.dashboard_read_model.get_dashboard_context") as builder:
            builder.return_value = SimpleNamespace(context=context)
            first = self.client.get(reverse("dashboard_analytics"))
            second = self.client.get(reverse("dashboard_analytics"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(_analytics_markup(first), _analytics_markup(second))
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
        self.assertContains(response, "shared read failed")
        builder.assert_called_once_with(include_performance_kpis=True)

    def test_cache_get_failure_renders_page_and_logs_reason(self):
        context = _analytics_context_with_bot_rows()
        with patch("dashboard.dashboard_read_model.cache.get", side_effect=pickle.UnpicklingError("bad analytics payload")):
            with patch("dashboard.dashboard_read_model.get_dashboard_context") as builder:
                builder.return_value = SimpleNamespace(context=context)
                with self.assertLogs("dashboard.dashboard_read_model", level="WARNING") as logs:
                    response = self.client.get(reverse("dashboard_analytics"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "shared read failed")
        self.assertContains(response, "BTCUSDT")
        self.assertContains(response, "2026-05-01")
        builder.assert_called_once_with(include_performance_kpis=True)
        output = "\n".join(logs.output)
        self.assertIn("analytics_cache_unreadable", output)
        self.assertIn("UnpicklingError", output)
        self.assertIn("bad analytics payload", output)
        self.assertIn(ANALYTICS_CACHE_KEY, output)

    def test_cache_set_failure_renders_page_and_logs_reason(self):
        context = _analytics_context_with_bot_rows()
        with patch("dashboard.dashboard_read_model.cache.set", side_effect=OSError("cache backend unavailable")):
            with patch("dashboard.dashboard_read_model.get_dashboard_context") as builder:
                builder.return_value = SimpleNamespace(context=context)
                with self.assertLogs("dashboard.dashboard_read_model", level="WARNING") as logs:
                    response = self.client.get(reverse("dashboard_analytics"))

        self.assertEqual(response.status_code, 200)
        for snippet in _expected_analytics_snippets():
            self.assertContains(response, snippet)
        builder.assert_called_once_with(include_performance_kpis=True)
        output = "\n".join(logs.output)
        self.assertIn("analytics_cache_store_failed", output)
        self.assertIn("OSError", output)
        self.assertIn("cache backend unavailable", output)
        self.assertIsNone(cache.get(ANALYTICS_CACHE_KEY))

    def test_non_cache_exception_from_cache_get_propagates(self):
        with patch(
            "dashboard.dashboard_read_model.cache.get",
            side_effect=RuntimeError("not a cache backend failure"),
        ):
            with self.assertRaisesMessage(RuntimeError, "not a cache backend failure"):
                self.client.get(reverse("dashboard_analytics"))

    def test_context_builder_errors_are_not_swallowed(self):
        with patch(
            "dashboard.dashboard_read_model.get_dashboard_context",
            side_effect=RuntimeError("kpi query bug"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.get(reverse("dashboard_analytics"))

    def test_snapshot_copies_concrete_fields_not_model_methods(self):
        created_at = timezone.now()
        operation = TradeOperation(
            symbol="BTCUSDT",
            side="BUY",
            status="FILLED",
            gross_quote=Decimal("10"),
            net_quote=Decimal("9.50"),
        )
        health = BotHealthcheck(
            status="ok",
            probe_message="heartbeat",
            created_at=created_at,
            details={"read_only": False},
        )
        control = BotControl(is_paused=True, reason="maintenance")
        safe = _cache_safe_value({
            "bot_status": {"row": health},
            "recent_operations": [operation],
            "latest_trade": {"row": operation, "gross_quote": operation.gross_quote},
            "bot_control": control,
        })

        self.assertEqual(safe["bot_status"]["row"].status, "ok")
        self.assertEqual(safe["bot_status"]["row"].probe_message, "heartbeat")
        self.assertEqual(safe["bot_status"]["row"].created_at, created_at)
        self.assertEqual(safe["bot_status"]["row"].details, {"read_only": False})
        self.assertEqual(safe["recent_operations"][0].symbol, "BTCUSDT")
        self.assertEqual(safe["recent_operations"][0].side, "BUY")
        self.assertEqual(safe["recent_operations"][0].status, "FILLED")
        self.assertEqual(safe["latest_trade"]["row"].gross_quote, Decimal("10"))
        self.assertEqual(safe["latest_trade"]["gross_quote"], Decimal("10"))
        self.assertTrue(safe["bot_control"].is_paused)
        self.assertEqual(safe["bot_control"].reason, "maintenance")
        self.assertFalse(hasattr(safe["bot_status"]["row"], "save"))
        self.assertFalse(hasattr(safe["recent_operations"][0], "delete"))
        self.assertFalse(hasattr(safe["bot_control"], "updated_by"))
        self.assertNotIsInstance(safe["bot_control"], BotControl)
        self.assertNotIsInstance(safe["recent_operations"][0], TradeOperation)


def _analytics_markup(response):
    html = response.content.decode()
    start = html.index('<div class="container-fluid py-4 dashboard-page">')
    end = html.index("<script", start)
    return html[start:end]


def _expected_analytics_snippets():
    return (
        "shared read failed",
        "3.50 USDT",
        "2.10 USDT",
        "1.40 USDT",
        "Fills: 7",
        "Assets: <strong>2</strong>",
        "Fills: 9",
        "0.00180000",
        "BNB",
        "1.25000000",
        "USDT",
        "12.34 USDT",
        "0.75 USDT",
        "66.67%",
        "breakeven: 1",
        "7.50 USDT",
        "Winning closures: 2",
        "-3.00 USDT",
        "5.00",
        "125.25 USDT",
        "-2.00 USDT",
        "Split from identifiable correction metadata",
        "fee note for normalized USDT",
        "manual note for identifiable corrections",
        "BTCUSDT",
        "7.00 USDT",
        "ETHUSDT",
        "-1.50 USDT",
        "-",
        "2026-05-01",
        "2026-05-02",
    )


def _analytics_context_with_bot_rows():
    operation = TradeOperation(
        symbol="BTCUSDT",
        side="BUY",
        status="FILLED",
        gross_quote=Decimal("10"),
        net_quote=Decimal("9.50"),
        executed_at=timezone.now(),
    )
    return {
        "data_error": "portfolio: shared read failed",
        "quote_fee_summary": {
            "total_fees_usdt": Decimal("3.50"),
            "total_operations": 7,
            "by_side": {
                "BUY": {"total_fee_usdt": Decimal("2.10"), "operations_count": 4},
                "SELL": {"total_fee_usdt": Decimal("1.40"), "operations_count": 3},
            },
        },
        "fee_summary": {
            "asset_count": 2,
            "fill_count": 9,
            "rows": [
                {"asset": "BNB", "total": Decimal("0.0018"), "fill_count": 2},
                {"asset": "USDT", "total": Decimal("1.25"), "fill_count": 7},
            ],
        },
        "performance_kpis": {
            "net_realized_pnl": Decimal("12.34"),
            "total_fees_usdt": Decimal("0.75"),
            "win_rate": Decimal("66.66666666666666666666666667"),
            "breakeven_closures_count": 1,
            "average_win": Decimal("7.50"),
            "winning_closures_count": 2,
            "average_loss": Decimal("-3.00"),
            "profit_factor": Decimal("5"),
            "gross_deployed_capital": Decimal("125.25"),
            "manual_adjustment_pnl": Decimal("-2.00"),
            "manual_corrections_split_available": True,
            "fee_limitations_note": "fee note for normalized USDT",
            "manual_corrections_note": "manual note for identifiable corrections",
            "pnl_by_symbol": [
                {"symbol": "BTCUSDT", "realized_pnl": Decimal("7.00"), "closures_count": 2},
                {"symbol": "ETHUSDT", "realized_pnl": Decimal("-1.50"), "closures_count": 1},
                {"symbol": "", "realized_pnl": Decimal("0"), "closures_count": 0},
            ],
            "pnl_by_day": [
                {"date": date(2026, 5, 1), "realized_pnl": Decimal("7.00"), "closures_count": 2},
                {"date": date(2026, 5, 2), "realized_pnl": Decimal("-1.50"), "closures_count": 1},
            ],
        },
        "bot_control": BotControl(is_paused=True, reason="maintenance"),
        "bot_status": {
            "row": BotHealthcheck(
                status="ok",
                probe_message="heartbeat",
                created_at=timezone.now(),
                details={"read_only": False},
            ),
        },
        "recent_operations": [operation],
        "latest_trade": {
            "row": operation,
            "gross_quote": operation.gross_quote,
            "net_quote": operation.net_quote,
        },
    }
