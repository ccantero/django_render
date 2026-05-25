# Codex Workflow Hooks

Repo-local hooks for the AGENTS.md workflow:

1. planner
2. implementer
3. tester
4. documentator

These scripts enforce deterministic checks that can be verified from files,
Git state, and an explicit workflow evidence file. They do not claim to force
Codex native subagents to run. In this repo inspection, no native Codex hook
configuration was found, so these scripts are manual/local integration points.

## Scripts

- `pre-task.sh`: validates required governance files before work starts and
  reports whether native Codex hook config appears to exist.
- `post-edit.sh`: lightweight advisory check after edits. It detects changed
  files, reports likely impact classifications, and warns about downstream
  validation that `post-task.sh` or `pre-commit.sh` will enforce.
- `post-task.sh`: strict final task check. It validates ordered workflow
  evidence, non-placeholder role evidence, tests, docs review, changelog
  handling, schema/DER handling, and touched core-doc version headers.
- `pre-commit.sh`: checks staged changes only. It validates workflow evidence,
  touched core-doc headers, changelog/schema requirements, and scans staged
  content for obvious secret patterns.
- `docs-sync.sh`: validates docs governance for all or staged changes and,
  when `DASHBOARD_DATA_CONTRACT` is set, checks the paired dashboard
  `docs/DATA_CONTRACT.md` synchronization when this repo's contract changes.
- `self-check.sh`: syntax-checks the hook scripts and exercises them in a
  temporary Git repository.

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

`.codex/hooks/lib.sh` is kept only as a compatibility shim that sources these
focused libraries.

## Workflow Evidence

The validators look for:

```bash
.codex/hooks/workflow-evidence.md
```

Use another path with:

```bash
CODEX_WORKFLOW_EVIDENCE=/tmp/current-codex-task.md .codex/hooks/post-task.sh
```

Start from:

```bash
cp .codex/hooks/workflow-evidence.template.md .codex/hooks/workflow-evidence.md
```

The template is intentionally incomplete. A copied template starts with
`pending` role markers and placeholder values, and strict hooks reject it until
each role has task-specific evidence:

- `planner_evidence`
- `implementer_evidence`
- `tester_evidence`
- `documentator_evidence`

The evidence file records ordered completion markers, impact classification,
tests, docs review, changelog handling, schema/DER handling, data-contract sync
handling, and pending issues. This is how the hooks detect that the workflow
order was followed. They cannot prove that a specific Codex implementation
used separate native subagents.

For paired dashboard contract validation, set:

```bash
DASHBOARD_DATA_CONTRACT=/path/to/dashboard/docs/DATA_CONTRACT.md
```

If that variable is unset and `docs/DATA_CONTRACT.md` changed, `docs-sync.sh`
warns and asks for follow-up evidence instead of embedding a machine-local
path.

## Manual Use

Recommended local sequence:

```bash
.codex/hooks/pre-task.sh
.codex/hooks/post-edit.sh
.codex/hooks/post-task.sh
.codex/hooks/docs-sync.sh all
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

`post-edit.sh` is intentionally warning-oriented so it can run frequently
during implementation. Use `post-task.sh` and `pre-commit.sh` for strict gates.

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

That variable only bypasses the protected-file block. Secret scanning, evidence
checks, docs checks, schema/DER checks, and version-header checks still run.

## Native Codex Hooks

No native Codex hook configuration file was found in this repository during
implementation. If a future Codex runtime exposes native hook wiring, point it
at these scripts in the same phases:

- pre-task: `.codex/hooks/pre-task.sh`
- post-edit: `.codex/hooks/post-edit.sh`
- post-task: `.codex/hooks/post-task.sh`

Keep Git-specific checks on `.codex/hooks/pre-commit.sh`.

## Secret Scan

`pre-commit.sh` includes a small regex-based staged-content scan for obvious
secrets such as private keys, database URLs, API secrets, and Telegram bot
tokens. This is a basic guard only. It does not replace dedicated tools such
as `gitleaks` or `detect-secrets`; those dependencies are not installed or
required by these hooks.

## Enforcement Map

- Required files exist: enforced by all validators.
- Planner before code changes: partially enforced by workflow evidence marker
  and non-placeholder role evidence detection; actual subagent execution is
  prompt-only unless native hooks exist.
- Behavior changes require tests: partially enforced by changed-path detection,
  touched tests, and evidence fields.
- Behavior/contract/schema/logging/docs-governance changes require docs review:
  partially enforced through docs-review evidence.
- Meaningful changes require changelog entry when applicable: partially
  enforced by staged/worktree `docs/CHANGELOG.md` changes or explicit evidence.
- Schema or migration changes require docs/db validation or follow-up:
  partially enforced by changed-path detection and evidence.
- Touched core docs have valid version headers: enforced for known core docs.
- Prevent obvious secrets from being committed: partially enforced by staged
  regex scanning.
- Preserve unrelated user changes: prompt-only; hooks avoid destructive actions
  but cannot determine ownership of existing changes.
