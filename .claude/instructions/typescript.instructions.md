# TypeScript Instructions

This file is the source of truth for TypeScript implementation rules across agents.

Agents should reference this file instead of duplicating TypeScript rules in agent profiles.

## Language

- All code is written in TypeScript — no `any`, no implicit `any`
- Use strict TypeScript settings (`strict: true`) when configuring projects

## Typing Conventions

- Define explicit types for all component props using `interface` (preferred over `type` for object shapes)
- Use `type` for unions, intersections, and aliases
- Create dedicated type files (e.g. `types.ts`) for domain models shared across components
- Co-locate component-specific types in the component file unless they are reused elsewhere
- Avoid type assertions (`as T`) — fix the root type instead
- Generic components must declare their type parameters explicitly
- Export types that are part of a component's public API

## Imports And Deprecation

- Before adding or keeping any import, verify that the imported symbol or entry point is not deprecated in the currently used package version
- Prefer stable, non-deprecated APIs and imports
- If only deprecated options are available or the migration path is unclear, stop and ask the user before proceeding

## Runtime Configuration And Secrets

- Never hardcode secrets, API keys, passwords, or tokens in TypeScript source, tests, fixtures, or committed config
- Access environment variables only through a dedicated, strongly typed configuration module
- Validate environment variables at startup with a schema validator (for example Zod or Joi) and fail fast if any required value is missing or malformed
- Do not spread raw `process.env` access across the codebase — expose validated typed values from the config module
- Never log secrets or include sensitive values in thrown errors

## Authentication And Authorization

- For JWT handling in TypeScript backends, always validate signature, allowed algorithm, expiration, not-before, issuer, and audience
- Reject unsigned tokens (`alg: none`) and algorithms outside an explicit allowlist
- Apply deny-by-default authorization and verify roles/permissions before executing business logic

## Error Handling

- Never leave a `catch` block empty
- Every `catch` block must explicitly rethrow, translate to a typed domain error, or handle with actionable context
