# Frontend Styling Instructions

This file is the source of truth for **framework-agnostic** styling principles across frontend agents.

Agents should reference this file instead of duplicating styling principles in agent profiles. The concrete styling stack (SCSS/BEM, CSS Modules, Tailwind, vanilla-extract, styled-components, …) and any project-specific naming conventions are owned by the project's frontend coder agent (`.claude/agents/frontend__coder__<framework>.agent.md`) and the project's frontend stack source-of-truth (`.claude/instructions/frontend.instructions.md` when adopted).

## Principles

- **Component-scoped styling**: every component's styles are scoped to that component (via the styling stack's mechanism — local class names, CSS Modules, scoped SCSS files co-located with the component, scoped attributes, etc.). Avoid global styles outside the documented global layer.
- **Tokens over magic numbers**: all spacing, color, typography, border-radius, elevation, and breakpoint values come from a documented design-token layer. No magic numbers, no hardcoded hex values, no ad hoc spacing in component styles.
- **No inline styles**, except when the value is dynamically computed at runtime and cannot be expressed via the project's styling stack.
- **Responsive-first**: respect the project's documented breakpoint tokens; never inline arbitrary `px` breakpoints.
- **Naming convention**: follow the convention documented by the project's frontend coder agent (e.g. BEM `block__element--modifier` for SCSS-based projects, utility-class composition for Tailwind, locally-scoped class identifiers for CSS Modules). Do not introduce a second naming convention into a project that already standardises one.
- **Nesting discipline**: when the styling stack supports nesting (SCSS, native CSS nesting), use it only to express structural relationships defined by the project's naming convention — do not nest arbitrarily.

## Project-specific details

The exact stack, file structure, token taxonomy, and naming convention live in the project's frontend coder agent and frontend instructions. Read those before writing styles. If they conflict with this file, the project-specific instructions win.
