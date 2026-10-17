from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient


API_TOKEN = "test-only-diagnostics-token-with-32-chars"


@override_settings(BOT_DIAGNOSTICS_API_TOKEN=API_TOKEN)
class BotDiagnosticsAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.auth = {"HTTP_AUTHORIZATION": f"Bearer {API_TOKEN}"}

    def test_health_rejects_anonymous_request_without_reading_database(self):
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health:
            response = self.client.get("/api/bot/health")

        self.assertEqual(response.status_code, 401)
        health.order_by.assert_not_called()

    def test_inventory_rejects_anonymous_request_without_reading_bot_tables(self):
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
             patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust, \
             patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio, \
             patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lots:
            response = self.client.get("/api/bot/inventory/ETHUSDT")

        self.assertEqual(response.status_code, 401)
        health.order_by.assert_not_called()
        dust.filter.assert_not_called()
        portfolio.filter.assert_not_called()
        lots.filter.assert_not_called()

    def test_diagnostics_bearer_authentication_is_scoped_to_diagnostics_routes(self):
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)

    def test_invalid_or_unconfigured_bearer_secret_is_rejected(self):
        for authorization in (
            "Bearer wrong-token",
            f"Bearer {'x' * 31}",
            f"Bearer {'x' * 32}",
            "Basic not-a-bearer-token",
            "Bearer one two",
            f"Bearer {'x' * 513}",
            "Bearer",
        ):
            with self.subTest(authorization=authorization[:32]):
                with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health:
                    response = self.client.get(
                        "/api/bot/health", HTTP_AUTHORIZATION=authorization
                    )
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response["Cache-Control"], "no-store")
                health.order_by.assert_not_called()

        with override_settings(BOT_DIAGNOSTICS_API_TOKEN="too-short"):
            response = self.client.get("/api/bot/health", **self.auth)
        self.assertEqual(response.status_code, 401)

    def test_health_returns_only_safe_persisted_fields(self):
        now = timezone.now()
        row = SimpleNamespace(
            status="ok",
            created_at=now,
            details={"run_id": "not-exposed", "api_key": "not-exposed"},
        )
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health:
            health.order_by.return_value.first.return_value = row
            response = self.client.get("/api/bot/health", **self.auth)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["healthcheck"]["status"], "ok")
        self.assertEqual(payload["healthcheck"]["freshness"], "fresh")
        self.assertNotIn("details", payload["healthcheck"])
        self.assertNotIn("api_key", response.content.decode())
        health.order_by.assert_called_once_with("-created_at", "-id")

    def test_inventory_returns_read_only_bounded_evidence_and_explicit_unavailable_sources(self):
        now = timezone.now()
        health_row = SimpleNamespace(
            status="ok",
            created_at=now,
            details={
                "position_classification": {
                    "material_symbols": ["ETHUSDT"],
                    "positions_count": 15,
                    "material_positions_count": 15,
                    "dust_positions_count": 0,
                    "unknown_value_positions_count": 0,
                    "effective_positions_count": 15,
                },
                "max_positions": 15,
                "remaining_buy_capacity": 0,
            },
        )
        portfolio = SimpleNamespace(
            quantity=Decimal("0.25"),
            entry_price=Decimal("3000"),
            current_price=Decimal("3200"),
            updated_at=now,
        )
        lot_values = {
            "open_quantity": Decimal("0.25"),
            "open_lot_count": 2,
            "first_opened_at": now - timedelta(days=2),
            "last_opened_at": now - timedelta(days=1),
        }
        spot_row = SimpleNamespace(
            spot_quantity=Decimal("0.000093"),
            open_lot_quantity=Decimal("0.25"),
            price_usdt=Decimal("2370"),
            estimated_value_usdt=Decimal("0.22041"),
            event_type="lot_balance_drift_detected",
            reason="balance differs from open FIFO lots",
            source="dust_detection_service",
            detected_at=now - timedelta(minutes=3),
        )
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
             patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
             patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
             patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
            health.order_by.return_value.first.return_value = health_row
            dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = spot_row
            portfolio_manager.filter.return_value.only.return_value.first.return_value = portfolio
            lot_manager.filter.return_value.aggregate.return_value = lot_values

            response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["symbol"], "ETHUSDT")
        self.assertEqual(payload["portfolio"]["quantity"], "0.25")
        self.assertEqual(payload["portfolio"]["estimated_value_usdt"], "800.00")
        self.assertEqual(payload["open_lots"]["quantity"], "0.25")
        self.assertEqual(payload["latest_spot_observation"]["observed_spot_quantity"], "0.000093")
        self.assertEqual(payload["latest_spot_observation"]["quantity_status"], "available")
        self.assertEqual(payload["latest_spot_observation"]["observation_recency"], "recent")
        self.assertEqual(payload["latest_spot_observation"]["detected_at"], spot_row.detected_at.isoformat())
        self.assertFalse(payload["latest_spot_observation"]["current_exchange_truth"])
        self.assertEqual(payload["quantity_difference"]["portfolio_minus_open_lots"], "0.00")
        self.assertEqual(payload["buy_capacity"]["symbol_classification"], "material")
        self.assertEqual(payload["buy_capacity"]["capacity_status"], "current_as_of_healthcheck")
        self.assertEqual(payload["buy_capacity"]["global_status"], "available")
        self.assertEqual(payload["buy_capacity"]["global"]["remaining_buy_capacity"], 0)
        self.assertEqual(payload["buy_capacity"]["global"]["effective_positions_count"], 15)
        self.assertFalse(payload["exchange_spot"]["available"])
        self.assertFalse(payload["active_generation"]["available"])
        self.assertEqual(payload["open_lots"]["freshness"], "unknown")
        self.assertFalse(payload["consistency"]["atomic"])
        self.assertEqual(payload["quantity_difference"]["comparability"], "not_synchronized")
        self.assertNotIn("not-exposed", response.content.decode())

        health.order_by.assert_called_once_with("-created_at", "-id")
        dust_manager.filter.assert_called_once_with(symbol="ETHUSDT", detected_at__isnull=False)
        dust_manager.filter.return_value.only.return_value.order_by.assert_called_once_with(
            "-detected_at", "-id"
        )
        portfolio_manager.filter.assert_called_once_with(symbol="ETHUSDT")
        lot_manager.filter.assert_called_once_with(symbol="ETHUSDT", remaining_quantity__gt=0)
        lot_manager.filter.return_value.aggregate.assert_called_once()
        portfolio_manager.all.assert_not_called()
        lot_manager.all.assert_not_called()
        portfolio_manager.delete.assert_not_called()
        lot_manager.delete.assert_not_called()
        portfolio_manager.create.assert_not_called()
        portfolio_manager.update.assert_not_called()
        lot_manager.create.assert_not_called()
        lot_manager.update.assert_not_called()
        for method_name in ("create", "update", "delete"):
            getattr(dust_manager, method_name).assert_not_called()

    def test_inventory_returns_not_found_when_symbol_has_no_persisted_position(self):
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
             patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
             patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
             patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
            health.order_by.return_value.first.return_value = None
            dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = None
            portfolio_manager.filter.return_value.only.return_value.first.return_value = None
            lot_manager.filter.return_value.aggregate.return_value = {
                "open_quantity": None,
                "open_lot_count": 0,
                "first_opened_at": None,
                "last_opened_at": None,
            }
            response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

        self.assertEqual(response.status_code, 404)

    def test_inventory_returns_spot_event_evidence_even_without_projection_or_open_lots(self):
        observed_at = timezone.now()
        spot_row = SimpleNamespace(
            spot_quantity=Decimal("0.000093"),
            open_lot_quantity=Decimal("0.25"),
            price_usdt=Decimal("2370"),
            estimated_value_usdt=Decimal("0.22041"),
            event_type="lot_balance_drift_detected",
            reason="balance differs from open FIFO lots",
            source="dust_detection_service",
            detected_at=observed_at,
        )
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
             patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
             patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
             patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
            health.order_by.return_value.first.return_value = None
            dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = spot_row
            portfolio_manager.filter.return_value.only.return_value.first.return_value = None
            lot_manager.filter.return_value.aggregate.return_value = {
                "open_quantity": None, "open_lot_count": 0,
                "first_opened_at": None, "last_opened_at": None,
            }
            response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsNone(payload["portfolio"]["quantity"])
        self.assertEqual(payload["latest_spot_observation"]["observed_spot_quantity"], "0.000093")

    def test_inventory_marks_stale_or_malformed_valuation_unavailable(self):
        now = timezone.now()
        stale = now - timedelta(hours=1)
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
             patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
             patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
             patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
            health.order_by.return_value.first.return_value = SimpleNamespace(
                status="ok", created_at=stale, details={}
            )
            dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = SimpleNamespace(
                spot_quantity=Decimal("0.000093"), open_lot_quantity=Decimal("0.25"),
                price_usdt=Decimal("2370"), estimated_value_usdt=Decimal("0.22041"),
                event_type="lot_balance_drift_detected", reason="historical",
                source="dust_detection_service", detected_at=stale,
            )
            portfolio_manager.filter.return_value.only.return_value.first.return_value = SimpleNamespace(
                quantity=Decimal("NaN"), entry_price=None, current_price=Decimal("3200"), updated_at=stale
            )
            lot_manager.filter.return_value.aggregate.return_value = {
                "open_quantity": Decimal("0.1"),
                "open_lot_count": 1,
                "first_opened_at": stale,
                "last_opened_at": stale,
            }
            response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["portfolio"]["freshness"], "stale")
        self.assertIsNone(payload["portfolio"]["quantity"])
        self.assertIsNone(payload["portfolio"]["estimated_value_usdt"])
        self.assertEqual(payload["portfolio"]["valuation_status"], "unavailable")
        self.assertEqual(payload["buy_capacity"]["freshness"], "stale")
        self.assertEqual(payload["buy_capacity"]["symbol_classification"], "unavailable")
        self.assertEqual(payload["latest_spot_observation"]["observation_recency"], "stale")
        self.assertEqual(payload["latest_spot_observation"]["detected_at"], stale.isoformat())
        self.assertEqual(payload["buy_capacity"]["capacity_status"], "historical")
        self.assertIsNone(payload["buy_capacity"]["global"])
        self.assertIsNone(payload["buy_capacity"]["historical_global"])

    def test_missing_and_malformed_spot_observations_do_not_create_a_current_balance(self):
        now = timezone.now()
        cases = (
            (None, "unavailable"),
            (SimpleNamespace(spot_quantity=Decimal("NaN"), detected_at=now), "recent"),
        )
        for spot_row, expected_recency in cases:
            with self.subTest(expected_recency=expected_recency), \
                 patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
                 patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
                 patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
                 patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
                health.order_by.return_value.first.return_value = None
                dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = spot_row
                portfolio_manager.filter.return_value.only.return_value.first.return_value = None
                lot_manager.filter.return_value.aggregate.return_value = {
                    "open_quantity": Decimal("0"), "open_lot_count": 1,
                    "first_opened_at": now, "last_opened_at": now,
                }
                response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

            self.assertEqual(response.status_code, 200)
            observation = response.json()["latest_spot_observation"]
            self.assertIsNone(observation["observed_spot_quantity"])
            self.assertEqual(observation["quantity_status"], "unavailable")
            self.assertEqual(observation["observation_recency"], expected_recency)
            self.assertFalse(observation["current_exchange_truth"])
            if spot_row:
                self.assertEqual(observation["detected_at"], now.isoformat())

    def test_absent_and_partial_healthcheck_capacity_are_explicit(self):
        now = timezone.now()
        cases = (
            (None, "unavailable"),
            (SimpleNamespace(status="ok", created_at=now, details={"max_positions": 15}),
             "partial_as_of_healthcheck"),
        )
        for health_row, expected_status in cases:
            with self.subTest(expected_status=expected_status), \
                 patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
                 patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
                 patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
                 patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
                health.order_by.return_value.first.return_value = health_row
                dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = None
                portfolio_manager.filter.return_value.only.return_value.first.return_value = None
                lot_manager.filter.return_value.aggregate.return_value = {
                    "open_quantity": Decimal("0"), "open_lot_count": 1,
                    "first_opened_at": now, "last_opened_at": now,
                }
                response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

            self.assertEqual(response.status_code, 200)
            capacity = response.json()["buy_capacity"]
            self.assertEqual(capacity["capacity_status"], expected_status)
            if health_row is None:
                self.assertIsNone(capacity["global"])
            else:
                self.assertEqual(capacity["global"]["max_positions"], 15)
                self.assertIsNone(capacity["global"]["effective_positions_count"])

    def test_stale_capacity_is_labeled_historical_and_never_returned_as_current(self):
        stale = timezone.now() - timedelta(hours=1)
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
             patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
             patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
             patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
            health.order_by.return_value.first.return_value = SimpleNamespace(
                status="ok", created_at=stale,
                details={"max_positions": 15, "effective_positions_count": 14,
                         "remaining_buy_capacity": 1},
            )
            dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = None
            portfolio_manager.filter.return_value.only.return_value.first.return_value = SimpleNamespace(
                quantity=Decimal("0.1"), entry_price=None, current_price=Decimal("1"),
                updated_at=stale,
            )
            lot_manager.filter.return_value.aggregate.return_value = {
                "open_quantity": Decimal("0.1"), "open_lot_count": 1,
                "first_opened_at": stale, "last_opened_at": stale,
            }
            response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

        capacity = response.json()["buy_capacity"]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(capacity["capacity_status"], "historical")
        self.assertIsNone(capacity["global"])
        self.assertEqual(capacity["historical_global"]["remaining_buy_capacity"], 1)

    def test_cross_source_comparison_is_marked_non_atomic_and_not_synchronized(self):
        now = timezone.now()
        detected_at = now - timedelta(minutes=12)
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
             patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
             patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
             patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
            health.order_by.return_value.first.return_value = None
            dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = SimpleNamespace(
                spot_quantity=Decimal("0.000093"), detected_at=detected_at
            )
            portfolio_manager.filter.return_value.only.return_value.first.return_value = SimpleNamespace(
                quantity=Decimal("0.25"), entry_price=None, current_price=Decimal("3200"),
                updated_at=now,
            )
            lot_manager.filter.return_value.aggregate.return_value = {
                "open_quantity": Decimal("0.2"), "open_lot_count": 1,
                "first_opened_at": detected_at, "last_opened_at": detected_at,
            }
            response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(payload["consistency"]["atomic"])
        self.assertEqual(payload["consistency"]["mode"], "separate_queries")
        self.assertEqual(payload["latest_spot_observation"]["detected_at"], detected_at.isoformat())
        self.assertEqual(payload["portfolio"]["updated_at"], now.isoformat())
        self.assertEqual(payload["quantity_difference"]["comparability"], "not_synchronized")

    def test_stale_projection_value_is_labeled_stale(self):
        stale = timezone.now() - timedelta(hours=1)
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health, \
             patch("dashboard.bot_diagnostics_api.DustDetection.objects") as dust_manager, \
             patch("dashboard.bot_diagnostics_api.Portfolio.objects") as portfolio_manager, \
             patch("dashboard.bot_diagnostics_api.PositionLot.objects") as lot_manager:
            health.order_by.return_value.first.return_value = None
            dust_manager.filter.return_value.only.return_value.order_by.return_value.first.return_value = None
            portfolio_manager.filter.return_value.only.return_value.first.return_value = SimpleNamespace(
                quantity=Decimal("0.1"), entry_price=Decimal("3000"),
                current_price=Decimal("3200"), updated_at=stale,
            )
            lot_manager.filter.return_value.aggregate.return_value = {
                "open_quantity": Decimal("0.1"), "open_lot_count": 1,
                "first_opened_at": stale, "last_opened_at": stale,
            }
            response = self.client.get("/api/bot/inventory/ETHUSDT", **self.auth)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["portfolio"]["valuation_status"], "stale")
        self.assertEqual(response.json()["portfolio"]["freshness"], "stale")

    def test_database_failure_is_safely_reported_without_exception_details(self):
        with patch("dashboard.bot_diagnostics_api.BotHealthcheck.objects") as health:
            health.order_by.side_effect = DatabaseError("secret database connection string")
            response = self.client.get("/api/bot/health", **self.auth)

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret database connection string", response.content.decode())

    def test_post_is_rejected_and_response_disables_caching(self):
        response = self.client.post("/api/bot/health", {}, **self.auth)
        self.assertEqual(response.status_code, 405)
        for method in ("put", "patch", "delete"):
            self.assertEqual(
                getattr(self.client, method)("/api/bot/health", **self.auth).status_code,
                405,
            )
        get_response = self.client.get("/api/bot/health", **self.auth)
        self.assertEqual(get_response.status_code, 503)
        self.assertEqual(get_response["Cache-Control"], "no-store")
