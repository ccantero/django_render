# TDD Skill

## When To Use

Use this skill for every implementation that changes application behavior, public interfaces, settings behavior, data handling, views, serializers, models, templates, logs consumed by operators, healthcheck payloads, CLI output, or user workflows.

Documentation-only and governance-only changes may skip new behavior tests only when the implementer explicitly states that no application behavior changed.

## Steps

1. Identify the smallest behavior to protect.
2. Add or update a focused test before implementation.
3. Run the focused test and confirm it fails.
4. Confirm the failure reason matches the intended behavior gap.
5. Implement the minimal fix.
6. Re-run the focused test and confirm it passes.
7. Avoid unrelated refactors.
8. For structured logging or operator-output changes, assert the presence of stable fields when practical.
9. For schema/contract changes, add or update tests that protect the expected data interpretation when practical.

## Failure Conditions

- Implementation is written before the failing test.
- No test is created for an application behavior change.
- The initial failing test is not executed.
- The initial test passes unexpectedly.
- The initial test fails for an unrelated reason.
- The fix changes unrelated behavior.
- The focused test is not re-run after implementation.
- Operator-facing log/output fields changed without test coverage or explicit justification.

On failure, stop and report the failed TDD checkpoint.
