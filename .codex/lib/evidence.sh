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

line_number_for_marker() {
  local marker="$1"
  if ! evidence_exists; then
    printf '0\n'
    return
  fi
  grep -En "${marker}" "${EVIDENCE_FILE}" | head -n 1 | cut -d: -f1 || printf '0\n'
}

require_workflow_order() {
  local planner implementer tester documentator
  planner="$(line_number_for_marker '^planner:[[:space:]]*completed$')"
  implementer="$(line_number_for_marker '^implementer:[[:space:]]*completed$')"
  tester="$(line_number_for_marker '^tester:[[:space:]]*completed$')"
  documentator="$(line_number_for_marker '^documentator:[[:space:]]*completed$')"

  if [[ "${planner}" == "0" || "${implementer}" == "0" || "${tester}" == "0" || "${documentator}" == "0" ]]; then
    fail "workflow evidence must include planner, implementer, tester, and documentator completed markers"
    return
  fi

  if (( planner >= implementer || implementer >= tester || tester >= documentator )); then
    fail "workflow evidence markers are not in required order: planner -> implementer -> tester -> documentator"
  fi
}

non_placeholder_value() {
  local key="$1"
  local value
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

require_role_evidence() {
  local role
  for role in planner implementer tester documentator; do
    require_evidence_marker "^${role}:[[:space:]]*completed$" "${role} completed marker"
    require_non_placeholder_value "${role}_evidence" "${role} evidence"
  done
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
