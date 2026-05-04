import pytest
from django.db import connection

from core.models import DustSignalReview


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
	with django_db_blocker.unblock():
		existing_tables = connection.introspection.table_names()
		if DustSignalReview._meta.db_table in existing_tables:
			return
		with connection.schema_editor() as schema_editor:
			schema_editor.create_model(DustSignalReview)
