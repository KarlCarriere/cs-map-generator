# Playwright Acceptance Instructions

This file is the source of truth for acceptance E2E testing with Playwright.

It is intended for `CMN::ACCEPTANCE-TEST-WRITER` and any orchestrator delegating acceptance work.

## Scope

- Build cycle-scoped acceptance tests from approved planner criteria.
- Enforce red-first before implementation.
- Provide strict input/output contracts for predictable handoffs.
- Define a standard Playwright harness baseline when missing.

## CLI Usage

- Use `npx playwright test` to run acceptance tests via the Bash tool.
- Use `npx playwright test --headed` or `--debug` for visual debugging when needed.
- Validate locators and accessible names through source code inspection and DOM output from test runs.
- Do not rely on interactive MCP browser tools — all browser interaction happens through written test code executed via CLI.

## Input Contract (Required Before Writing Tests)

The agent must collect all required inputs before creating tests:

1. `planFilePath`: path to the approved planner file.
2. `featureId`: short identifier for the feature cycle.
3. `baseUrl`: target URL for execution.
4. `authSetup`: authentication mode and credentials/session approach.
5. `testDataSetup`: required seed state or fixtures.
6. `executionCommand`: existing project command, if one exists.
7. `approvalExpectation`: explicit confirmation that user sign-off is required before handoff.

If any required input is missing, the agent must pause and ask clarifying questions.

## Output Contract (Required For Handoff)

The acceptance step is complete only when the agent outputs all artifacts below:

1. `createdOrUpdatedFiles`: exact list of changed files.
2. `criteriaCoverageTable`: one row per acceptance criterion mapped to one or more test cases.
3. `redGateReport`:
   - total tests created for this cycle
   - failed count
   - passed count (must be zero before coding starts)
   - per-test classification: `product-gap` or `test-defect`
4. `approvalStatus`: `approved` or `not-approved`.
5. `permanentDeletionManifest`: exact list of acceptance tests that must be deleted permanently after full green.

No handoff to coding orchestration is allowed without this output package.

## Playwright Harness Baseline (When Missing)

If the target project does not already have an E2E harness, the agent should create a minimal baseline:

1. `playwright.config.ts`
2. `tests/acceptance/` directory
3. `tests/acceptance/fixtures/` directory
4. cycle-scoped spec files in `tests/acceptance/`
5. package scripts for acceptance execution

### Baseline Config Rules

- `testDir`: `tests/acceptance`
- `retries`: `0` during red-first phase
- `fullyParallel`: `false` by default unless project already standardizes differently
- `reporter`: keep simple and readable (`list` or project equivalent)
- use `baseURL` from input contract

### Baseline Script Names

If scripts are added, prefer:

- `test:acceptance`
- `test:acceptance:headed`
- `test:acceptance:debug`

## Locator And Wait Policy

- Prefer `getByRole`, then `getByLabel`, then visible text as needed.
- Never use XPath selectors.
- Never use CSS class-based selectors.
- Never use `waitForTimeout`.
- Never use `data-testid` selectors.
- If role/label/text are insufficient, stop and report an accessibility contract gap (missing semantic role/label/text) to be implemented.
- Use assertion-based waiting (`expect(...).toBeVisible()`, `toHaveURL`, `toContainText`, etc.).

## Red-First Enforcement

Before implementation starts:

1. 100% of cycle-scoped acceptance tests must fail at least once.
2. 0 cycle-scoped acceptance tests may pass.
3. Failures must represent missing behavior (`product-gap`), not broken tests.

If failures are `test-defect`, fix the tests and rerun before handoff.

## User Approval Gate

After red-gate validation and before coding handoff:

1. Present coverage table.
2. Present red-gate report.
3. Ask for explicit user approval.
4. Wait for explicit approval.

No implicit approval is allowed.

## End-Of-Cycle Permanent Deletion

After full green status is reached for the feature cycle:

1. Delete permanently from the repository all acceptance tests listed in the `permanentDeletionManifest`.
2. Re-run the standard project test checks after deletion.
3. Continue to next feature cycle.
