#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for script in "${SCRIPT_DIR}"/*.sh; do
  bash -n "${script}"
done

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

mkdir -p "${tmpdir}/repo/docs" "${tmpdir}/repo/.codex/hooks" "${tmpdir}/repo/.codex/lib"
git -C "${tmpdir}/repo" init -q

cp "${SCRIPT_DIR}/../lib/"*.sh "${tmpdir}/repo/.codex/lib/"
cp "${SCRIPT_DIR}/lib.sh" "${tmpdir}/repo/.codex/hooks/lib.sh"
cp "${SCRIPT_DIR}/pre-task.sh" "${tmpdir}/repo/.codex/hooks/pre-task.sh"
cp "${SCRIPT_DIR}/post-edit.sh" "${tmpdir}/repo/.codex/hooks/post-edit.sh"
cp "${SCRIPT_DIR}/post-task.sh" "${tmpdir}/repo/.codex/hooks/post-task.sh"
cp "${SCRIPT_DIR}/pre-commit.sh" "${tmpdir}/repo/.codex/hooks/pre-commit.sh"
cp "${SCRIPT_DIR}/docs-sync.sh" "${tmpdir}/repo/.codex/hooks/docs-sync.sh"
cp "${SCRIPT_DIR}/workflow-evidence.template.md" "${tmpdir}/repo/.codex/hooks/workflow-evidence.template.md"

write_doc() {
  local path="$1"
  local doc_id="$2"
  cat > "${tmpdir}/repo/${path}" <<EOF_DOC
---
doc_id: ${doc_id}
doc_version: 1.0.0
schema_version: unknown
runtime_min_version: unknown
last_verified_at: 2026-05-24
source_repo: test-repo
---

# ${doc_id}
EOF_DOC
}

write_doc "README.md" "readme"
write_doc "PLAN.md" "plan"
write_doc "docs/PROJECT_STATE.md" "project-state"
write_doc "docs/ARCHITECTURE.md" "architecture"
write_doc "docs/DATA_CONTRACT.md" "data-contract"
write_doc "docs/DESIGN.md" "design"
write_doc "docs/CHANGELOG.md" "changelog"

write_valid_evidence() {
  cat > "${tmpdir}/repo/.codex/hooks/workflow-evidence.md" <<'EOF_EVIDENCE'
planner: completed
planner_evidence: inspected required docs and scoped hook-only governance changes
implementer: completed
implementer_evidence: changed only repo-local hook files and docs
tester: completed
tester_evidence: ran hook syntax checks and self-check scenarios
documentator: completed
documentator_evidence: reviewed required docs and updated hook README/changelog
impact: docs_only, operations
tests_created: not_applicable: governance-only hook revision
failing_test_proof: not_applicable: no application behavior changed
tests_executed: bash -n .codex/hooks/*.sh; .codex/hooks/self-check.sh
code_changes: repo-local hook scripts only
docs_updated: .codex/hooks/README.md
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md
changelog: updated
logging_observability: no runtime logging changes
schema_der: not_applicable: no schema changes
data_contract_sync: follow_up: DASHBOARD_DATA_CONTRACT was not configured in self-check
pending_issues: none
EOF_EVIDENCE
}

git -C "${tmpdir}/repo" add .
git -C "${tmpdir}/repo" -c user.name=HookSelfCheck -c user.email=hook-self-check@example.invalid commit -q -m "baseline" >/dev/null
ln -s ../../.codex/hooks/pre-commit.sh "${tmpdir}/repo/.git/hooks/pre-commit"

cp "${tmpdir}/repo/.codex/hooks/workflow-evidence.template.md" "${tmpdir}/repo/.codex/hooks/workflow-evidence.md"
if "${tmpdir}/repo/.codex/hooks/post-task.sh" >/dev/null 2>&1; then
  printf 'placeholder workflow evidence unexpectedly passed\n' >&2
  exit 1
fi

write_valid_evidence
"${tmpdir}/repo/.codex/hooks/pre-task.sh" >/dev/null
"${tmpdir}/repo/.codex/hooks/post-task.sh" >/dev/null
"${tmpdir}/repo/.codex/hooks/docs-sync.sh" all >/dev/null
"${tmpdir}/repo/.git/hooks/pre-commit" >/dev/null

printf '\ncontract self-check change\n' >> "${tmpdir}/repo/docs/DATA_CONTRACT.md"
dashboard_output="$("${tmpdir}/repo/.codex/hooks/docs-sync.sh" all 2>&1)"
if ! grep -q 'DASHBOARD_DATA_CONTRACT is not set' <<<"${dashboard_output}"; then
  printf 'missing DASHBOARD_DATA_CONTRACT warning was not emitted\n' >&2
  exit 1
fi

mkdir -p "${tmpdir}/repo/apps/orders" "${tmpdir}/repo/tests"
printf 'def view(request):\n    return None\n' > "${tmpdir}/repo/apps/orders/views.py"
post_edit_output="$("${tmpdir}/repo/.codex/hooks/post-edit.sh" 2>&1)"
if ! grep -q 'likely impact: .*behavior' <<<"${post_edit_output}"; then
  printf 'Django path behavior impact was not detected by post-edit\n' >&2
  exit 1
fi

cp "${tmpdir}/repo/.codex/hooks/workflow-evidence.template.md" "${tmpdir}/repo/.codex/hooks/workflow-evidence.md"
git -C "${tmpdir}/repo" add apps/orders/views.py
if "${tmpdir}/repo/.codex/hooks/pre-commit.sh" >/dev/null 2>&1; then
  printf 'pre-commit unexpectedly accepted placeholder workflow evidence\n' >&2
  exit 1
fi

cat > "${tmpdir}/repo/.codex/hooks/workflow-evidence.md" <<'EOF_BEHAVIOR'
planner: completed
planner_evidence: planned a temporary Django path detection check
implementer: completed
implementer_evidence: added a temporary Django view in the self-check repo
tester: completed
tester_evidence: validated pre-commit behavior detection in the self-check repo
documentator: completed
documentator_evidence: self-check scenario needs no persistent docs in temp repo
impact: behavior
tests_created: tests/test_orders_view.py covers the temporary view behavior
failing_test_proof: pytest failed before implementation in the temporary scenario
tests_executed: pytest tests/test_orders_view.py
code_changes: apps/orders/views.py
docs_updated: not_applicable: temporary self-check repo
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md
changelog: not_applicable: temporary self-check repo
logging_observability: no runtime logging changes
schema_der: not_applicable: no schema changes
pending_issues: none
EOF_BEHAVIOR
"${tmpdir}/repo/.codex/hooks/pre-commit.sh" >/dev/null

printf '\nprotected change\n' >> "${tmpdir}/repo/AGENTS.md"
git -C "${tmpdir}/repo" add AGENTS.md
protected_output="$("${tmpdir}/repo/.codex/hooks/pre-commit.sh" 2>&1 || true)"
if ! grep -q 'protected workflow infrastructure changes are staged' <<<"${protected_output}"; then
  printf 'pre-commit did not block protected workflow files by default\n' >&2
  exit 1
fi
if ! grep -q 'ALLOW_WORKFLOW_INFRA_CHANGE=1 git commit' <<<"${protected_output}"; then
  printf 'protected workflow block did not explain how to proceed\n' >&2
  exit 1
fi
ALLOW_WORKFLOW_INFRA_CHANGE=1 "${tmpdir}/repo/.codex/hooks/pre-commit.sh" >/dev/null 2>&1 || {
  printf 'pre-commit did not allow protected workflow files with ALLOW_WORKFLOW_INFRA_CHANGE=1\n' >&2
  exit 1
}

cp "${tmpdir}/repo/.codex/hooks/workflow-evidence.template.md" "${tmpdir}/repo/.codex/hooks/workflow-evidence.md"
if ALLOW_WORKFLOW_INFRA_CHANGE=1 "${tmpdir}/repo/.codex/hooks/pre-commit.sh" >/dev/null 2>&1; then
  printf 'ALLOW_WORKFLOW_INFRA_CHANGE bypassed non-protected workflow validations\n' >&2
  exit 1
fi

printf 'self-check passed\n'
