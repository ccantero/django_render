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


def postgresql_relation_exists(relation_name):
	with connection.cursor() as cursor:
		cursor.execute("SELECT to_regclass(%s)", [relation_name])
		return cursor.fetchone()[0] is not None


def bot_dust_signal_review_table_exists():
	return postgresql_relation_exists("bot.dust_signal_reviews")


def postgresql_flush_table_names(tables, *fixture_tables):
	"""Return the exact PostgreSQL relations that test cleanup may truncate.

	The disposable PostgreSQL settings place Django-managed relations in the
	``django`` schema.  Qualifying them removes any dependency on a connection's
	current search path and lets PostgreSQL see each test-only dust-review table
	and its ``profile_userprofile`` foreign-key target in the same TRUNCATE
	statement.
	"""
	return [*(f'"django"."{table}"' for table in tables), *fixture_tables]


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
	with django_db_blocker.unblock():
		if connection.vendor != "postgresql":
			existing_tables = connection.introspection.table_names()
			if DustSignalReview._meta.db_table not in existing_tables:
				with connection.schema_editor() as schema_editor:
					schema_editor.create_model(DustSignalReview)
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
			if kwargs.get("only_existing", False):
				fixture_tables = []
				# The historical migration created this Django-schema table, but
				# the current unmanaged model no longer represents it. It still has
				# a FK to profile_userprofile and must participate in test flush.
				if postgresql_relation_exists("django.dust_signal_reviews"):
					fixture_tables.append('"django"."dust_signal_reviews"')
				if bot_dust_signal_review_table_exists():
					fixture_tables.append(DustSignalReview._meta.db_table)
				if fixture_tables:
					return postgresql_flush_table_names(
						tables,
						*fixture_tables,
					)
			return tables

		connection.introspection.django_table_names = django_table_names_with_bot_fixture
	try:
		yield
	finally:
		connection.introspection.django_table_names = original_django_table_names
