#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"
# shellcheck source=../lib/git.sh
source "${SCRIPT_DIR}/../lib/git.sh"
# shellcheck source=../lib/classify.sh
source "${SCRIPT_DIR}/../lib/classify.sh"
# shellcheck source=../lib/evidence.sh
source "${SCRIPT_DIR}/../lib/evidence.sh"
# shellcheck source=../lib/docs.sh
source "${SCRIPT_DIR}/../lib/docs.sh"

mode="${1:-all}"
if [[ "${mode}" != "all" && "${mode}" != "staged" ]]; then
  fail "usage: docs-sync.sh [all|staged]"
  finish
fi

info "running docs-sync validation (${mode})"
require_git_repo
require_required_files
validate_touched_doc_headers "${mode}"
require_docs_review_when_needed "${mode}"
require_changelog_when_needed "${mode}"
require_schema_der_when_needed "${mode}"
require_kpi_registry_when_needed "${mode}"

if has_changed_path_matching "${mode}" '^docs/DATA_CONTRACT\.md$'; then
  if [[ -z "${DASHBOARD_DATA_CONTRACT:-}" ]]; then
    warn "DASHBOARD_DATA_CONTRACT is not set; paired dashboard contract validation was not run"
    if ! evidence_has '^data_contract_sync:[[:space:]]*(not_applicable:.+|follow_up:.+|verified:.+)'; then
      warn "record data_contract_sync follow-up evidence before final reporting"
    fi
  elif [[ -f "${DASHBOARD_DATA_CONTRACT}" ]]; then
    if cmp -s "${REPO_ROOT}/docs/DATA_CONTRACT.md" "${DASHBOARD_DATA_CONTRACT}"; then
      info "paired dashboard DATA_CONTRACT.md is synchronized"
    elif evidence_has '^data_contract_sync:[[:space:]]*(verified|follow_up:.+)'; then
      warn "paired dashboard DATA_CONTRACT.md differs; workflow evidence records sync handling"
    else
      fail "docs/DATA_CONTRACT.md changed but paired dashboard contract differs: ${DASHBOARD_DATA_CONTRACT}"
    fi
  elif ! evidence_has '^data_contract_sync:[[:space:]]*(not_applicable:.+|follow_up:.+)'; then
    warn "DASHBOARD_DATA_CONTRACT does not point to a file: ${DASHBOARD_DATA_CONTRACT}"
    warn "record a data_contract_sync follow-up before final reporting"
  fi
fi

if has_changed_path_matching "${mode}" '^docs/KPI_REGISTRY\.md$'; then
  if [[ -z "${DASHBOARD_KPI_REGISTRY:-}" ]]; then
    warn "DASHBOARD_KPI_REGISTRY is not set; paired dashboard KPI registry validation was not run"
    if ! evidence_has '^kpi_registry_sync_checked:[[:space:]]*(not-available|no|yes)'; then
      warn "record kpi_registry_sync_checked evidence before final reporting"
    fi
  elif [[ -f "${DASHBOARD_KPI_REGISTRY}" ]]; then
    if cmp -s "${REPO_ROOT}/docs/KPI_REGISTRY.md" "${DASHBOARD_KPI_REGISTRY}"; then
      info "paired dashboard KPI_REGISTRY.md is synchronized"
    elif evidence_has '^kpi_registry_sync_checked:[[:space:]]*(no|not-available)'; then
      warn "paired dashboard KPI_REGISTRY.md differs; workflow evidence records sync handling"
    else
      fail "docs/KPI_REGISTRY.md changed but paired dashboard registry differs: ${DASHBOARD_KPI_REGISTRY}"
    fi
  elif ! evidence_has '^kpi_registry_sync_checked:[[:space:]]*(no|not-available)'; then
    warn "DASHBOARD_KPI_REGISTRY does not point to a file: ${DASHBOARD_KPI_REGISTRY}"
    warn "record a kpi_registry_sync_checked follow-up before final reporting"
  fi
fi

finish
