# Frontend Bootstrap Templates

> **Stack-specific (Vite + React + Vitest + Playwright).** This file is **only consumed by the framework-specific project-initiator agent** (`FE::PROJECT-INITIATOR::REACT`). Framework-agnostic frontend agents (`FE::ORCHESTRATOR`, `FE::TEST`, `FE::DOCS`, `FE::COMPONENTS-INITIATOR`) must not depend on the templates in this file. Other framework initiators (Vue, Svelte, …) should ship their own bootstrap-templates instruction file.

This file is the canonical source of generated template files for React frontend project initialization.

## Usage Contract

- The initializer MUST generate all files listed here exactly.
- The initializer MUST preserve file paths and content.
- The initializer MUST fail explicitly if any file cannot be created.
- The initializer MUST create parent directories before writing files.
- The initializer MUST install `@devsights/frontend-core` as a runtime dependency.
- The initializer MUST NOT generate local `src/core/**` files because core is provided by `@devsights/frontend-core`.

## Required Directories

- `src/locales/`
- `src/mocks/`
- `tests/acceptance/`

## Required Files

### `src/locales/en.json`

```json
{}
```

### `src/locales/fr.json`

```json
{}
```

### `src/mocks/i18n.ts`

```ts
import { vi } from 'vitest'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: 'en' },
  }),
  Trans: ({ i18nKey }: { i18nKey: string }) => i18nKey,
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}))
```

### `vitest.config.ts`

```ts
import { defineConfig } from 'vitest/config'
import path from 'node:path'

export default defineConfig({
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/vitest.setup.ts'],
    exclude: ['**/node_modules/**', 'tests/acceptance/**'],
    server: {
      deps: {
        inline: [/@devsights\//],
      },
    },
  },
})
```

### `vite.config.ts``

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: process.env.VITE_SERVER_HOST ?? '0.0.0.0',
    port: process.env.VITE_SERVER_PORT ? Number(process.env.VITE_SERVER_PORT) : 5173,
  },
})
```

### `playwright.config.ts`

```ts
import { defineConfig } from '@playwright/test'

const baseURL = 'http://localhost:5173'

export default defineConfig({
  testDir: 'tests/acceptance',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL,
    trace: 'off',
  },
  webServer: {
    command: 'npm run dev -- --host 0.0.0.0 --port 5173',
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120000,
  },
})
```

## Package-based Core Usage

The frontend bootstrap must consume core utilities from `@devsights/frontend-core`.

- Install command:

```bash
npm install @devsights/frontend-core
```

- Import style in generated examples and future code:

```ts
import { AxiosInstanceFactory, RESTClient } from '@devsights/frontend-core'
```

- Do not generate local re-export shims in `src/core/**`.
