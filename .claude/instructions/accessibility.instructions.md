# Accessibility Instructions

This file is the source of truth for accessibility rules across frontend agents.

Agents should reference this file instead of duplicating accessibility rules in agent profiles.

## Standards

- Every interactive element must be keyboard-navigable
- Images require meaningful alt text
- Forms must have associated labels
- Color alone must not convey meaning
- Announce dynamic content changes to screen readers when relevant
- Use semantic HTML elements appropriately (e.g. `<button>`, not `<div role="button">`)
- Ensure sufficient color contrast for text and interactive elements
- Use ARIA attributes only when native HTML cannot achieve the desired accessibility outcome
