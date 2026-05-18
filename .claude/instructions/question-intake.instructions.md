# Question Intake Guidance

Ask clarifying questions using a /plan-like UX. Do not proceed until the user replies.

## Primary UX (interactive)

When interactive question controls are available to you, use them to ask structured questions.

Rules:
- Ask questions one at a time OR in a small batch of max 3 questions.
- ALWAYS stop after asking and wait for answers.
- Use options (single-select / multi-select) whenever it reduces ambiguity.
- Always allow free-text input when the user may need to provide a custom value.

Choose the question mode contextually:
- Use single-select options when choices are mutually exclusive.
- Use multi-select options when choices are additive.
- Use free-text input when the answer is open-ended or unknown.
- Use mixed mode (select + optional free-text note) when structured choice and nuance are both useful.

## Fallback UX (plain text)

If interactive controls are unavailable, provide an equivalent plain-text fallback that:
- Numbers the options (1), (2), (3), ...
- Explicitly states the default (if any)
- Allows a free-text answer

Example:

"Choose deployment target: (1) Azure App Service (default) (2) Azure Container Apps (3) AKS. You can also type a custom target."
