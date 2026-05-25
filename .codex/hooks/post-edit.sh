#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"
# shellcheck source=../lib/git.sh
source "${SCRIPT_DIR}/../lib/git.sh"
# shellcheck source=../lib/classify.sh
source "${SCRIPT_DIR}/../lib/classify.sh"
# shellcheck source=../lib/docs.sh
source "${SCRIPT_DIR}/../lib/docs.sh"
# shellcheck source=../lib/evidence.sh
source "${SCRIPT_DIR}/../lib/evidence.sh"

info "running post-edit validation"
require_git_repo
require_required_files

if meaningful_changes_exist all; then
  warn_downstream_requirements all
  if evidence_exists; then
    if evidence_has '^planner:[[:space:]]*completed$'; then
      info "planner completion evidence is present"
    else
      warn "planner completion evidence is not present yet"
    fi
  else
    warn "workflow evidence file is not present yet: ${EVIDENCE_FILE}"
  fi
else
  info "no meaningful worktree changes detected"
fi

finish
