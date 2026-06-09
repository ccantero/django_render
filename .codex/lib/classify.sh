#!/usr/bin/env bash

app_behavior_changes_exist() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '(^manage\.py$|^config/|^apps/|(^|.*/)(models|views|serializers|urls|settings|admin|forms|tasks)\.py$|(^|.*/)management/commands/|^templates/|^static/|^src/.*\.py$|^pytest\.ini$|^Dockerfile$|^docker-compose.*\.ya?ml$|^\.env\.example$)'
}

schema_changes_exist() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '(^src/sql/.*\.sql$|(^|.*/)migrations/|(^|.*/)schema|docs/db/|schema_snapshot|schema_columns|schema_indexes|schema_constraints)'
}

contract_changes_exist() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '(^docs/DATA_CONTRACT\.md$|^src/db/models\.py$|^src/repositories/|^src/services/.*health|^src/scripts/.*audit|^src/scripts/.*analyze)'
}

logging_changes_exist() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '(logging|notification|telegram|healthcheck|diagnostic|alert|cli|scripts/)'
}

kpi_observability_changes_exist() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '(^src/scripts/analyze_.*\.py$|^src/scripts/get_audit_events\.py$|^scripts/get_audit_details\.sh$|healthcheck|telegram|diagnostic|dashboard|read.?model|observability|analytics|KPI|kpi|^docs/KPI_REGISTRY\.md$)'
}

docs_governance_changes_exist() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '(^AGENTS\.md$|^\.codex/|^docs/CHANGELOG\.md$|^docs/.*\.md$|^README\.md$|^PLAN\.md$)'
}

docs_only_changes_exist() {
  local mode="${1:-all}"
  local file saw_change=0
  while IFS= read -r file; do
    is_meaningful_file "${file}" || continue
    saw_change=1
    case "${file}" in
      *.md|docs/*|.codex/hooks/README.md)
        ;;
      *)
        return 1
        ;;
    esac
  done < <(changed_files_for_mode "${mode}")
  [[ "${saw_change}" == "1" ]]
}

high_risk_changes_exist() {
  local mode="${1:-all}"
  if app_behavior_changes_exist "${mode}"; then
    return 0
  fi
  if has_changed_path_matching "${mode}" '(^docs/DATA_CONTRACT\.md$|^docs/db/|^src/sql/.*\.sql$|(^|.*/)migrations/|schema_snapshot|schema_columns|schema_indexes|schema_constraints)'; then
    return 0
  fi
  if has_changed_path_matching "${mode}" '(position_lots|lot_closures|trade_operations|reconciliation|fifo|accounting|manual_correction|manual-correction)'; then
    return 0
  fi
  if has_changed_path_matching "${mode}" '(^src/services/(buy|sell|order|reconciliation)|^src/bot\.py$|BUY|SELL|buy_service|sell_service|order_service)'; then
    return 0
  fi
  if logging_changes_exist "${mode}" || kpi_observability_changes_exist "${mode}"; then
    return 0
  fi
  if evidence_has '^impact:.*(behavior|contract|schema|logging|operations)'; then
    return 0
  fi
  return 1
}

medium_risk_changes_exist() {
  local mode="${1:-all}"
  if has_changed_path_matching "${mode}" '(^README\.md$|^PLAN\.md$|^docs/(PROJECT_STATE|ARCHITECTURE|DESIGN|CHANGELOG)\.md$|^\.env.*example|^tests/|^scripts/.*\.sh$)'; then
    return 0
  fi
  if has_changed_path_matching "${mode}" '^\.codex/(hooks|lib|skills|legacy)/'; then
    return 0
  fi
  if evidence_has '^impact:.*docs_only'; then
    return 0
  fi
  return 1
}

risk_level() {
  local mode="${1:-all}"
  if high_risk_changes_exist "${mode}"; then
    printf 'high\n'
  elif medium_risk_changes_exist "${mode}"; then
    printf 'medium\n'
  else
    printf 'low\n'
  fi
}

config_dependency_changes_exist() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '(^requirements.*\.txt$|^pyproject\.toml$|^poetry\.lock$|^Dockerfile$|^docker-compose.*\.ya?ml$|^\.env\.example$|(^|.*/)settings\.py$|^config/)'
}

impact_summary() {
  local mode="${1:-all}"
  local impacts=()
  app_behavior_changes_exist "${mode}" && impacts+=("behavior")
  contract_changes_exist "${mode}" && impacts+=("contract")
  schema_changes_exist "${mode}" && impacts+=("schema")
  logging_changes_exist "${mode}" && impacts+=("logging")
  kpi_observability_changes_exist "${mode}" && impacts+=("kpi_observability")
  docs_governance_changes_exist "${mode}" && impacts+=("docs_governance")
  docs_only_changes_exist "${mode}" && impacts+=("docs_only")
  config_dependency_changes_exist "${mode}" && impacts+=("config_dependency")
  if (( ${#impacts[@]} == 0 )); then
    printf 'none\n'
  else
    local IFS=','
    printf '%s\n' "${impacts[*]}"
  fi
}

warn_downstream_requirements() {
  local mode="${1:-all}"
  local impacts
  impacts="$(impact_summary "${mode}")"
  info "likely impact: ${impacts}"
  app_behavior_changes_exist "${mode}" && warn "behavior-like changes detected; post-task/pre-commit will require test evidence"
  contract_changes_exist "${mode}" && warn "contract-like changes detected; post-task/pre-commit will require docs and changelog handling"
  schema_changes_exist "${mode}" && warn "schema/migration-like changes detected; post-task/pre-commit will require docs/db update or follow-up evidence"
  logging_changes_exist "${mode}" && warn "logging/observability-like changes detected; post-task/pre-commit will require docs/changelog handling when applicable"
  kpi_observability_changes_exist "${mode}" && warn "KPI/observability-like changes detected; post-task/pre-commit will require KPI registry review evidence"
  config_dependency_changes_exist "${mode}" && warn "config/dependency changes detected; verify tests and docs before post-task/pre-commit"
  true
}
