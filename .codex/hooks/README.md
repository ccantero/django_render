# Codex Workflow Hooks

Repo-local hooks for the AGENTS.md single-agent workflow:

1. planner
2. implementer
3. tester
4. documentator

These scripts enforce deterministic checks that can be verified from files,
Git state, and an explicit workflow evidence file. They validate phase
evidence for one agent; they do not spawn, require, or coordinate sub-agents.
They are guardrails for evidence and consistency, not a substitute for human
review.

## Scripts

- `pre-commit.sh`: main enforced safety gate for staged changes. It classifies
  staged risk, validates evidence according to that risk, validates touched
  core-doc headers, blocks protected workflow infrastructure without explicit
  approval, and scans obvious staged secret patterns.
- `docs-sync.sh`: validates docs governance for all or staged changes and,
  when `DASHBOARD_DATA_CONTRACT` is set, checks the paired dashboard
  `docs/DATA_CONTRACT.md` synchronization when this repo's contract changes.
  When `DASHBOARD_KPI_REGISTRY` is set, it also checks the paired dashboard
  KPI registry copy when `docs/KPI_REGISTRY.md` changes.
- `post-task.sh`: manual advisory check. It reports likely downstream
  requirements and warns when common workflow evidence is missing, but the
  enforced gate is `pre-commit.sh`.
- `self-check.sh`: maintainer check for hook/lib changes. It syntax-checks
  hook scripts and exercises pre-commit/docs-sync behavior in a temporary Git
  repository.

All scripts are safe and idempotent. They do not mutate application files,
install dependencies, call external services, or commit changes.

## Libraries

Shared hook logic lives under `.codex/lib/`:

- `common.sh`: repository paths, shared constants, and status helpers.
- `git.sh`: Git status and changed-file helpers.
- `classify.sh`: impact classification and advisory warnings.
- `evidence.sh`: workflow evidence validation.
- `docs.sh`: required-doc, changelog, schema/DER, and version-header checks.
- `secrets.sh`: lightweight staged secret scan.
- `protected.sh`: protected workflow infrastructure path guard.

## Workflow Evidence

The validators look for a local, unversioned evidence file by default:

```bash
.codex/workflow-evidence.md
```

Use another path with:

```bash
CODEX_WORKFLOW_EVIDENCE=/tmp/current-codex-task.md .codex/hooks/pre-commit.sh
```

Start from:

```bash
cp .codex/hooks/workflow-evidence.template.md .codex/workflow-evidence.md
```

The default evidence file is intentionally ignored by Git. This keeps daily
task evidence out of protected workflow infrastructure while preserving the
hook's ability to validate high-risk commits. Use `CODEX_WORKFLOW_EVIDENCE`
for disposable task files under `/tmp` or for a reviewed evidence file in a
different location.

The template is intentionally incomplete. The common evidence fields are:

- `phases_completed`
- `impact`
- `tests_executed`
- `pending_issues`

Extra evidence is conditional:

- behavior impact: `tests_created`, `failing_test_proof`
- docs/workflow impact: `docs_reviewed`, `docs_updated`, `changelog`
- schema impact: `schema_der`
- contract impact: `data_contract_sync`
- KPI/observability/logging impact: `logging_observability`,
  `kpi_registry_reviewed`, `kpi_registry_updated`,
  `kpi_registry_sync_checked`

## Risk-Tier Evidence

`pre-commit.sh` classifies staged changes before validating workflow evidence.

High risk blocks without complete evidence. Examples include trading behavior,
BUY/SELL execution paths, FIFO/accounting, `position_lots`, reconciliation,
database schema artifacts, `docs/DATA_CONTRACT.md`, logging/operator output,
healthcheck payloads, KPIs, observability, dashboard/read-model contract
semantics, and application behavior changes. Required evidence:

```text
phases_completed: planner, implementer, tester, documentator
impact: behavior
tests_executed: pytest tests/unit/test_sell_service.py -q
pending_issues: none
tests_created: tests/unit/test_sell_service.py covers the changed SELL behavior
failing_test_proof: pytest failed before the fix for the expected reason
docs_reviewed: README.md, PLAN.md, docs/DATA_CONTRACT.md, docs/PROJECT_STATE.md, docs/DESIGN.md, docs/ARCHITECTURE.md, docs/CHANGELOG.md
docs_updated: docs/CHANGELOG.md
changelog: updated
data_contract_sync: not_applicable: no data contract semantics changed
logging_observability: not_applicable: no runtime/operator output changed
```

Medium risk requires the common evidence fields and warns for secondary fields
that are not clearly applicable. Examples include operational docs, env
examples, relevant tests, protected hook/docs maintenance, and read-only
operator-facing scripts that do not change shared semantics. Example:

```text
phases_completed: planner, implementer, tester, documentator
impact: docs_only
tests_executed: bash -n .codex/hooks/*.sh
pending_issues: none
docs_reviewed: AGENTS.md, .codex/hooks/README.md
docs_updated: .codex/hooks/README.md
changelog: not_applicable: workflow documentation only
```

Low risk does not block solely because evidence is missing. The hook still
checks required project files, protected workflow approval, staged secrets,
and touched versioned-doc headers. Examples include non-operational docs-only
cleanup, typo fixes, tests-only changes without behavior, and small internal
cleanup without observable behavior. Missing low-risk evidence emits a warning
like:

```text
WARN: low-risk staged changes without workflow evidence: .codex/workflow-evidence.md
```

For paired dashboard contract validation, set:

```bash
DASHBOARD_DATA_CONTRACT=/path/to/dashboard/docs/DATA_CONTRACT.md
```

If that variable is unset and `docs/DATA_CONTRACT.md` changed, `docs-sync.sh`
warns and asks for follow-up evidence instead of embedding a machine-local
path.

For paired dashboard KPI registry validation, set:

```bash
DASHBOARD_KPI_REGISTRY=/path/to/dashboard/docs/KPI_REGISTRY.md
```

If that variable is unset and `docs/KPI_REGISTRY.md` changed, `docs-sync.sh`
warns and asks for KPI registry sync evidence rather than assuming the
dashboard copy is unavailable or current.

## Manual Use

Recommended local sequence:

```bash
.codex/hooks/post-task.sh
```

Before committing:

```bash
git add <files>
.codex/hooks/pre-commit.sh
```

Self-check:

```bash
.codex/hooks/self-check.sh
```

`post-task.sh` is intentionally advisory. Use `pre-commit.sh` for the strict
gate.

## Git Integration

Install the local Git pre-commit hook with:

```bash
scripts/install-hooks.sh
```

`.git/hooks/` is developer-local Git metadata and is not committed. The
installer creates `.git/hooks/pre-commit` as a symlink to:

```bash
../../.codex/hooks/pre-commit.sh
```

If symlinks are not practical, the installer falls back to a managed copy. It
is safe and idempotent. It refuses to overwrite an existing non-managed
pre-commit hook unless `FORCE=1` is set after review:

```bash
FORCE=1 scripts/install-hooks.sh
```

This repository does not auto-install Git hooks because that would mutate
developer-local metadata.

## Protected Infrastructure

The pre-commit hook blocks staged changes to protected workflow infrastructure
unless `ALLOW_WORKFLOW_INFRA_CHANGE=1` is set:

- `AGENTS.md`
- `.codex/hooks/**`
- `.codex/lib/**`
- `.codex/templates/**`
- `.codex/README.md`
- `.codex/workflow-evidence.template.md`

When protected files are staged, review the diff manually first. Then commit
with:

```bash
ALLOW_WORKFLOW_INFRA_CHANGE=1 git commit
```

That variable only bypasses the protected-file block. Secret scanning, risk
classification, evidence checks for the staged risk level, docs checks,
schema/DER checks, and version-header checks still run.

## Legacy Sub-Agent Prompts

The previous sub-agent prompts are archived under `.codex/legacy/subagents/`
for review only. They are not active workflow inputs and should not be wired
back into hooks or task routing.

## Secret Scan

`pre-commit.sh` includes a small regex-based staged-content scan for obvious
secrets such as private keys, database URLs, API secrets, and Telegram bot
tokens. This is a basic guard only. It does not replace dedicated tools such
as `gitleaks` or `detect-secrets`; those dependencies are not installed or
required by these hooks.

## Enforcement Map

- Required files exist: enforced by validators.
- Single-agent phase completion: enforced by `phases_completed` in
  `pre-commit.sh`.
- Behavior changes require tests: partially enforced by changed-path detection,
  touched tests, and conditional evidence fields.
- Behavior/contract/schema/logging/docs-governance changes require docs review:
  partially enforced through conditional docs evidence.
- Analytics/KPI/observability changes require KPI Registry review evidence:
  partially enforced through changed-path detection and
  `kpi_registry_reviewed`, `kpi_registry_updated`, and
  `kpi_registry_sync_checked` evidence fields. Trivial changes can record
  `kpi_registry_reviewed: not-needed` with a task-specific justification in
  the surrounding evidence.
- Docs/workflow changes require changelog handling: partially enforced by
  staged/worktree `docs/CHANGELOG.md` changes or explicit evidence.
- Schema or migration changes require docs/db validation or follow-up:
  partially enforced by changed-path detection and evidence.
- Touched core docs have valid version headers: enforced for known core docs.
- Prevent obvious secrets from being committed: partially enforced by staged
  regex scanning.
- Preserve unrelated user changes: prompt-only; hooks avoid destructive actions
  but cannot determine ownership of existing changes.
