#!/usr/bin/env bash

evidence_exists() {
  [[ -f "${EVIDENCE_FILE}" ]]
}

require_evidence_file() {
  if ! evidence_exists; then
    fail "workflow evidence file is missing: ${EVIDENCE_FILE}"
    fail "copy .codex/hooks/workflow-evidence.template.md to that path or set CODEX_WORKFLOW_EVIDENCE"
  fi
}

evidence_has() {
  local pattern="$1"
  evidence_exists && grep -Eq "${pattern}" "${EVIDENCE_FILE}"
}

require_evidence_marker() {
  local marker="$1"
  local description="$2"
  if ! evidence_has "${marker}"; then
    fail "workflow evidence is missing ${description}: ${marker}"
  fi
}

non_placeholder_value() {
  local key="$1"
  local value
  evidence_exists || return 1
  value="$(grep -E "^${key}:" "${EVIDENCE_FILE}" | head -n 1 | cut -d: -f2- | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' || true)"
  [[ -n "${value}" ]] || return 1
  [[ "${value}" != "pending" ]] || return 1
  [[ "${value}" != "TODO" ]] || return 1
  [[ "${value}" != "TBD" ]] || return 1
  [[ "${value}" != "<fill in>" ]] || return 1
  [[ "${value}" != "<required>" ]] || return 1
  [[ "${value}" != *"..."* ]] || return 1
  return 0
}

require_non_placeholder_value() {
  local key="$1"
  local description="$2"
  if ! non_placeholder_value "${key}"; then
    fail "workflow evidence has missing or placeholder ${description}: ${key}"
  fi
}

require_common_evidence() {
  require_evidence_marker '^phases_completed:[[:space:]]*planner,[[:space:]]*implementer,[[:space:]]*tester,[[:space:]]*documentator$' "single-agent phase completion"
  require_evidence_marker '^impact:[[:space:]]*(none|docs_only|behavior|contract|schema|logging|operations)(,[[:space:]]*(docs_only|behavior|contract|schema|logging|operations))*$' "impact classification"
  require_non_placeholder_value "tests_executed" "tests executed record"
  require_non_placeholder_value "pending_issues" "pending issues result"
}

warn_common_evidence() {
  if ! evidence_exists; then
    warn "low-risk staged changes without workflow evidence: ${EVIDENCE_FILE}"
    return 0
  fi
  evidence_has '^phases_completed:[[:space:]]*planner,[[:space:]]*implementer,[[:space:]]*tester,[[:space:]]*documentator$' || warn "workflow evidence is missing single-agent phase completion"
  evidence_has '^impact:[[:space:]]*(none|docs_only|behavior|contract|schema|logging|operations)(,[[:space:]]*(docs_only|behavior|contract|schema|logging|operations))*$' || warn "workflow evidence is missing impact classification"
  non_placeholder_value "tests_executed" || warn "workflow evidence is missing tests_executed"
  non_placeholder_value "pending_issues" || warn "workflow evidence is missing pending_issues"
}

require_behavior_tests_when_needed() {
  local mode="${1:-all}"
  if app_behavior_changes_exist "${mode}" || evidence_has '^impact:.*behavior'; then
    if ! non_placeholder_value "tests_created" || evidence_has '^tests_created:[[:space:]]*not_applicable:'; then
      fail "behavior-like changes require test evidence or touched tests"
    fi
    if ! non_placeholder_value "failing_test_proof" || evidence_has '^failing_test_proof:[[:space:]]*not_applicable:'; then
      fail "workflow evidence must record failing_test_proof for behavior changes"
    fi
  fi
}

require_docs_evidence_when_needed() {
  local mode="${1:-all}"
  if docs_governance_changes_exist "${mode}" || evidence_has '^impact:.*docs_only'; then
    require_non_placeholder_value "docs_reviewed" "docs reviewed record"
    require_non_placeholder_value "docs_updated" "docs updated record"
    require_evidence_marker '^changelog:[[:space:]]*(updated|not_applicable:.+)' "changelog handling"
  fi
}

require_contract_sync_when_needed() {
  local mode="${1:-all}"
  if has_changed_path_matching "${mode}" '^docs/DATA_CONTRACT\.md$' || evidence_has '^impact:.*contract'; then
    require_evidence_marker '^data_contract_sync:[[:space:]]*(verified:.+|not_applicable:.+|follow_up:.+)' "data contract sync handling"
  fi
}

require_logging_observability_when_needed() {
  local mode="${1:-all}"
  if logging_changes_exist "${mode}" || kpi_observability_changes_exist "${mode}" || evidence_has '^impact:.*logging'; then
    require_non_placeholder_value "logging_observability" "logging/observability result"
  fi
}

warn_secondary_evidence_when_needed() {
  local mode="${1:-all}"
  if docs_governance_changes_exist "${mode}" || evidence_has '^impact:.*docs_only'; then
    non_placeholder_value "docs_reviewed" || warn "medium-risk docs/workflow change is missing docs_reviewed evidence"
    non_placeholder_value "docs_updated" || warn "medium-risk docs/workflow change is missing docs_updated evidence"
    evidence_has '^changelog:[[:space:]]*(updated|not_applicable:.+)' || warn "medium-risk docs/workflow change is missing changelog handling evidence"
  fi
  if schema_changes_exist "${mode}" && ! docs_db_changed "${mode}" && ! evidence_has '^schema_der:[[:space:]]*(updated|not_applicable:.+|follow_up:.+)'; then
    warn "medium-risk schema-like change is missing schema_der evidence"
  fi
  if has_changed_path_matching "${mode}" '^docs/DATA_CONTRACT\.md$' || evidence_has '^impact:.*contract'; then
    evidence_has '^data_contract_sync:[[:space:]]*(verified:.+|not_applicable:.+|follow_up:.+)' || warn "medium-risk contract-like change is missing data_contract_sync evidence"
  fi
  if logging_changes_exist "${mode}" || kpi_observability_changes_exist "${mode}" || evidence_has '^impact:.*logging'; then
    non_placeholder_value "logging_observability" || warn "medium-risk logging/observability-like change is missing logging_observability evidence"
  fi
}
