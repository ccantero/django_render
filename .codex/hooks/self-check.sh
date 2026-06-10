#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for script in "${SCRIPT_DIR}"/*.sh; do
  bash -n "${script}"
done

validate_workflow_references() {
  local repo="$1"
  local ref path file name

  [[ -f "${repo}/AGENTS.md" ]] || {
    printf 'missing AGENTS.md for workflow reference validation\n' >&2
    return 1
  }
  [[ -d "${repo}/.codex/skills" ]] || {
    printf 'missing .codex/skills for workflow reference validation\n' >&2
    return 1
  }

  while IFS= read -r ref; do
    path="${repo}/${ref}"
    if [[ ! -f "${path}" ]]; then
      printf 'broken workflow reference: %s\n' "${ref}" >&2
      return 1
    fi
  done < <(grep -RhoE '\.codex/skills/[A-Za-z0-9_.-]+\.md' "${repo}/AGENTS.md" "${repo}/.codex/skills" 2>/dev/null | sort -u)

  while IFS= read -r file; do
    name="$(basename "${file}")"
    if ! grep -RqsF ".codex/skills/${name}" "${repo}/AGENTS.md"; then
      printf 'unreferenced skill: .codex/skills/%s\n' "${name}" >&2
      return 1
    fi
  done < <(find "${repo}/.codex/skills" -maxdepth 1 -type f -name '*.md' | sort)

  while IFS= read -r ref; do
    path="${repo}/${ref}"
    if [[ ! -f "${path}" ]]; then
      printf 'declared hook does not exist: %s\n' "${ref}" >&2
      return 1
    fi
  done < <(grep -rhoE '\.codex/hooks/[A-Za-z0-9_.-]+\.sh' "${repo}/.codex/hooks/README.md" 2>/dev/null | sort -u)
}

write_doc() {
  local repo="$1"
  local path="$2"
  local doc_id="$3"
  cat > "${repo}/${path}" <<EOF_DOC
---
doc_id: ${doc_id}
doc_version: 1.0.0
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-05-29
source_repo: test-repo
---

# ${doc_id}
EOF_DOC
}

write_core_evidence() {
  local repo="$1"
  cat > "${repo}/.codex/workflow-evidence.md" <<'EOF_EVIDENCE'
phases_completed: planner, implementer, tester, documentator
impact: docs_only, operations
tests_executed: .codex/hooks/self-check.sh
pending_issues: none
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md
docs_updated: .codex/hooks/README.md
changelog: not_applicable: temporary self-check repo
EOF_EVIDENCE
}

validate_workflow_references "${SCRIPT_DIR}/../.."

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

repo="${tmpdir}/repo"
mkdir -p "${repo}/docs" "${repo}/.codex/hooks" "${repo}/.codex/lib" "${repo}/.codex/skills"
git -C "${repo}" init -q

cp "${SCRIPT_DIR}/../lib/"*.sh "${repo}/.codex/lib/"
cp "${SCRIPT_DIR}/post-task.sh" "${repo}/.codex/hooks/post-task.sh"
cp "${SCRIPT_DIR}/pre-commit.sh" "${repo}/.codex/hooks/pre-commit.sh"
cp "${SCRIPT_DIR}/docs-sync.sh" "${repo}/.codex/hooks/docs-sync.sh"
cp "${SCRIPT_DIR}/self-check.sh" "${repo}/.codex/hooks/self-check.sh"
cp "${SCRIPT_DIR}/workflow-evidence.template.md" "${repo}/.codex/hooks/workflow-evidence.template.md"
cp "${SCRIPT_DIR}/../skills/"*.md "${repo}/.codex/skills/"
cp "${SCRIPT_DIR}/../../AGENTS.md" "${repo}/AGENTS.md"
cp "${SCRIPT_DIR}/README.md" "${repo}/.codex/hooks/README.md"
cat > "${repo}/.gitignore" <<'EOF_GITIGNORE'
.codex/workflow-evidence.md
EOF_GITIGNORE

validate_workflow_references "${repo}"

printf '# Extra skill\n' > "${repo}/.codex/skills/unreferenced.md"
if validate_workflow_references "${repo}" >/dev/null 2>&1; then
  printf 'workflow reference validation missed an unreferenced skill\n' >&2
  exit 1
fi
rm "${repo}/.codex/skills/unreferenced.md"

printf '\nBroken skill ref: .codex/skills/missing.md\n' >> "${repo}/AGENTS.md"
if validate_workflow_references "${repo}" >/dev/null 2>&1; then
  printf 'workflow reference validation missed a missing skill reference\n' >&2
  exit 1
fi
cp "${SCRIPT_DIR}/../../AGENTS.md" "${repo}/AGENTS.md"

printf '\nBroken hook ref: .codex/hooks/missing-hook.sh\n' >> "${repo}/.codex/hooks/README.md"
if validate_workflow_references "${repo}" >/dev/null 2>&1; then
  printf 'workflow reference validation missed a missing hook reference\n' >&2
  exit 1
fi
cp "${SCRIPT_DIR}/README.md" "${repo}/.codex/hooks/README.md"

write_doc "${repo}" "README.md" "readme"
write_doc "${repo}" "PLAN.md" "plan"
write_doc "${repo}" "docs/PROJECT_STATE.md" "project-state"
write_doc "${repo}" "docs/ARCHITECTURE.md" "architecture"
write_doc "${repo}" "docs/DATA_CONTRACT.md" "data-contract"
write_doc "${repo}" "docs/DESIGN.md" "design"
write_doc "${repo}" "docs/CHANGELOG.md" "changelog"
write_core_evidence "${repo}"

git -C "${repo}" add .
git -C "${repo}" -c user.name=HookSelfCheck -c user.email=hook-self-check@example.invalid commit -q -m "baseline" >/dev/null

mkdir -p "${repo}/apps/orders"
printf 'def view(request):\n    return None\n' > "${repo}/apps/orders/views.py"
git -C "${repo}" add apps/orders/views.py
if "${repo}/.codex/hooks/pre-commit.sh" >/dev/null 2>&1; then
  printf 'pre-commit unexpectedly accepted high-risk behavior without workflow evidence\n' >&2
  exit 1
fi

cat > "${repo}/.codex/workflow-evidence.md" <<'EOF_BEHAVIOR_MISSING'
phases_completed: planner, implementer, tester, documentator
impact: behavior
tests_executed: pytest tests/test_orders_view.py
pending_issues: none
EOF_BEHAVIOR_MISSING
if "${repo}/.codex/hooks/pre-commit.sh" >/dev/null 2>&1; then
  printf 'pre-commit unexpectedly accepted behavior change without behavior evidence\n' >&2
  exit 1
fi

cat >> "${repo}/.codex/workflow-evidence.md" <<'EOF_BEHAVIOR'
tests_created: tests/test_orders_view.py covers the temporary view behavior
failing_test_proof: pytest failed before implementation in the temporary scenario
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md
docs_updated: not_applicable: temporary behavior self-check does not persist project docs
changelog: not_applicable: temporary behavior self-check repo
EOF_BEHAVIOR
"${repo}/.codex/hooks/pre-commit.sh" >/dev/null
git -C "${repo}" -c user.name=HookSelfCheck -c user.email=hook-self-check@example.invalid commit -q -m "behavior scenario" >/dev/null

rm -f "${repo}/.codex/workflow-evidence.md"
mkdir -p "${repo}/docs/notes"
printf '# Typo cleanup\n' > "${repo}/docs/notes/typo-cleanup.md"
git -C "${repo}" add docs/notes/typo-cleanup.md
low_risk_output="$("${repo}/.codex/hooks/pre-commit.sh" 2>&1)"
if ! grep -q 'low-risk staged changes without workflow evidence' <<<"${low_risk_output}"; then
  printf 'pre-commit did not warn for missing low-risk workflow evidence\n' >&2
  exit 1
fi
git -C "${repo}" -c user.name=HookSelfCheck -c user.email=hook-self-check@example.invalid commit -q -m "low risk docs scenario" >/dev/null

mkdir -p "${repo}/src/scripts"
printf 'def main():\n    return None\n' > "${repo}/src/scripts/analyze_new_metric.py"
git -C "${repo}" add src/scripts/analyze_new_metric.py
cat > "${repo}/.codex/workflow-evidence.md" <<'EOF_KPI_MISSING'
phases_completed: planner, implementer, tester, documentator
impact: behavior, logging, operations
tests_executed: pytest tests/test_analyze_new_metric.py
pending_issues: none
tests_created: tests/test_analyze_new_metric.py covers the temporary analytics behavior
failing_test_proof: pytest failed before implementation in the temporary analytics scenario
EOF_KPI_MISSING
if "${repo}/.codex/hooks/pre-commit.sh" >/dev/null 2>&1; then
  printf 'pre-commit unexpectedly accepted analytics changes without KPI/logging evidence\n' >&2
  exit 1
fi

cat >> "${repo}/.codex/workflow-evidence.md" <<'EOF_KPI'
logging_observability: temporary analytics output only
kpi_registry_reviewed: not-needed
kpi_registry_updated: not-needed
kpi_registry_sync_checked: not-available
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md
docs_updated: not_applicable: temporary KPI self-check does not persist project docs
changelog: not_applicable: temporary KPI self-check repo
EOF_KPI
"${repo}/.codex/hooks/pre-commit.sh" >/dev/null
git -C "${repo}" -c user.name=HookSelfCheck -c user.email=hook-self-check@example.invalid commit -q -m "kpi scenario" >/dev/null

printf '\ncontract self-check change\n' >> "${repo}/docs/DATA_CONTRACT.md"
git -C "${repo}" add docs/DATA_CONTRACT.md
cat > "${repo}/.codex/workflow-evidence.md" <<'EOF_CONTRACT_MISSING'
phases_completed: planner, implementer, tester, documentator
impact: contract
tests_executed: docs-sync
pending_issues: none
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md
docs_updated: docs/DATA_CONTRACT.md
changelog: updated
EOF_CONTRACT_MISSING
if "${repo}/.codex/hooks/pre-commit.sh" >/dev/null 2>&1; then
  printf 'pre-commit unexpectedly accepted contract change without sync evidence\n' >&2
  exit 1
fi

cat >> "${repo}/.codex/workflow-evidence.md" <<'EOF_CONTRACT'
data_contract_sync: follow_up: DASHBOARD_DATA_CONTRACT was not configured in self-check
EOF_CONTRACT
"${repo}/.codex/hooks/pre-commit.sh" >/dev/null
git -C "${repo}" -c user.name=HookSelfCheck -c user.email=hook-self-check@example.invalid commit -q -m "contract scenario" >/dev/null

printf '\nsecond contract self-check change\n' >> "${repo}/docs/DATA_CONTRACT.md"
dashboard_output="$("${repo}/.codex/hooks/docs-sync.sh" all 2>&1)"
if ! grep -q 'DASHBOARD_DATA_CONTRACT is not set' <<<"${dashboard_output}"; then
  printf 'missing DASHBOARD_DATA_CONTRACT warning was not emitted\n' >&2
  exit 1
fi

printf '\nprotected change\n' >> "${repo}/AGENTS.md"
git -C "${repo}" add AGENTS.md
protected_output="$("${repo}/.codex/hooks/pre-commit.sh" 2>&1 || true)"
if ! grep -q 'protected workflow infrastructure changes are staged' <<<"${protected_output}"; then
  printf 'pre-commit did not block protected workflow files by default\n' >&2
  exit 1
fi
if ! grep -q 'ALLOW_WORKFLOW_INFRA_CHANGE=1 git commit' <<<"${protected_output}"; then
  printf 'protected workflow block did not explain how to proceed\n' >&2
  exit 1
fi
ALLOW_WORKFLOW_INFRA_CHANGE=1 "${repo}/.codex/hooks/pre-commit.sh" >/dev/null 2>&1 || {
  printf 'pre-commit did not allow protected workflow files with ALLOW_WORKFLOW_INFRA_CHANGE=1\n' >&2
  exit 1
}

cp "${repo}/.codex/hooks/workflow-evidence.template.md" "${repo}/.codex/workflow-evidence.md"
if ALLOW_WORKFLOW_INFRA_CHANGE=1 "${repo}/.codex/hooks/pre-commit.sh" >/dev/null 2>&1; then
  printf 'ALLOW_WORKFLOW_INFRA_CHANGE bypassed non-protected workflow validations\n' >&2
  exit 1
fi

"${repo}/.codex/hooks/post-task.sh" >/dev/null 2>&1

printf 'self-check passed\n'
