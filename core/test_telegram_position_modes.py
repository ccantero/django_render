import json
import re
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import patch

from django.db import DatabaseError, ProgrammingError, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone


TELEGRAM_TEXT_LIMIT = 4096
SAFE_READ_ERROR = "Generation data unavailable (read error)"
NO_CLASSIFICATION = (
    "No healthcheck classification is available. "
    "Material symbols were not taken from portfolio."
)
HOLD_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
TRADING_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
SECOND_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
CLOSED_IDS = [
    uuid.UUID("44444444-4444-4444-4444-444444444441"),
    uuid.UUID("44444444-4444-4444-4444-444444444442"),
    uuid.UUID("44444444-4444-4444-4444-444444444443"),
    uuid.UUID("44444444-4444-4444-4444-444444444444"),
]


def _text(result):
    if isinstance(result, list):
        return "\n".join(result)
    return result


def _balanced_html(chunk):
    for tag in ("b", "code"):
        if chunk.count(f"<{tag}>") != chunk.count(f"</{tag}>"):
            return False
    if chunk.count("<") != chunk.count(">"):
        return False
    return "<" not in chunk or not chunk.rstrip().endswith("<")


def _entities_complete(chunk):
    stripped = re.sub(r"&(?:[a-zA-Z]+|#\d+|#x[0-9a-fA-F]+);", "", chunk)
    return "&" not in stripped


class PositionModeDispatchTests(TestCase):
    def test_unauthorized_chat_or_user_rejected(self):
        from core.telegram_diagnostics import diagnostic_response

        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS="999", TELEGRAM_ALLOWED_USER_IDS="42"):
            self.assertEqual(
                diagnostic_response("/position_modes", "111", user_id=7),
                "Unauthorized diagnostics request.",
            )
            self.assertEqual(
                diagnostic_response("/position_mode ENAUSDT", "111", user_id=7),
                "Unauthorized diagnostics request.",
            )

    def test_existing_commands_and_help_still_work(self):
        from core.telegram_diagnostics import DIAGNOSTIC_COMMANDS, diagnostic_response, format_help
        from core.views import HELP_RESPONSE

        for command in (
            "/help",
            "/health",
            "/position",
            "/last_sell",
            "/why_not_sell",
            "/buy_status",
            "/portfolio_status",
            "/last_operations",
            "/position_modes",
            "/position_mode",
        ):
            self.assertIn(command, DIAGNOSTIC_COMMANDS)
        for text in (format_help(), HELP_RESPONSE):
            self.assertIn("/health", text)
            self.assertIn("/buy_status", text)
            self.assertIn("/portfolio_status", text)
            self.assertIn("/last_operations", text)
            self.assertIn("/position SYMBOL", text)
            self.assertIn("/last_sell SYMBOL", text)
            self.assertIn("/why_not_sell SYMBOL", text)
            self.assertIn("/position_modes", text)
            self.assertIn("/position_mode SYMBOL", text)
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS="999"):
            self.assertIn("Usage:", diagnostic_response("/last_operations 0", "999"))
            self.assertEqual(
                diagnostic_response("/position bad", "999"),
                "Invalid symbol. Use uppercase letters/numbers, max 20 chars.",
            )
            self.assertIn("Bot commands", diagnostic_response("/help", "999"))

    @patch("core.views.TELEGRAM_WEBHOOK_TOKEN", "test-webhook-token")
    @patch("core.views.send_message", side_effect=[True, False, AssertionError("remaining chunk must not be sent")])
    @patch("core.views.diagnostic_response", return_value=["<b>one</b>", "<b>two</b>", "<b>three</b>"])
    def test_chunk_send_failure_is_logged_without_retry(self, mock_diagnostic, mock_send):
        client = Client()
        payload = {
            "update_id": 77,
            "message": {
                "text": "/position_modes",
                "message_id": 8801,
                "chat": {"id": 999},
                "from": {"id": 7, "username": "operator"},
            },
        }
        with self.assertLogs("core.views", level="WARNING") as logs:
            response = client.post(
                reverse("listener"),
                data=json.dumps(payload),
                content_type="application/json",
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="test-webhook-token",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_send.call_count, 2)
        self.assertEqual(mock_send.call_args_list[0].args[0], "<b>one</b>")
        self.assertEqual(mock_send.call_args_list[1].args[0], "<b>two</b>")
        self.assertEqual([call.args[0] for call in mock_send.call_args_list].count("<b>two</b>"), 1)
        failed = [record for record in logs.records if getattr(record, "stage", None) == "outbound_chunk"]
        self.assertEqual(len(failed), 1)
        self.assertIs(failed[0].delivered, False)
        self.assertEqual(failed[0].chat_id, 999)
        self.assertEqual(failed[0].command, "/position_modes")
        mock_diagnostic.assert_called_once()

    def test_overlong_line_is_split_outside_entities_and_tags(self):
        from core.telegram_diagnostics import _split_html_messages

        payload = "&lt;" * 1500
        line = f"<b>note</b> Opening provenance: <code>{payload}</code>"
        self.assertGreater(len(line), TELEGRAM_TEXT_LIMIT)
        chunks = _split_html_messages(line)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(sum(chunk.count("&lt;") for chunk in chunks), 1500)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), TELEGRAM_TEXT_LIMIT)
            self.assertTrue(_balanced_html(chunk))
            self.assertTrue(_entities_complete(chunk))
            self.assertNotIn("<code></code>", chunk)
            self.assertNotIn("<b></b>", chunk)


@override_settings(TIME_ZONE="UTC", HEALTHCHECK_STALE_MINUTES=15, TELEGRAM_ALLOWED_CHAT_IDS="999", TELEGRAM_ALLOWED_USER_IDS="")
class PositionGenerationModeTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from core.trading_models import BotHealthcheck, Portfolio, PositionGeneration, PositionLot

        cls.BotHealthcheck = BotHealthcheck
        cls.Portfolio = Portfolio
        cls.PositionGeneration = PositionGeneration
        cls.PositionLot = PositionLot
        cls._bot_ready = False
        if connection.vendor == "sqlite":
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA database_list")
                attached = {row[1] for row in cursor.fetchall()}
                if "bot" not in attached:
                    cursor.execute("ATTACH DATABASE ':memory:' AS bot")
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(BotHealthcheck)
            schema_editor.create_model(Portfolio)
            schema_editor.create_model(PositionGeneration)
            schema_editor.create_model(PositionLot)
        cls._bot_ready = True

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "_bot_ready", False):
            with connection.schema_editor() as schema_editor:
                schema_editor.delete_model(cls.PositionLot)
                schema_editor.delete_model(cls.PositionGeneration)
                schema_editor.delete_model(cls.Portfolio)
                schema_editor.delete_model(cls.BotHealthcheck)
            if connection.vendor == "sqlite":
                with connection.cursor() as cursor:
                    cursor.execute("DETACH DATABASE bot")
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM "bot"."position_lots"')
            cursor.execute('DELETE FROM "bot"."position_generations"')
            cursor.execute('DELETE FROM "bot"."portfolio"')
            cursor.execute('DELETE FROM "bot"."bot_healthcheck"')

    def _run(self, text, chat_id="999", user_id=1):
        from core.telegram_diagnostics import diagnostic_response

        return diagnostic_response(text, chat_id, user_id=user_id)

    def _health(self, symbols=None, created_at=None, details=None, flat=False):
        if details is None:
            if symbols is None:
                details = {}
            elif flat:
                details = {"material_symbols": list(symbols)}
            else:
                details = {
                    "position_classification": {
                        "material_symbols": list(symbols),
                        "material_positions_count": len(symbols),
                    }
                }
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "bot"."bot_healthcheck" (status, created_at, details) VALUES (%s, %s, %s)',
                ["ok", created_at or timezone.now(), json.dumps(details)],
            )

    def _generation(self, generation_id, symbol, phase, created_at=None, **extra):
        columns = {
            "generation_id": str(generation_id),
            "symbol": symbol,
            "phase": phase,
            "opening_provenance": extra.get("opening_provenance"),
            "created_at": created_at or timezone.now(),
            "updated_at": extra.get("updated_at"),
            "hold_admitted_at": extra.get("hold_admitted_at"),
            "hold_admission_reason": extra.get("hold_admission_reason"),
            "peak_price_since_hold": extra.get("peak_price_since_hold"),
            "hold_stop_price": extra.get("hold_stop_price"),
            "hold_stop_updated_at": extra.get("hold_stop_updated_at"),
            "hold_stop_reason": extra.get("hold_stop_reason"),
            "hold_strategy_version": extra.get("hold_strategy_version"),
        }
        names = list(columns)
        sql = 'INSERT INTO "bot"."position_generations" ({}) VALUES ({})'.format(
            ", ".join(names),
            ", ".join(["%s"] * len(names)),
        )
        with connection.cursor() as cursor:
            cursor.execute(sql, [columns[name] for name in names])

    def _lot(self, lot_id, symbol, qty, generation_id=None):
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "bot"."position_lots" '
                "(lot_id, symbol, quantity_original, quantity_open, generation_id) "
                "VALUES (%s, %s, %s, %s, %s)",
                [lot_id, symbol, qty, qty, None if generation_id is None else str(generation_id)],
            )

    def _portfolio(self, symbol, quantity, current_price):
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO "bot"."portfolio" (symbol, quantity, current_price) VALUES (%s, %s, %s)',
                [symbol, quantity, current_price],
            )

    def test_mapping_is_unmanaged_read_only(self):
        field_names = {field.name for field in self.PositionGeneration._meta.fields}
        self.assertTrue(
            {
                "generation_id",
                "symbol",
                "phase",
                "opening_provenance",
                "created_at",
                "updated_at",
                "hold_admitted_at",
                "hold_admission_reason",
                "peak_price_since_hold",
                "hold_stop_price",
                "hold_stop_updated_at",
                "hold_stop_reason",
                "hold_strategy_version",
            }
            <= field_names
        )
        self.assertFalse(self.PositionGeneration._meta.managed)
        self.assertEqual(self.PositionGeneration._meta.db_table, '"bot"."position_generations"')
        peak = self.PositionGeneration._meta.get_field("peak_price_since_hold")
        stop = self.PositionGeneration._meta.get_field("hold_stop_price")
        self.assertEqual((peak.max_digits, peak.decimal_places), (38, 18))
        self.assertEqual((stop.max_digits, stop.decimal_places), (38, 18))
        generation_id = self.PositionLot._meta.get_field("generation_id")
        self.assertEqual(generation_id.db_column, "generation_id")
        self.assertTrue(generation_id.null)
        self.assertIsNone(generation_id.remote_field)
        with self.assertRaises(RuntimeError):
            self.PositionGeneration(generation_id=uuid.uuid4(), symbol="ENAUSDT").save()

    def test_hold_only_mode(self):
        admitted = datetime(2026, 10, 1, 12, 30, tzinfo=dt_timezone.utc)
        created = datetime(2026, 9, 30, 8, 0, tzinfo=dt_timezone.utc)
        self._health(["ENAUSDT"])
        self._generation(
            HOLD_ID,
            "ENAUSDT",
            "HOLD",
            created_at=created,
            opening_provenance="<script>",
            hold_admitted_at=admitted,
            peak_price_since_hold=Decimal("2.5"),
            hold_stop_price=Decimal("2.25"),
            hold_stop_reason="ratchet",
            hold_strategy_version="hold-v1",
        )
        self._lot("lot-a", "ENAUSDT", Decimal("1.25"), HOLD_ID)
        self._lot("lot-b", "ENAUSDT", Decimal("0.25"), HOLD_ID)
        self._lot("lot-zero", "ENAUSDT", Decimal("0"), HOLD_ID)
        self._portfolio("ENAUSDT", Decimal("1.5"), Decimal("2"))

        with CaptureQueriesContext(connection) as captured:
            listed = _text(self._run("/position_modes"))
            detail = _text(self._run("/position_mode ENAUSDT"))
        generation_queries = [
            query["sql"] for query in captured.captured_queries if "position_generations" in query["sql"]
        ]
        self.assertEqual(len(generation_queries), 2)
        self.assertIn("Material count: <code>1</code>", listed)
        self.assertIn("<code>fresh</code>", listed)
        self.assertIn("ENAUSDT — <code>HOLD</code>", listed)
        self.assertNotIn("UNKNOWN", listed)
        self.assertNotIn("INCONSISTENT", listed)
        self.assertIn("<b>Position mode ENAUSDT</b>", detail)
        self.assertIn("Mode: <code>HOLD</code>", detail)
        self.assertIn("Material list: <code>yes</code>", detail)
        self.assertIn(f"ID: <code>{HOLD_ID}</code>", detail)
        self.assertIn("Phase: <code>HOLD</code>", detail)
        self.assertIn("Opening provenance: <code>&lt;script&gt;</code>", detail)
        self.assertIn("Qty: <code>1.5</code>", detail)
        self.assertIn("Estimated value: <code>3 USDT</code>", detail)
        self.assertIn("Peak since hold: <code>2.5</code>", detail)
        self.assertIn("Hold stop price: <code>2.25</code>", detail)
        self.assertIn("Hold stop reason: <code>ratchet</code>", detail)
        self.assertIn("Hold admitted: <code>2026-10-01 12:30 UTC</code>", detail)
        self.assertIn("Hold strategy version: <code>hold-v1</code>", detail)
        self.assertIn("TP / SL / trailing %: <code>N/A</code>", detail)
        self.assertIn("Quantity comparison: <code>MATCH</code>", detail)
        self.assertIn("Closed-generation open qty: <code>0</code>", detail)
        self.assertIn("Missing-generation open qty: <code>0</code>", detail)
        self.assertIn("generationless (unassigned): <code>0</code>", detail)
        self.assertNotIn("<script>", detail)
        self.assertIn("Not live Binance Spot truth", detail)
        self.assertIn("No reconciliation", detail)

    def test_trading_only_mode(self):
        self._health(["BTCUSDT"], flat=True)
        self._generation(TRADING_ID, "BTCUSDT", "OPEN", opening_provenance="canonical_buy")
        self._lot("lot-t", "BTCUSDT", Decimal("4"), TRADING_ID)
        self._portfolio("BTCUSDT", Decimal("4"), None)
        listed = _text(self._run("/position_modes"))
        detail = _text(self._run("/position_mode BTCUSDT"))
        self.assertIn("BTCUSDT — <code>TRADING</code>", listed)
        self.assertIn("Mode: <code>TRADING</code>", detail)
        self.assertIn("Phase: <code>OPEN</code>", detail)
        self.assertIn("Opening provenance: <code>canonical_buy</code>", detail)
        self.assertIn("Estimated value: <code>N/A</code>", detail)
        self.assertIn("TP / SL / trailing %: <code>N/A</code>", detail)
        self.assertNotIn("Hold stop price:", detail)
        self.assertNotIn("HOLD", detail)

    def test_mixed_hold_and_trading_mode(self):
        self._health(["ENAUSDT"])
        self._generation(HOLD_ID, "ENAUSDT", "HOLD", created_at=timezone.now() - timedelta(hours=2))
        self._generation(
            TRADING_ID,
            "ENAUSDT",
            "PARTIAL_PENDING",
            created_at=timezone.now() - timedelta(hours=1),
            opening_provenance="canonical_buy",
        )
        self._lot("lot-h", "ENAUSDT", Decimal("1"), HOLD_ID)
        self._lot("lot-t", "ENAUSDT", Decimal("2"), TRADING_ID)
        self._portfolio("ENAUSDT", Decimal("3"), Decimal("1"))
        with CaptureQueriesContext(connection) as captured:
            detail = _text(self._run("/position_mode ENAUSDT"))
        lot_queries = [query["sql"] for query in captured.captured_queries if "position_lots" in query["sql"]]
        generation_queries = [
            query["sql"] for query in captured.captured_queries if "position_generations" in query["sql"]
        ]
        self.assertEqual(len(lot_queries), 1)
        self.assertEqual(len(generation_queries), 1)
        listed = _text(self._run("/position_modes"))
        self.assertIn("ENAUSDT — <code>HOLD + TRADING</code>", listed)
        self.assertIn("Mode: <code>HOLD + TRADING</code>", detail)
        self.assertIn(f"ID: <code>{HOLD_ID}</code>", detail)
        self.assertIn(f"ID: <code>{TRADING_ID}</code>", detail)
        self.assertLess(detail.index(str(HOLD_ID)), detail.index(str(TRADING_ID)))
        self.assertIn("Qty: <code>1</code>", detail)
        self.assertIn("Qty: <code>2</code>", detail)
        self.assertIn("Phase: <code>HOLD</code>", detail)
        self.assertIn("Phase: <code>PARTIAL_PENDING</code>", detail)
        self.assertEqual(detail.count("Hold stop price:"), 1)
        self.assertIn("Active generation qty: <code>3</code>", detail)
        self.assertIn("Quantity comparison: <code>MATCH</code>", detail)
        self.assertIn("Closed-generation open qty: <code>0</code>", detail)
        self.assertIn("Missing-generation open qty: <code>0</code>", detail)

    def test_two_active_generations_of_same_kind_are_inconsistent(self):
        self._health(["ENAUSDT", "SOLUSDT"])
        self._generation(HOLD_ID, "ENAUSDT", "HOLD")
        self._generation(SECOND_ID, "ENAUSDT", "HOLD")
        self._generation(TRADING_ID, "SOLUSDT", "OPEN")
        runner_id = uuid.UUID("55555555-5555-5555-5555-555555555555")
        self._generation(runner_id, "SOLUSDT", "RUNNER")
        listed = _text(self._run("/position_modes"))
        hold_detail = _text(self._run("/position_mode ENAUSDT"))
        trading_detail = _text(self._run("/position_mode SOLUSDT"))
        self.assertIn("ENAUSDT — <code>INCONSISTENT</code>", listed)
        self.assertIn("SOLUSDT — <code>INCONSISTENT</code>", listed)
        self.assertNotIn("ENAUSDT — <code>HOLD</code>", listed)
        self.assertNotIn("SOLUSDT — <code>TRADING</code>", listed)
        self.assertIn("Mode: <code>INCONSISTENT</code>", hold_detail)
        self.assertIn(f"ID: <code>{HOLD_ID}</code>", hold_detail)
        self.assertIn(f"ID: <code>{SECOND_ID}</code>", hold_detail)
        self.assertIn("Mode: <code>INCONSISTENT</code>", trading_detail)
        self.assertIn("Phase: <code>OPEN</code>", trading_detail)
        self.assertIn("Phase: <code>RUNNER</code>", trading_detail)

    def test_unrecognized_phase_is_inconsistent(self):
        self._health(["ENAUSDT"])
        self._generation(HOLD_ID, "ENAUSDT", "HOLD")
        self._generation(SECOND_ID, "ENAUSDT", "NOT_A_PHASE")
        detail = _text(self._run("/position_mode ENAUSDT"))
        listed = _text(self._run("/position_modes"))
        self.assertIn("ENAUSDT — <code>INCONSISTENT</code>", listed)
        self.assertIn("Mode: <code>INCONSISTENT</code>", detail)
        self.assertIn("Phase: <code>NOT_A_PHASE</code>", detail)
        self.assertNotIn("ENAUSDT — <code>HOLD</code>", listed)

    def test_closed_generation_excluded_from_mode_and_shown_as_historical(self):
        now = timezone.now()
        self._health(["ENAUSDT"])
        self._generation(HOLD_ID, "ENAUSDT", "HOLD", created_at=now)
        for offset, generation_id in enumerate(CLOSED_IDS, start=1):
            self._generation(
                generation_id,
                "ENAUSDT",
                "CLOSED",
                created_at=now - timedelta(days=offset),
            )
        self._lot("lot-h", "ENAUSDT", Decimal("1"), HOLD_ID)
        self._lot("lot-c", "ENAUSDT", Decimal("9"), CLOSED_IDS[0])
        self._portfolio("ENAUSDT", Decimal("1"), Decimal("1"))
        detail = _text(self._run("/position_mode ENAUSDT"))
        listed = _text(self._run("/position_modes"))
        active, _, historical = detail.partition("<b>Historical generations</b>")
        self.assertIn("ENAUSDT — <code>HOLD · unassigned qty</code>", listed)
        self.assertIn("Closed-generation open qty: <code>9</code>", detail)
        self.assertIn("Mode: <code>HOLD</code>", active)
        self.assertIn(str(HOLD_ID), active)
        self.assertNotIn(str(CLOSED_IDS[0]), active)
        self.assertIn("Count: <code>4</code>", historical)
        self.assertNotIn(str(CLOSED_IDS[3]), historical)
        for generation_id in CLOSED_IDS[:3]:
            self.assertIn(str(generation_id), historical)
        self.assertLess(historical.index(str(CLOSED_IDS[0])), historical.index(str(CLOSED_IDS[2])))
        self.assertIn("Phase: <code>CLOSED</code>", historical)
        self.assertIn("Active generation qty: <code>1</code>", detail)

    def test_material_symbol_without_generations_is_unknown(self):
        self._health(["ADAUSDT"])
        listed = _text(self._run("/position_modes"))
        detail = _text(self._run("/position_mode ADAUSDT"))
        self.assertIn("Material count: <code>1</code>", listed)
        self.assertIn("ADAUSDT — <code>UNKNOWN (no generation)</code>", listed)
        self.assertIn("Mode: <code>UNKNOWN (no generation)</code>", detail)
        self.assertIn("Material list: <code>yes</code>", detail)
        self.assertIn("No position data for this symbol.", detail)
        self.assertIn("Historical generations", detail)
        self.assertIn("Count: <code>0</code>", detail)

    def test_all_generationless_open_lots_remain_unknown(self):
        self._health(["GENLESSUSDT"])
        self._lot("lot-1", "GENLESSUSDT", Decimal("4"))
        self._lot("lot-2", "GENLESSUSDT", Decimal("1"))
        self._portfolio("GENLESSUSDT", Decimal("5"), Decimal("1"))
        listed = _text(self._run("/position_modes"))
        detail = _text(self._run("/position_mode GENLESSUSDT"))
        self.assertIn("GENLESSUSDT — <code>UNKNOWN (no generation) · unassigned qty</code>", listed)
        self.assertIn("Mode: <code>UNKNOWN (no generation)</code>", detail)
        self.assertIn("generationless (unassigned): <code>5</code>", detail)
        self.assertIn("Open-lot qty: <code>5</code>", detail)
        self.assertIn("Active generation qty: <code>0</code>", detail)
        self.assertIn("Portfolio qty: <code>5</code>", detail)
        self.assertIn("Quantity comparison: <code>MATCH</code>", detail)
        self.assertIn("Closed-generation open qty: <code>0</code>", detail)
        self.assertIn("Missing-generation open qty: <code>0</code>", detail)
        self.assertNotIn("INCONSISTENT", detail)
        self.assertNotIn("MISMATCH", detail)

    def test_quantity_mismatch_includes_generationless_unassigned_lots(self):
        self._health(["ENAUSDT"])
        self._generation(HOLD_ID, "ENAUSDT", "HOLD")
        self._generation(CLOSED_IDS[0], "ENAUSDT", "CLOSED", created_at=timezone.now() - timedelta(days=1))
        self._lot("lot-active", "ENAUSDT", Decimal("10"), HOLD_ID)
        self._lot("lot-free", "ENAUSDT", Decimal("3"))
        self._lot("lot-closed", "ENAUSDT", Decimal("2"), CLOSED_IDS[0])
        self._portfolio("ENAUSDT", Decimal("20"), Decimal("1"))
        detail = _text(self._run("/position_mode ENAUSDT"))
        self.assertIn("Mode: <code>HOLD</code>", detail)
        self.assertIn("Active generation qty: <code>10</code>", detail)
        self.assertIn("Open-lot qty: <code>15</code>", detail)
        self.assertIn("generationless (unassigned): <code>3</code>", detail)
        self.assertIn("Portfolio qty: <code>20</code>", detail)
        self.assertIn("Quantity comparison: <code>MISMATCH</code>", detail)
        self.assertIn("Closed-generation open qty: <code>2</code>", detail)
        self.assertIn("Missing-generation open qty: <code>0</code>", detail)
        self.assertIn("Delta (open-lot qty - portfolio qty): <code>-5</code>", detail)
        self.assertIn("does not prove accounting integrity", detail)
        self.assertNotIn("Consistency:", detail)
        self.assertIn("not synchronized", detail.lower())

    def test_summary_qualifies_mixed_assigned_and_unassigned_lots(self):
        missing_id = uuid.UUID("66666666-6666-6666-6666-666666666666")
        self._health(["ENAUSDT", "BTCUSDT", "SOLUSDT", "XRPUSDT"])
        self._generation(HOLD_ID, "ENAUSDT", "HOLD")
        self._lot("ena-assigned", "ENAUSDT", Decimal("8"), HOLD_ID)
        self._lot("ena-null", "ENAUSDT", Decimal("2"))
        self._portfolio("ENAUSDT", Decimal("10"), Decimal("1"))
        self._generation(TRADING_ID, "BTCUSDT", "OPEN")
        self._generation(CLOSED_IDS[0], "BTCUSDT", "CLOSED", created_at=timezone.now() - timedelta(days=1))
        self._lot("btc-assigned", "BTCUSDT", Decimal("4"), TRADING_ID)
        self._lot("btc-closed", "BTCUSDT", Decimal("1"), CLOSED_IDS[0])
        self._portfolio("BTCUSDT", Decimal("5"), Decimal("1"))
        self._generation(SECOND_ID, "SOLUSDT", "RUNNER")
        self._lot("sol-assigned", "SOLUSDT", Decimal("3"), SECOND_ID)
        self._lot("sol-missing", "SOLUSDT", Decimal("1"), missing_id)
        self._portfolio("SOLUSDT", Decimal("4"), Decimal("1"))
        self._generation(CLOSED_IDS[1], "XRPUSDT", "HOLD")
        self._lot("xrp-assigned", "XRPUSDT", Decimal("2"), CLOSED_IDS[1])
        self._portfolio("XRPUSDT", Decimal("2"), Decimal("1"))

        with CaptureQueriesContext(connection) as captured:
            listed = _text(self._run("/position_modes"))
        lot_queries = [query["sql"] for query in captured.captured_queries if "position_lots" in query["sql"]]
        generation_queries = [
            query["sql"] for query in captured.captured_queries if "position_generations" in query["sql"]
        ]
        portfolio_queries = [query["sql"] for query in captured.captured_queries if "portfolio" in query["sql"].lower()]
        self.assertEqual(len(lot_queries), 1)
        self.assertEqual(len(generation_queries), 1)
        self.assertEqual(portfolio_queries, [])
        self.assertIn("ENAUSDT — <code>HOLD · unassigned qty</code>", listed)
        self.assertIn("BTCUSDT — <code>TRADING · unassigned qty</code>", listed)
        self.assertIn("SOLUSDT — <code>TRADING · unassigned qty</code>", listed)
        self.assertIn("XRPUSDT — <code>HOLD</code>", listed)
        self.assertNotIn("XRPUSDT — <code>HOLD · unassigned qty</code>", listed)
        self.assertNotIn("ENAUSDT — <code>HOLD</code>", listed.replace("HOLD · unassigned qty", "QUALIFIED"))

        ena = _text(self._run("/position_mode ENAUSDT"))
        self.assertIn("Mode: <code>HOLD</code>", ena)
        self.assertNotIn("unassigned qty", ena)
        btc = _text(self._run("/position_mode BTCUSDT"))
        self.assertIn("Mode: <code>TRADING</code>", btc)
        self.assertNotIn("HOLD", btc)
        sol = _text(self._run("/position_mode SOLUSDT"))
        self.assertIn("Mode: <code>TRADING</code>", sol)
        self.assertIn("Phase: <code>RUNNER</code>", sol)

    def test_quantity_comparison_reports_bad_associations_when_totals_match(self):
        missing_id = uuid.UUID("66666666-6666-6666-6666-666666666666")
        self._health(["ENAUSDT", "SOLUSDT"])
        self._generation(HOLD_ID, "ENAUSDT", "HOLD")
        self._generation(CLOSED_IDS[0], "ENAUSDT", "CLOSED", created_at=timezone.now() - timedelta(days=2))
        self._lot("ena-active", "ENAUSDT", Decimal("8"), HOLD_ID)
        self._lot("ena-closed", "ENAUSDT", Decimal("2"), CLOSED_IDS[0])
        self._portfolio("ENAUSDT", Decimal("10"), Decimal("1"))
        self._generation(TRADING_ID, "SOLUSDT", "FULL_EXIT_PENDING")
        self._lot("sol-active", "SOLUSDT", Decimal("6"), TRADING_ID)
        self._lot("sol-missing", "SOLUSDT", Decimal("4"), missing_id)
        self._portfolio("SOLUSDT", Decimal("10"), Decimal("1"))

        ena = _text(self._run("/position_mode ENAUSDT"))
        sol = _text(self._run("/position_mode SOLUSDT"))
        listed = _text(self._run("/position_modes"))
        self.assertIn("Quantity comparison: <code>MATCH</code>", ena)
        self.assertIn("Closed-generation open qty: <code>2</code>", ena)
        self.assertIn("Missing-generation open qty: <code>0</code>", ena)
        self.assertIn("Active generation qty: <code>8</code>", ena)
        self.assertIn("Open-lot qty: <code>10</code>", ena)
        self.assertIn(
            "Quantity comparison only compares these aggregate quantities from separate reads. "
            "It does not prove accounting integrity or the Binance balance.",
            ena,
        )
        self.assertNotIn("Consistency:", ena)
        self.assertNotIn("Delta (open-lot qty - portfolio qty):", ena)
        self.assertIn("ENAUSDT — <code>HOLD · unassigned qty</code>", listed)
        self.assertIn("Quantity comparison: <code>MATCH</code>", sol)
        self.assertIn("Closed-generation open qty: <code>0</code>", sol)
        self.assertIn("Missing-generation open qty: <code>4</code>", sol)
        self.assertIn("SOLUSDT — <code>TRADING · unassigned qty</code>", listed)
        self.assertIn("does not prove accounting integrity", sol)
        self.assertIn("Binance balance", sol)

    def test_position_mode_overlong_field_and_large_closed_history_is_split(self):
        provenance = "<" * 1200
        history_ids = [uuid.UUID(f"77777777-7777-7777-7777-{index:012d}") for index in range(1, 41)]
        base = timezone.now()
        self._health(["ENAUSDT"])
        self._generation(
            HOLD_ID,
            "ENAUSDT",
            "HOLD",
            created_at=base - timedelta(days=30),
            opening_provenance=provenance,
        )
        self._lot("lot-h", "ENAUSDT", Decimal("1"), HOLD_ID)
        self._portfolio("ENAUSDT", Decimal("1"), Decimal("1"))
        for offset, generation_id in enumerate(history_ids):
            self._generation(
                generation_id,
                "ENAUSDT",
                "CLOSED",
                created_at=base - timedelta(minutes=offset),
            )
        result = self._run("/position_mode ENAUSDT")
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 1)
        joined = "\n".join(result)
        self.assertGreater(len(joined), TELEGRAM_TEXT_LIMIT)
        self.assertEqual(sum(chunk.count("&lt;") for chunk in result), 1200)
        self.assertIn("Count: <code>40</code>", joined)
        for generation_id in history_ids[:3]:
            self.assertTrue(any(str(generation_id) in chunk for chunk in result))
        self.assertNotIn(str(history_ids[-1]), joined)
        for chunk in result:
            self.assertLessEqual(len(chunk), TELEGRAM_TEXT_LIMIT)
            self.assertTrue(_balanced_html(chunk))
            self.assertTrue(_entities_complete(chunk))
            self.assertNotIn("omitted", chunk.lower())
            self.assertNotIn("truncated", chunk.lower())

    def test_invalid_and_unknown_symbols(self):
        self._health(["ENAUSDT"])
        self._generation(TRADING_ID, "XRPUSDT", "RUNNER", opening_provenance="canonical_buy")
        self._lot("lot-x", "XRPUSDT", Decimal("1"), TRADING_ID)
        invalid = [
            "/position_mode",
            "/position_mode lowercase",
            "/position_mode bad/usdt",
            "/position_mode " + ("A" * 21),
        ]
        for command in invalid:
            self.assertEqual(
                self._run(command),
                "Invalid symbol. Use uppercase letters/numbers, max 20 chars.",
                command,
            )
        unknown = _text(self._run("/position_mode NOTINLISTUSDT"))
        self.assertIn("Mode: <code>UNKNOWN (no generation)</code>", unknown)
        self.assertIn("Material list: <code>no</code>", unknown)
        self.assertIn("No position data for this symbol.", unknown)
        self.assertNotIn("INCONSISTENT", unknown)
        other = _text(self._run("/position_mode XRPUSDT"))
        self.assertIn("Mode: <code>TRADING</code>", other)
        self.assertIn("Material list: <code>no</code>", other)
        self.assertIn("Phase: <code>RUNNER</code>", other)
        self.assertNotIn("No position data", other)

    def test_position_modes_over_4096_is_split_without_truncation(self):
        symbols = [f"S{index:04d}USDT" for index in range(120)]
        self._health(symbols)
        result = self._run("/position_modes")
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 1)
        joined = "\n".join(result)
        self.assertGreater(len(joined), TELEGRAM_TEXT_LIMIT)
        self.assertIn("Material count: <code>120</code>", joined)
        for chunk in result:
            self.assertLessEqual(len(chunk), TELEGRAM_TEXT_LIMIT)
            self.assertTrue(_balanced_html(chunk), chunk[:120])
            self.assertNotIn("omitted", chunk.lower())
            self.assertNotIn("truncated", chunk.lower())
        for symbol in symbols:
            self.assertIn(f"{symbol} — <code>UNKNOWN (no generation)</code>", joined)
            self.assertTrue(any(symbol in chunk for chunk in result))
        with CaptureQueriesContext(connection) as captured:
            self._run("/position_modes")
        generation_queries = [
            query["sql"] for query in captured.captured_queries if "position_generations" in query["sql"]
        ]
        portfolio_queries = [query["sql"] for query in captured.captured_queries if "portfolio" in query["sql"].lower()]
        self.assertEqual(len(generation_queries), 1)
        self.assertEqual(portfolio_queries, [])

    def test_stale_healthcheck_is_flagged(self):
        self._health(["ENAUSDT"], created_at=timezone.now() - timedelta(minutes=20))
        self._generation(HOLD_ID, "ENAUSDT", "HOLD")
        self._portfolio("EXTRAUSDT", Decimal("50"), Decimal("1"))
        listed = _text(self._run("/position_modes"))
        self.assertIn("<code>stale</code>", listed)
        self.assertIn("Healthcheck stale", listed)
        self.assertIn("20m", listed)
        self.assertIn("ENAUSDT — <code>HOLD</code>", listed)
        self.assertNotIn("EXTRAUSDT", listed)
        self.assertNotIn(NO_CLASSIFICATION, listed)

    def test_missing_healthcheck_classification_is_explicit(self):
        self._portfolio("ONLYUSDT", Decimal("10"), Decimal("1"))
        missing = _text(self._run("/position_modes"))
        self.assertIn(NO_CLASSIFICATION, missing)
        self.assertNotIn("ONLYUSDT", missing)
        self.assertNotIn("<code>fresh</code>", missing)
        self._health(details={"run_id": "run-1"})
        unclassified = _text(self._run("/position_modes"))
        self.assertIn(NO_CLASSIFICATION, unclassified)
        self.assertIn("Healthcheck:", unclassified)
        self.assertNotIn("ONLYUSDT", unclassified)
        detail = _text(self._run("/position_mode ENAUSDT"))
        self.assertIn("Material list: <code>unavailable</code>", detail)
        self.assertIn(NO_CLASSIFICATION, detail)

    def test_database_error_returns_safe_reply_and_logs(self):
        self._health(["ENAUSDT"])
        leaked = "postgres secret SELECT position_generations host db.internal"
        with patch(
            "core.telegram_diagnostics.PositionGeneration.objects.filter",
            side_effect=DatabaseError(leaked),
        ):
            with self.assertLogs("core.telegram_diagnostics", level="ERROR") as logs:
                result = self._run("/position_mode ENAUSDT")
        self.assertEqual(result, SAFE_READ_ERROR)
        self.assertNotIn("secret", result)
        self.assertNotIn("SELECT", result)
        self.assertNotIn("postgres", result)
        self.assertNotIn("position_generations", result)
        self.assertEqual(logs.records[0].exception_class, "DatabaseError")
        self.assertEqual(logs.records[0].command, "/position_mode")
        self.assertEqual(logs.records[0].chat_id, "999")
        self.assertTrue(logs.records[0].stage)

    def test_permission_denied_returns_safe_reply_and_logs(self):
        self._health(["ENAUSDT"])
        error = ProgrammingError(
            'permission denied for table position_generations\nSELECT generation_id FROM "bot"."position_generations"'
        )
        with patch(
            "core.telegram_diagnostics.PositionGeneration.objects.filter",
            side_effect=error,
        ):
            with self.assertLogs("core.telegram_diagnostics", level="ERROR") as logs:
                result = self._run("/position_modes")
        self.assertEqual(result, SAFE_READ_ERROR)
        self.assertNotIn("permission denied", result.lower())
        self.assertNotIn("SELECT", result)
        self.assertNotIn("position_generations", result)
        self.assertNotIn("bot", result.lower())
        record = logs.records[0]
        self.assertEqual(record.exception_class, "ProgrammingError")
        self.assertEqual(record.command, "/position_modes")
        self.assertEqual(record.chat_id, "999")
        self.assertTrue(record.stage)

    def test_authorized_user_id_can_read_modes(self):
        from core.telegram_diagnostics import diagnostic_response

        self._health(["ENAUSDT"])
        with self.settings(TELEGRAM_ALLOWED_CHAT_IDS="", TELEGRAM_ALLOWED_USER_IDS="42"):
            rejected = diagnostic_response("/position_modes", "111", user_id=7)
            allowed = _text(diagnostic_response("/position_modes", "111", user_id=42))
        self.assertEqual(rejected, "Unauthorized diagnostics request.")
        self.assertIn("ENAUSDT — <code>UNKNOWN (no generation)</code>", allowed)
