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

info "running manual post-task advisory validation"
require_git_repo
require_required_files

if meaningful_changes_exist all; then
  warn_downstream_requirements all
fi

if ! evidence_exists; then
  warn "workflow evidence file is not present yet: ${EVIDENCE_FILE}"
else
  non_placeholder_value "phases_completed" || warn "workflow evidence is missing phases_completed"
  non_placeholder_value "impact" || warn "workflow evidence is missing impact"
  non_placeholder_value "tests_executed" || warn "workflow evidence is missing tests_executed"
  non_placeholder_value "pending_issues" || warn "workflow evidence is missing pending_issues"
fi

finish
