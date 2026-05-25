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
  config_dependency_changes_exist "${mode}" && warn "config/dependency changes detected; verify tests and docs before post-task/pre-commit"
  true
}
