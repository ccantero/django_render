#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"
# shellcheck source=../lib/git.sh
source "${SCRIPT_DIR}/../lib/git.sh"
# shellcheck source=../lib/docs.sh
source "${SCRIPT_DIR}/../lib/docs.sh"
# shellcheck source=../lib/evidence.sh
source "${SCRIPT_DIR}/../lib/evidence.sh"

info "running pre-task validation"
require_git_repo
require_required_files

if native_codex_hooks_available; then
  info "native Codex hook config candidate found under .codex"
else
  warn "native Codex hooks were not detected; use repo-local scripts and optional Git hook wrapper"
fi

if evidence_exists; then
  if ! evidence_has '^planner:[[:space:]]*completed$'; then
    warn "workflow evidence exists but planner is not marked completed yet"
  fi
else
  warn "workflow evidence file not found yet: ${EVIDENCE_FILE}"
fi

finish
