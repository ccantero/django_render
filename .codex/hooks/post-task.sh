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

info "running post-task validation"
require_git_repo
require_required_files
require_evidence_file

if evidence_exists; then
  require_workflow_order
  require_role_evidence
  require_evidence_marker '^impact:[[:space:]]*(none|docs_only|behavior|contract|schema|logging|operations)(,[[:space:]]*(docs_only|behavior|contract|schema|logging|operations))*$' "impact classification"
  require_non_placeholder_value "tests_executed" "tests executed record"
  require_non_placeholder_value "code_changes" "code changes summary"
  require_non_placeholder_value "docs_updated" "docs update summary"
  require_non_placeholder_value "logging_observability" "logging/observability result"
  require_non_placeholder_value "schema_der" "schema/DER result"
  require_non_placeholder_value "pending_issues" "pending issues result"
  require_behavior_tests_when_needed all
  require_docs_review_when_needed all
  require_changelog_when_needed all
  require_schema_der_when_needed all
  validate_touched_doc_headers all
fi

finish
