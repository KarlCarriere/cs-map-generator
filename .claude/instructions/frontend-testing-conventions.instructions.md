# Frontend Testing Conventions

This file is the source of truth for **framework-agnostic** frontend test file conventions and coverage standards across agents. The concrete test runner (Vitest/Jest/…), component testing binding (`@testing-library/{react,vue,svelte}`, …), and coverage tool come from the project's frontend coder agent and frontend stack source-of-truth.

## Test File Conventions

```
test_file_pattern: "**/*.{test,spec}.{ts,tsx,js,jsx,vue,svelte,mts,cts}"
                   # adapt to the project's framework — keep only the extensions actually used
test_location:     colocated
naming_convention: describe > it/test blocks

describe: component name, module name, or method name
it/test:  should [expected behavior in natural language]

describe_nesting:
  level_1: component name (<ComponentName />), class, or module name
  level_2: method name or scenario group (e.g. "when [context]")
  deeper:  sub-scenarios as needed (e.g. "when [specific condition]")

test_name_rules:
  - use normal sentence-style titles with spaces for every it()/test()
  - never use camelCase or snake_case for test titles
  - preferred shape: should [expected behavior] when [condition]
  - keep titles explicit and readable
```

## Coverage Configuration

Coverage is a **floor, not a goal**. It exists to catch untested code, not to prove quality.
Never write a test solely to increase a percentage — every test must validate meaningful behavior.

```
coverage:
  provider: v8 | istanbul | <project-specific equivalent>

  # Global thresholds — applies to the entire codebase (including legacy)
  global_thresholds:
    lines: 80
    branches: 80           # branches is the most revealing metric — do NOT relax it below lines
    functions: 80
    statements: 80

  # New code thresholds — stricter for any newly written or modified code
  # New code has no excuse for low coverage. Legacy gets a pass, new code does not.
  new_code_thresholds:
    lines: 90
    branches: 90
    functions: 90
    statements: 90

  # Suggested exclusions — adapt to the project's actual layout and framework
  exclude:
    - "**/*.stories.{ts,tsx,vue,svelte}"
    - "**/*.d.ts"
    - "**/index.ts"               # barrel files
    - "src/mocks/**"
    - "src/types/**"
    - "src/config/**"             # configuration files
    - "src/constants/**"          # static constants
    - "**/*.config.{ts,js,mjs,cjs}"  # build/test runner configs
    - "src/i18n/**"               # i18n setup and locale files
    - "src/styles/**"             # pure style files

principles:
  - branches ≥ lines — branches is the most meaningful metric, never set it lower than lines
  - coverage reveals untested code — it does NOT prove the tests are good
  - do NOT write tests just to hit a threshold — every test must assert meaningful behavior
  - a file at 100% coverage with bad assertions is worse than a file at 80% with strong assertions
  - uncovered lines are a signal to investigate, not an obligation to cover
  - if a line is intentionally untested (e.g. defensive fallback that cannot be triggered), document why with a comment
```
