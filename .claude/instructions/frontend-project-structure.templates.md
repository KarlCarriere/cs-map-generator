# Required Folder Structure

This template describes the **framework-agnostic** project folder layout used by Devsights frontend projects. The component file extension depends on the project's UI framework (`.tsx` for React, `.vue` for Vue, `.svelte` for Svelte, etc.) — match the project's coder agent (`.claude/agents/frontend__coder__<framework>.agent.md`).

```
root/
├── docs/
│   └── components.md (index of components)
└── src/
    ├── config/
    ├── features/
    ├── globalAssets/
    ├── globalComponents/
    ├── locales/
    ├── mocks/
    ├── router/
    └── pages/ (all navigable pages)
```

## Examples

Examples below use the React extension (`.tsx`, `.scss`) for illustration. Substitute the project's framework-specific extension when applying these patterns.

### Example feature

```
features/
└── contact/
    ├── pactTests/
    │   └── contactRepository.pact.test.ts
    ├── api/
    │   ├── dto/
    │   │   ├── addContactRequest.ts
    │   │   ├── addContactRequest.test.ts
    │   │   ├── contactResponse.ts
    │   │   └── contactResponse.test.ts
    │   └── contactRepository.ts
    └── components/
        └── addContactForm/
            ├── addContactForm.<ext>          # .tsx | .vue | .svelte | …
            ├── addContactForm.test.<ext>
            ├── useAddContactForm.<ext>       # custom hook / composable / store, when applicable
            ├── useAddContactForm.test.<ext>
            └── addContactForm.<style-ext>    # .scss | .css | .module.css | …
```

### Example component

```
globalComponents/
└── button/
    ├── button.<ext>
    ├── button.test.<ext>
    ├── useButton.<ext>      (if necessary)
    ├── useButton.test.<ext> (if necessary)
    └── button.<style-ext>
```

The exact extensions, the existence of a co-located hook/composable file, and the styling-stack file format come from the project's frontend coder agent and frontend instructions.
