#!/usr/bin/env bash

CODEX_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CODEX_DIR="$(cd "${CODEX_LIB_DIR}/.." >/dev/null && pwd -P)"
if git -C "${CODEX_DIR}" rev-parse --show-toplevel >/dev/null 2>&1; then
  REPO_ROOT="$(git -C "${CODEX_DIR}" rev-parse --show-toplevel)"
else
  REPO_ROOT="$(cd "${CODEX_DIR}/.." >/dev/null && pwd -P)"
fi

DEFAULT_EVIDENCE_FILE="${REPO_ROOT}/.codex/workflow-evidence.md"
EVIDENCE_FILE="${CODEX_WORKFLOW_EVIDENCE:-${DEFAULT_EVIDENCE_FILE}}"

CORE_DOCS=(
  "README.md"
  "PLAN.md"
  "docs/PROJECT_STATE.md"
  "docs/ARCHITECTURE.md"
  "docs/DATA_CONTRACT.md"
)

DOC_REVIEW_FILES=(
  "README.md"
  "PLAN.md"
  "docs/DATA_CONTRACT.md"
  "docs/PROJECT_STATE.md"
  "docs/DESIGN.md"
  "docs/ARCHITECTURE.md"
)

VERSIONED_DOCS=(
  "README.md"
  "PLAN.md"
  "docs/PROJECT_STATE.md"
  "docs/ARCHITECTURE.md"
  "docs/DATA_CONTRACT.md"
  "docs/DESIGN.md"
  "docs/CHANGELOG.md"
)

failures=0
warnings=0

info() {
  printf 'INFO: %s\n' "$*"
}

warn() {
  warnings=$((warnings + 1))
  printf 'WARN: %s\n' "$*" >&2
}

fail() {
  failures=$((failures + 1))
  printf 'FAIL: %s\n' "$*" >&2
}

finish() {
  if (( failures > 0 )); then
    printf 'Result: failed with %d failure(s), %d warning(s).\n' "${failures}" "${warnings}" >&2
    exit 1
  fi
  printf 'Result: passed with %d warning(s).\n' "${warnings}"
}
