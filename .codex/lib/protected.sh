#!/usr/bin/env bash

is_protected_workflow_file() {
  local file="$1"
  case "${file}" in
    AGENTS.md|.codex/README.md|.codex/workflow-evidence.template.md)
      return 0
      ;;
    .codex/hooks/*|.codex/lib/*|.codex/templates/*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

protected_staged_files() {
  local file
  while IFS= read -r file; do
    if is_protected_workflow_file "${file}"; then
      printf '%s\n' "${file}"
    fi
  done < <(changed_files_staged)
}

require_workflow_infra_allowed() {
  local protected_files
  protected_files="$(protected_staged_files)"
  [[ -n "${protected_files}" ]] || return 0
  if [[ "${ALLOW_WORKFLOW_INFRA_CHANGE:-}" == "1" ]]; then
    warn "protected workflow infrastructure changes allowed by ALLOW_WORKFLOW_INFRA_CHANGE=1"
    return 0
  fi

  fail "protected workflow infrastructure changes are staged:"
  while IFS= read -r file; do
    [[ -n "${file}" ]] && fail "  ${file}"
  done <<<"${protected_files}"
  fail "Review the protected workflow diff manually, then commit with: ALLOW_WORKFLOW_INFRA_CHANGE=1 git commit"
}
