from django.db import models


class ReadOnlyTradingModel(models.Model):
	"""
	Base for tables owned by the external trading bot.
	Django maps them only to read data; schema and writes belong to the bot.
	"""

	def save(self, *args, **kwargs):
		raise RuntimeError("Trading bot tables are read-only from the Django dashboard.")

	def delete(self, *args, **kwargs):
		raise RuntimeError("Trading bot tables are read-only from the Django dashboard.")

	class Meta:
		abstract = True
		managed = False
		app_label = "trading_read"


class BotHealthcheck(ReadOnlyTradingModel):
	status = models.CharField(max_length=32, blank=True, null=True)
	probe_message = models.TextField(blank=True, null=True)
	created_at = models.DateTimeField(blank=True, null=True)
	details = models.JSONField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."bot_healthcheck"'
		app_label = "trading_read"


class Portfolio(ReadOnlyTradingModel):
	symbol = models.CharField(max_length=32, primary_key=True)
	asset = models.CharField(max_length=32, blank=True, null=True)
	quantity = models.DecimalField(max_digits=36, decimal_places=18)
	entry_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	current_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	updated_at = models.DateTimeField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."portfolio"'
		app_label = "trading_read"


class PositionLot(ReadOnlyTradingModel):
	lot_id = models.CharField(max_length=128, primary_key=True)
	symbol = models.CharField(max_length=32)
	original_quantity = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		db_column="quantity_original",
	)
	remaining_quantity = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		db_column="quantity_open",
	)
	entry_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	status = models.CharField(max_length=32, blank=True, null=True)
	opened_at = models.DateTimeField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."position_lots"'
		app_label = "trading_read"


class TradeOperation(ReadOnlyTradingModel):
	order_id = models.BigIntegerField(blank=True, null=True)
	client_order_id = models.TextField(blank=True, null=True)
	symbol = models.CharField(max_length=32)
	side = models.CharField(max_length=16)
	status = models.CharField(max_length=32, blank=True, null=True)
	base_asset = models.TextField(blank=True, null=True)
	quote_asset = models.TextField(blank=True, null=True)
	fee_asset = models.TextField(blank=True, null=True)
	executed_base_qty = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	gross_quote = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	fee_amount = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	fee_amount_in_quote = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	net_quote = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	fill_count = models.IntegerField(blank=True, null=True)
	created_at = models.DateTimeField(blank=True, null=True)
	executed_at = models.DateTimeField(blank=True, null=True)
	raw_payload = models.JSONField(blank=True, null=True)
	fee_details = models.JSONField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."trade_operations"'
		app_label = "trading_read"


class TradeFill(ReadOnlyTradingModel):
	run_id = models.CharField(max_length=128, blank=True, null=True)
	event_type = models.CharField(max_length=32)
	order_id = models.CharField(max_length=128, blank=True, null=True)
	symbol = models.CharField(max_length=32)
	side = models.CharField(max_length=16, blank=True, null=True)
	quantity = models.DecimalField(max_digits=36, decimal_places=18)
	price = models.DecimalField(max_digits=36, decimal_places=18)
	executed_at = models.DateTimeField()
	source = models.CharField(max_length=32)
	lot_id = models.CharField(max_length=128, blank=True, null=True)
	metadata = models.JSONField(blank=True, null=True)
	created_at = models.DateTimeField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."trade_fills"'
		app_label = "trading_read"


class LotClosure(ReadOnlyTradingModel):
	sell_fill_id = models.BigIntegerField()
	lot_id = models.CharField(max_length=128)
	symbol = models.CharField(max_length=32)
	trade_operation_id = models.BigIntegerField()
	closed_quantity = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		db_column="quantity_closed",
	)
	entry_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	exit_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	realized_pnl = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	closed_at = models.DateTimeField(blank=True, null=True)
	metadata = models.JSONField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."lot_closures"'
		app_label = "trading_read"


class Snapshot(ReadOnlyTradingModel):
	created_at = models.DateTimeField(blank=True, null=True)
	notes = models.JSONField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."portfolio_snapshots"'
		app_label = "trading_read"


class DustDetection(ReadOnlyTradingModel):
	run_id = models.CharField(max_length=128, blank=True, null=True)
	detected_at = models.DateTimeField(blank=True, null=True)
	event_type = models.CharField(max_length=64, blank=True, null=True)
	severity = models.CharField(max_length=32, blank=True, null=True)
	symbol = models.CharField(max_length=32, blank=True, null=True)
	asset = models.CharField(max_length=32, blank=True, null=True)
	spot_quantity = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		blank=True,
		null=True,
	)
	open_lot_quantity = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		blank=True,
		null=True,
	)
	quantity_delta = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		blank=True,
		null=True,
	)
	price_usdt = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		blank=True,
		null=True,
	)
	estimated_value_usdt = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		blank=True,
		null=True,
	)
	estimated_delta_value_usdt = models.DecimalField(
		max_digits=36,
		decimal_places=18,
		blank=True,
		null=True,
	)
	reason = models.TextField(blank=True, null=True)
	suggested_action = models.TextField(blank=True, null=True)
	source = models.CharField(max_length=128, blank=True, null=True)
	payload = models.JSONField(blank=True, null=True)
	created_at = models.DateTimeField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."dust_detections"'
		app_label = "trading_read"


class SellDecisionEvent(ReadOnlyTradingModel):
	symbol = models.CharField(max_length=32)
	event_name = models.CharField(max_length=128)
	reason = models.TextField(blank=True, null=True)
	validation_stage = models.CharField(max_length=128, blank=True, null=True)
	estimated_pnl_percent = models.DecimalField(
		max_digits=18,
		decimal_places=8,
		blank=True,
		null=True,
	)
	entry_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	current_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	stop_loss_threshold = models.DecimalField(
		max_digits=18,
		decimal_places=8,
		blank=True,
		null=True,
	)
	take_profit_threshold = models.DecimalField(
		max_digits=18,
		decimal_places=8,
		blank=True,
		null=True,
	)
	profit_guard_bypassed = models.BooleanField(blank=True, null=True)
	created_at = models.DateTimeField(blank=True, null=True)
	payload = models.JSONField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."sell_decision_events"'
		app_label = "trading_read"


PortfolioPosition = Portfolio
Healthcheck = BotHealthcheck
