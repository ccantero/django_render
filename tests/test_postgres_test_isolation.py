from conftest import postgresql_flush_table_names


def test_postgresql_flush_uses_explicit_schemas_for_both_dust_review_tables():
    tables = postgresql_flush_table_names(
        ["profile_userprofile", "django_migrations"],
        '"django"."dust_signal_reviews"',
        '"bot"."dust_signal_reviews"',
    )

    assert tables == [
        '"django"."profile_userprofile"',
        '"django"."django_migrations"',
        '"django"."dust_signal_reviews"',
        '"bot"."dust_signal_reviews"',
    ]
