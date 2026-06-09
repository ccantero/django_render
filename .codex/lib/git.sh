#!/usr/bin/env bash

require_git_repo() {
  if ! git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    fail "not inside a Git worktree: ${REPO_ROOT}"
  fi
}

changed_files_all() {
  git -C "${REPO_ROOT}" diff --name-only --diff-filter=ACMRTUXB "${CODEX_HOOK_BASE_REF:-HEAD}" 2>/dev/null || true
  git -C "${REPO_ROOT}" ls-files --others --exclude-standard
}

changed_files_staged() {
  git -C "${REPO_ROOT}" diff --cached --name-only --diff-filter=ACMRTUXB
}

changed_files_for_mode() {
  local mode="${1:-all}"
  if [[ "${mode}" == "staged" ]]; then
    changed_files_staged
  else
    changed_files_all
  fi
}

has_changed_path_matching() {
  local mode="$1"
  local pattern="$2"
  local file
  if [[ "${mode}" == "staged" ]]; then
    while IFS= read -r file; do
      [[ "${file}" =~ ${pattern} ]] && return 0
    done < <(changed_files_staged)
  else
    while IFS= read -r file; do
      [[ "${file}" =~ ${pattern} ]] && return 0
    done < <(changed_files_all)
  fi
  return 1
}

is_meaningful_file() {
  local file="$1"
  case "${file}" in
    .pytest_cache/*|__pycache__/*|*.pyc|logs/*|data/*|portfolio.json|portfolio__*.json)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

meaningful_changes_exist() {
  local mode="${1:-all}"
  local file
  if [[ "${mode}" == "staged" ]]; then
    while IFS= read -r file; do
      is_meaningful_file "${file}" && return 0
    done < <(changed_files_staged)
  else
    while IFS= read -r file; do
      is_meaningful_file "${file}" && return 0
    done < <(changed_files_all)
  fi
  return 1
}
