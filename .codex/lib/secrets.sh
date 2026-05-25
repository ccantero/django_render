#!/usr/bin/env bash

secret_scan_staged() {
  local file
  while IFS= read -r file; do
    [[ -f "${REPO_ROOT}/${file}" ]] || continue
    case "${file}" in
      *.patch|*.txt|logs/*|data/*)
        continue
        ;;
      .codex/lib/secrets.sh)
        continue
        ;;
    esac
    if git -C "${REPO_ROOT}" show ":${file}" 2>/dev/null | grep -Eiq 'postgres://[^[:space:]]+:[^[:space:]@]+@|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY'; then
      fail "possible secret detected in staged file: ${file}"
    elif git -C "${REPO_ROOT}" show ":${file}" 2>/dev/null | grep -Eiq '(^|[^[:alnum:]_])(api[_-]?secret|secret[_-]?key|private[_-]?key|binance[_-]?secret|telegram[_-]?bot[_-]?token|database_url)[[:space:]]*=[[:space:]]*["'\''][^"'\''<>{}[:space:]]{8,}'; then
      fail "possible secret detected in staged file: ${file}"
    elif git -C "${REPO_ROOT}" show ":${file}" 2>/dev/null | grep -Eiq '["'\''](api[_-]?secret|secret[_-]?key|private[_-]?key|binance[_-]?secret|telegram[_-]?bot[_-]?token|database_url)["'\''][[:space:]]*:[[:space:]]*["'\''][^"'\''<>{}[:space:]]{8,}'; then
      fail "possible secret detected in staged file: ${file}"
    fi
  done < <(changed_files_staged)
  true
}
