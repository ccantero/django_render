import pytest
from django.db import connection

from core.models import DustSignalReview


def assert_postgresql_test_schemas():
	if connection.vendor != "postgresql":
		return

	with connection.cursor() as cursor:
		cursor.execute(
			"SELECT schema_name FROM information_schema.schemata "
			"WHERE schema_name IN ('bot', 'django')"
		)
		schemas = {row[0] for row in cursor.fetchall()}
	missing = {"bot", "django"} - schemas
	if missing:
		raise RuntimeError(
			"Disposable PostgreSQL test database is missing required schemas: "
			+ ", ".join(sorted(missing))
		)


def bot_dust_signal_review_table_exists():
	with connection.cursor() as cursor:
		cursor.execute("SELECT to_regclass('bot.dust_signal_reviews')")
		return cursor.fetchone()[0] is not None


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
	with django_db_blocker.unblock():
		if connection.vendor != "postgresql":
			yield
			return

		assert_postgresql_test_schemas()
		if not bot_dust_signal_review_table_exists():
			with connection.schema_editor() as schema_editor:
				schema_editor.create_model(DustSignalReview)

		# DustSignalReview is bot-owned in production and therefore remains
		# ``managed = False``. This fixture created the isolated test surrogate,
		# whose FK to profile_userprofile must be included in the same PostgreSQL
		# TRUNCATE as its Django-owned target. Register only this fixture table
		# with Django's test flush; do not change model ownership or use CASCADE.
		original_django_table_names = connection.introspection.django_table_names

		def django_table_names_with_bot_fixture(*args, **kwargs):
			tables = original_django_table_names(*args, **kwargs)
			if kwargs.get("only_existing", False) and bot_dust_signal_review_table_exists():
				return [*tables, DustSignalReview._meta.db_table]
			return tables

		connection.introspection.django_table_names = django_table_names_with_bot_fixture
	try:
		yield
	finally:
		connection.introspection.django_table_names = original_django_table_names
