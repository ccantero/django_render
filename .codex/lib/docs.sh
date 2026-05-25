#!/usr/bin/env bash

require_required_files() {
  local file
  for file in "${CORE_DOCS[@]}"; do
    if [[ ! -f "${REPO_ROOT}/${file}" ]]; then
      fail "required workflow file is missing: ${file}"
    fi
  done
}

docs_db_changed() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '^docs/db/'
}

changelog_changed() {
  local mode="${1:-all}"
  has_changed_path_matching "${mode}" '^docs/CHANGELOG\.md$'
}

require_docs_review_when_needed() {
  local mode="${1:-all}"
  if app_behavior_changes_exist "${mode}" || contract_changes_exist "${mode}" || schema_changes_exist "${mode}" || logging_changes_exist "${mode}" || docs_governance_changes_exist "${mode}"; then
    local file
    for file in "${DOC_REVIEW_FILES[@]}"; do
      if ! evidence_has "^docs_reviewed:.*${file}"; then
        fail "docs review evidence is missing ${file}"
      fi
    done
    if [[ -f "${REPO_ROOT}/docs/CHANGELOG.md" ]] && ! evidence_has '^docs_reviewed:.*docs/CHANGELOG\.md'; then
      fail "docs review evidence is missing docs/CHANGELOG.md"
    fi
  fi
}

require_changelog_when_needed() {
  local mode="${1:-all}"
  if app_behavior_changes_exist "${mode}" || contract_changes_exist "${mode}" || schema_changes_exist "${mode}" || logging_changes_exist "${mode}" || docs_governance_changes_exist "${mode}"; then
    if ! changelog_changed "${mode}" && ! evidence_has '^changelog:[[:space:]]*(updated|not_applicable:.+)'; then
      fail "meaningful changes require docs/CHANGELOG.md update or explicit changelog not_applicable reason"
    fi
  fi
}

require_schema_der_when_needed() {
  local mode="${1:-all}"
  if schema_changes_exist "${mode}"; then
    if ! docs_db_changed "${mode}" && ! evidence_has '^schema_der:[[:space:]]*(updated|not_applicable:.+|follow_up:.+)'; then
      fail "schema/migration changes require docs/db update or explicit schema_der follow-up evidence"
    fi
  fi
}

validate_version_header() {
  local file="$1"
  local path="${REPO_ROOT}/${file}"
  [[ -f "${path}" ]] || return 0
  if ! sed -n '1,8p' "${path}" | grep -qx -- '---'; then
    fail "versioned doc lacks opening YAML header marker: ${file}"
    return
  fi
  local key
  for key in doc_id doc_version schema_version runtime_min_version last_verified_at source_repo; do
    if ! sed -n '1,12p' "${path}" | grep -Eq "^${key}: .+"; then
      fail "versioned doc header missing ${key}: ${file}"
    fi
  done
  if ! sed -n '1,12p' "${path}" | grep -Eq '^doc_version: [0-9]+\.[0-9]+\.[0-9]+$'; then
    fail "versioned doc header has invalid semver doc_version: ${file}"
  fi
  if ! sed -n '1,12p' "${path}" | grep -Eq '^last_verified_at: [0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
    fail "versioned doc header has invalid last_verified_at date: ${file}"
  fi
}

validate_touched_doc_headers() {
  local mode="${1:-all}"
  local file versioned
  if [[ "${mode}" == "staged" ]]; then
    while IFS= read -r file; do
      for versioned in "${VERSIONED_DOCS[@]}"; do
        [[ "${file}" == "${versioned}" ]] && validate_version_header "${file}"
      done
    done < <(changed_files_staged)
  else
    while IFS= read -r file; do
      for versioned in "${VERSIONED_DOCS[@]}"; do
        [[ "${file}" == "${versioned}" ]] && validate_version_header "${file}"
      done
    done < <(changed_files_all)
  fi
  true
}
