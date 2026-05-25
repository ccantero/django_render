#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if git -C "${script_dir}/.." rev-parse --show-toplevel >/dev/null 2>&1; then
  repo_root="$(git -C "${script_dir}/.." rev-parse --show-toplevel)"
else
  repo_root="$(cd "${script_dir}/.." >/dev/null && pwd -P)"
fi
hook_dir="${repo_root}/.git/hooks"
target="${hook_dir}/pre-commit"
source_hook="${repo_root}/.codex/hooks/pre-commit.sh"
relative_source="../../.codex/hooks/pre-commit.sh"
managed_marker="# Managed by binanceBot Codex workflow hooks"

info() {
  printf 'INFO: %s\n' "$*"
}

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

if [[ ! -d "${repo_root}/.git" ]]; then
  fail "not a Git worktree: ${repo_root}"
fi

if [[ ! -f "${source_hook}" ]]; then
  fail "source hook not found: ${source_hook}"
fi

mkdir -p "${hook_dir}"

is_managed_file() {
  [[ -f "${target}" ]] && head -n 3 "${target}" | grep -qx "${managed_marker}"
}

if [[ -e "${target}" || -L "${target}" ]]; then
  if [[ -L "${target}" ]]; then
    current_target="$(readlink "${target}")"
    if [[ "${current_target}" == "${relative_source}" || "${current_target}" == "${source_hook}" ]]; then
      info "pre-commit hook already points to Codex workflow hook"
      chmod +x "${source_hook}"
      exit 0
    fi
  elif is_managed_file; then
    info "updating managed pre-commit hook"
  elif [[ "${FORCE:-}" != "1" ]]; then
    fail "refusing to overwrite existing non-managed pre-commit hook; re-run with FORCE=1 after review"
  fi
  rm -f "${target}"
fi

if ln -s "${relative_source}" "${target}" 2>/dev/null; then
  info "installed pre-commit symlink: ${target} -> ${relative_source}"
else
  info "symlink failed; installing managed pre-commit copy"
  {
    sed -n '1p' "${source_hook}"
    printf '%s\n' "${managed_marker}"
    sed '1d' "${source_hook}"
  } > "${target}"
fi

chmod +x "${source_hook}" "${target}"
info "pre-commit hook installation complete"
