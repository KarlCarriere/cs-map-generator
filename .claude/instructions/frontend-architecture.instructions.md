# Frontend Architecture Instructions

> **Stack-specific.** This file documents architecture rules tied to the `@devsights/frontend-core` package and is **only consumed by the framework-specific frontend coder and project-initiator agents** (e.g. `FE::CODER::REACT`, `FE::PROJECT-INITIATOR::REACT`). Framework-agnostic agents (`FE::ORCHESTRATOR`, `FE::TEST`, `FE::DOCS`, `FE::COMPONENTS-INITIATOR`) must not depend on the rules in this file directly — they defer to the project's coder agent for architecture guidance.

This file is the source of truth for frontend architectural rules across the framework-specific coder/initiator agents.

## API Layer

- Use `@devsights/frontend-core` as the shared framework-agnostic core for API calls, HTTP client logic, and typed client errors
- Do not recreate or duplicate `@devsights/frontend-core` code in local `src/core/**`
- If a new reusable core capability is needed, create it in `src/core/` but prefer contributing it to `@devsights/frontend-core` if it is generally applicable
- UI components must not call APIs directly; they consume functions/services built on top of `@devsights/frontend-core`
- API calls must go through feature repositories (e.g. `src/features/<feature>/api/*Repository.ts`)
- Repositories are the only place allowed to call `apiClient` from `@devsights/frontend-core`
- When calling `apiClient`, always use relative endpoint paths (e.g. `/contacts`, `/contacts/{id}`)
- Never hardcode absolute API URLs or domains inside repositories, hooks, or components
- Never use `window.location.origin` to build API URLs, base URLs, or endpoints
