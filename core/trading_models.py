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
	order_id = models.CharField(max_length=128, blank=True, null=True)
	symbol = models.CharField(max_length=32)
	side = models.CharField(max_length=16)
	status = models.CharField(max_length=32, blank=True, null=True)
	executed_base_qty = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	gross_quote = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	net_quote = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	created_at = models.DateTimeField(blank=True, null=True)
	executed_at = models.DateTimeField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."trade_operations"'
		app_label = "trading_read"


class TradeFill(ReadOnlyTradingModel):
	order_id = models.CharField(max_length=128, blank=True, null=True)
	symbol = models.CharField(max_length=32)
	side = models.CharField(max_length=16, blank=True, null=True)
	executed_quantity = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	executed_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	quote_quantity = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	commission = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	commission_asset = models.CharField(max_length=32, blank=True, null=True)
	timestamp = models.DateTimeField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."trade_fills"'
		app_label = "trading_read"


class LotClosure(ReadOnlyTradingModel):
	trade_operation_id = models.BigIntegerField()
	closed_lot_id = models.BigIntegerField()
	closed_quantity = models.DecimalField(max_digits=36, decimal_places=18)
	entry_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	exit_price = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	realized_pnl = models.DecimalField(max_digits=36, decimal_places=18, blank=True, null=True)
	timestamp = models.DateTimeField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."lot_closures"'
		app_label = "trading_read"


class Snapshot(ReadOnlyTradingModel):
	created_at = models.DateTimeField(blank=True, null=True)
	data = models.JSONField(blank=True, null=True)

	class Meta:
		managed = False
		db_table = '"bot"."snapshots"'
		app_label = "trading_read"


PortfolioPosition = Portfolio
Healthcheck = BotHealthcheck
