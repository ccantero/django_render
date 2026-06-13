phases_completed: planner, implementer, tester, documentator
impact: behavior
tests_executed: .venv/bin/python -m pytest core/tests.py::BuyStatusPnlSummaryTests -q; .venv/bin/python -m pytest core/tests.py -q; .venv/bin/python -m pytest -q
pending_issues: none
tests_created: core/tests.py covers positive, negative, zero, mixed, empty, over-eight-position aggregation, unavailable material inputs, compact layout stability, format_buy_status wiring, and exact UTC operation-timestamp boundaries/fallback
failing_test_proof: focused PnL tests failed 8 tests before implementation for the old label, eight-row aggregation cap, and missing-material valuation falsely rendered as complete zero
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md, docs/db/*
docs_updated: README.md, docs/DESIGN.md, docs/PROJECT_STATE.md, docs/CHANGELOG.md, docs/KPI_REGISTRY.md, paired binanceBot/docs/KPI_REGISTRY.md
changelog: updated
schema_der: not_applicable: no schema, migration, index, constraint, or DB contract changed
data_contract_sync: not_applicable: existing shared contract semantics were reused without change
logging_observability: Telegram label now states UTC explicitly; open-position PnL covers all material rows and degrades to unavailable for incomplete inputs; existing useful logging is preserved
kpi_registry_reviewed: yes
kpi_registry_updated: yes
kpi_registry_sync_checked: yes
kpi_registry_sync_detail: stale pnl_by_day wording synchronized in both Django and paired bot registries
