#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
if [[ ! -f "${LIB_DIR}/common.sh" ]]; then
  if REPO_ROOT_CANDIDATE="$(git -C "${SCRIPT_DIR}/../.." rev-parse --show-toplevel 2>/dev/null)" \
    && [[ -f "${REPO_ROOT_CANDIDATE}/.codex/lib/common.sh" ]]; then
    LIB_DIR="${REPO_ROOT_CANDIDATE}/.codex/lib"
  elif REPO_ROOT_CANDIDATE="$(git rev-parse --show-toplevel 2>/dev/null)" \
    && [[ -f "${REPO_ROOT_CANDIDATE}/.codex/lib/common.sh" ]]; then
    LIB_DIR="${REPO_ROOT_CANDIDATE}/.codex/lib"
  fi
fi
# shellcheck source=../lib/common.sh
source "${LIB_DIR}/common.sh"
# shellcheck source=../lib/git.sh
source "${LIB_DIR}/git.sh"
# shellcheck source=../lib/classify.sh
source "${LIB_DIR}/classify.sh"
# shellcheck source=../lib/evidence.sh
source "${LIB_DIR}/evidence.sh"
# shellcheck source=../lib/docs.sh
source "${LIB_DIR}/docs.sh"
# shellcheck source=../lib/secrets.sh
source "${LIB_DIR}/secrets.sh"
# shellcheck source=../lib/protected.sh
source "${LIB_DIR}/protected.sh"

info "running pre-commit validation"
require_git_repo
require_required_files
require_workflow_infra_allowed
secret_scan_staged

if meaningful_changes_exist staged; then
  if high_risk_changes_exist staged; then
    require_evidence_file
    require_common_evidence
    require_behavior_tests_when_needed staged
    require_docs_review_when_needed staged
    require_changelog_when_needed staged
    require_schema_der_when_needed staged
    require_contract_sync_when_needed staged
    require_logging_observability_when_needed staged
    require_kpi_registry_when_needed staged
  elif medium_risk_changes_exist staged; then
    require_evidence_file
    require_common_evidence
    warn_secondary_evidence_when_needed staged
  else
    warn_common_evidence
  fi
  validate_touched_doc_headers staged
else
  info "no meaningful staged changes detected"
fi

finish
