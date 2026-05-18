# Project Instructions

## Overview

This document describes the technology stack, architectural decisions, and conventions for the **pi-backend** Python project. It is the single source of truth for every backend agent and contributor working on this codebase.

This is a Python REST API for a Raspberry Pi device management appliance. It exposes hardware controls (Wi-Fi, brightness, volume, reboot/shutdown), hardware health monitoring (camera, pumps, light), analysis lifecycle orchestration, and device language preference to a co-located frontend. The API runs on the device, binds to `localhost` only, and is never exposed to an external network.

For a high-level overview of the system, the agent ecosystem, and the workflows, read `PROJECT.md` first.

## Stack

- **Language**: Python 3.12 (target via `pyproject.toml`)
- **Web framework**: FastAPI (with Starlette `TestClient` for tests)
- **Validation**: Pydantic v2 + `pydantic-settings`
- **Persistence**: SQLite via SQLModel (SQLAlchemy 2 + Pydantic). Schema is created at startup via `SQLModel.metadata.create_all` — **no Alembic, no migrations** (see ADR-002).
- **HTTP client**: `httpx`
- **Email**: `jinja2` + `babel` + `weasyprint`; transport via SendGrid Mail Send v3 (hand-rolled `httpx` adapter)
- **Contract testing**: `pact-python` (provider verification only on this side — the consumer is the React frontend)
- **Tests**: `pytest` (`pytest-asyncio` strict mode), Starlette `TestClient`
- **Linter / formatter**: Ruff (`pyproject.toml` rule set: `E`, `W`, `F`, `I`, `UP`, `B`, `S`, `C4`, `SIM`, `TCH`, `RUF`)
- **Server**: Uvicorn
- **Distribution**: Docker image `pi-backend`, bound to port 8001, `/data` volume for SQLite persistence

## Dependencies And Imports

- Before adding or keeping any import, verify that the symbol is not deprecated in the currently used library version
- Prefer stable, non-deprecated APIs in FastAPI, Pydantic v2, SQLModel, SQLAlchemy, and third-party libraries
- If no safe replacement is known, stop and ask the user before proceeding
- Deprecation verification must use the current official documentation/changelog of the exact dependency version in use — when in doubt, fetch via `mcp__context7__get-library-docs`
- Pin and bump dependencies in `requirements.txt`; tooling configuration lives in `pyproject.toml`

## Security Baseline

- Never hardcode secrets, API keys, passwords, tokens, private keys, or certificates in code, tests, or committed configuration files
- Retrieve secrets only from environment variables loaded via `pydantic-settings` (`Settings` class in `src/config.py`); never call `os.getenv(...)` from business code
- `Settings` validates required environment variables at instantiation (`@model_validator`) and fails fast on missing or malformed values
- Environment is selected via the `ENV_FILE` env var (`.env.dev`, `.env.mock`, `.env.prod`); the production image bakes in `.env.prod`
- Never log secrets or leak sensitive values in error payloads, logs, metrics, or traces; redaction helpers (e.g. `email_log_redaction.py`) exist for sensitive fields
- Never leave an `except` block empty — re-raise, translate to a typed domain exception, compensate, or log with actionable context

## Authentication And Authorization

- All hardware-control and frontend-facing mutating endpoints are gated by an **API-key dependency** (`verify_api_key` in `src/api/auth.py`) that compares the `X-API-Key` header to `settings.api_key`. Missing/invalid keys return `401`.
- WebSocket clients pass the API key as the `api_key` query parameter (browsers cannot set custom headers before the WS handshake). Invalid keys close the socket with code `1008 (Policy Violation)`.
- Backend-to-backend endpoints called by the analysis backend (`POST /api/cartridge`, `POST /api/analysis/status`, `POST /api/analysis/complete`, `POST /api/material/status`, `POST /api/material/error`, `POST /api/material/calibrated`) are intentionally unauthenticated today; do not add JWT or session-based auth on these without an ADR.
- This project does **not** use JWTs. Do not introduce JWT validation, OAuth flows, or password hashing — they have no place here. (See ADR-001 + ADR-004 for the full rationale.)
- Apply deny-by-default authorization for any new endpoint: if it mutates device state or returns user data, gate it on `verify_api_key` via `dependencies=[Depends(verify_api_key)]` on the route. Never trust client-provided identifiers without server-side verification.

---

## Architecture

The project follows **Clean Architecture** with explicit layer boundaries and dependency inversion. There is **no service layer** — controllers call domain command handlers, domain repositories (ABC ports), or query repository methods directly. See `docs/adr/003-no-service-layer.md`.

### Layer-first organisation

Code is organised **by layer first, then by bounded context**. Each layer is a top-level package under `src/` and contains one sub-package per concept (e.g. `analysis`, `cartridge`, `language`, `material`, `notification`, `os_control`, `dx`, `websocket`).

```
src/
  api/<concept>/        # FastAPI routers + Pydantic request/response models
  domain/<concept>/     # Pure Python: ABC ports, frozen dataclasses, commands, command handlers, exceptions
  infra/<concept>/      # Concrete port implementations + SQLModel ORM entities + hardware adapters + HTTP clients
  composition/          # Composition Root: FastAPI Depends() providers binding domain ports to infra adapters
  common/               # Cross-cutting domain primitives (e.g. AnalysisSortField, SortOrder)
```

Do **not** flip this to concept-first packaging (`src/<concept>/api/...`). The flat layer organisation is deliberate so dependency direction is enforced statically by import paths.

### Dependency direction

`api` → `domain` ← `infra` ← `composition`. The Composition Root (`src/composition/`) is the **only** layer that imports both domain ports and infra adapters together. Every other layer depends on abstractions defined in `domain/`.

| Layer | Allowed imports from | Framework deps? |
|---|---|---|
| `api` | `domain`, `composition`, Pydantic, FastAPI | Yes (FastAPI, Pydantic) |
| `domain` | itself, stdlib only | **No** — zero framework dependencies |
| `infra` | `domain` (to implement ports), framework SDKs | Yes (SQLModel, httpx, hardware libs) |
| `composition` | `domain` ports + `infra` adapters | Yes (FastAPI `Depends`) |

ORM entities (`AnalysisModel`, `LanguageModel`, `EmailJobModel`) live exclusively under `src/infra/<concept>/<concept>_model.py` and never cross into `domain` or `api`. Translation between ORM rows and domain dataclasses happens inside the repository implementation (e.g. `_to_domain` in `SqlAnalysisRepository`).

### Command handler pattern

For every domain concept that mutates state, define:

1. A frozen dataclass `*Command` in `src/domain/<concept>/commands.py` (one file per concept).
2. A dedicated `*CommandHandler` class in its own file: `src/domain/<concept>/<verb>_<concept>_command_handler.py` (one handler per file). Each handler exposes a single `handle(command)` method.
3. A request DTO in `src/api/<concept>/requests.py` with a `to_command()` method that builds the frozen command. Validation lives on the Pydantic model.

Pure read operations (listings, single-entity fetches) call the repository **port directly from the controller** via `Depends(get_<concept>_repository)`. Do not introduce a `*QueryHandler` class for simple reads — the FastAPI route function is already thin enough.

Do not introduce `*Service` or `*Manager` classes. If you find yourself wanting one, extract a command handler or call the repository port directly.

### Composition Root

`src/composition/` holds one file per concept, mirroring the api/domain/infra layout. Each file declares **provider functions** consumed via FastAPI `Depends()`:

- Request-scoped providers (e.g. repositories that depend on a `Session`) build a fresh instance per request.
- Process-scoped singletons (e.g. `in_flight_analysis_repository`, `websocket_analysis_event_publisher`) are imported from `src.infra` and returned as-is.
- Handlers are constructed per request from their dependencies.

When two composition files would otherwise import each other, extract the shared leaf providers into `src/composition/<concept>_ports.py` (see `notification_ports.py`).

`get_session` lives in `src/infra/database.py` because it is a request-lifecycle primitive, not a port binding.

### Mock injection

When `app_env != "prod"`, FastAPI `app.dependency_overrides` swap real adapters for in-memory or no-op equivalents:

| Real | Mock | Selected when |
|---|---|---|
| `PiOs` | `MockOs` | `app_env in {"mock", "dev"}` |
| `HttpDxBackend` | `MockDxBackend` | `app_env == "mock"` |
| `SqlAnalysisRepository` | `MemoryAnalysisRepository` | `app_env == "mock"` |
| `SendGridEmailSender` | `LoggingEmailSender` | non-prod (no `SENDGRID_API_KEY`) |

Tests apply the same `dependency_overrides` mechanism in `tests/conftest.py`. Tests never touch real hardware, the real DB file, or real network endpoints.

### WebSocket relay

`src/infra/websocket/websocket_hub.py` defines a process-scoped `WebSocketHub` singleton with `connect`, `disconnect`, and `broadcast` methods. Domain event publishers (e.g. `AnalysisEventPublisher`, `MaterialEventPublisher`) are domain ports (ABCs); the infra implementations wrap the hub and publish typed envelopes. Controllers translate inbound HTTP relays from the analysis backend into command-handler invocations that ultimately call `publisher.publish_*` — they never write WebSocket envelopes themselves.

### Email outbox + worker

Email delivery is decoupled from the trigger via an outbox table:

1. Producers (`SendAnalysisReportCommandHandler`, `CompleteAnalysisCommandHandler`) persist an `EmailJob` row in the same DB transaction as the trigger.
2. A single asyncio task started in the FastAPI lifespan (`build_email_outbox_worker()`) polls `email_outbox`, renders (`composed_email_renderer.py` → Jinja2 body + WeasyPrint PDF, locale captured at enqueue time) and sends via SendGrid with exponential backoff.
3. Idempotency is enforced by client-supplied UUID (manual share) or `auto:{analysis.id}` (auto-send).

See `docs/adr/006-outbox-pattern-for-email-delivery.md`. Do not bypass the outbox for new email use cases.

---

## Project Structure

```
.
├── src/
│   ├── main.py                       # App factory, lifespan hook, router registration, mock injection, exception handlers
│   ├── config.py                     # pydantic-settings Settings; reads from ENV_FILE
│   ├── api/
│   │   ├── auth.py                   # verify_api_key dependency
│   │   ├── responses.py              # ok() / no_content() helpers + ValueResponse
│   │   ├── exception_handlers.py     # Centralised typed-exception → HTTP mapping
│   │   ├── <concept>/
│   │   │   ├── <concept>_controller.py  # APIRouter + path operations (thin)
│   │   │   ├── requests.py              # Pydantic v2 request DTOs with to_command()
│   │   │   └── responses.py             # Pydantic v2 response models with from_domain()
│   ├── domain/
│   │   ├── <concept>/
│   │   │   ├── <entity>.py                       # Frozen / non-frozen dataclasses
│   │   │   ├── <port>.py / <port>_repository.py  # ABC ports
│   │   │   ├── commands.py                       # Frozen dataclass *Command per concept
│   │   │   ├── <verb>_<concept>_command_handler.py  # One handler per file
│   │   │   └── exception.py                      # Typed domain exceptions
│   │   └── common/                   # Clock, IdGenerator (shared domain primitives)
│   ├── infra/
│   │   ├── database.py               # Engine, init_db() (create_all + seed), get_session generator
│   │   └── <concept>/
│   │       ├── <concept>_model.py             # SQLModel table (infra-only ORM entity)
│   │       ├── <concept>_repository.py        # Sql<Concept>Repository implementing the domain port
│   │       └── …                              # Hardware/HTTP/mock adapters as needed
│   ├── composition/
│   │   ├── <concept>.py              # Depends() providers per concept (mirrors api/ + infra/)
│   │   ├── <concept>_ports.py        # Shared leaf providers when two concepts depend on the same port
│   │   ├── common.py                 # Clock + IdGenerator providers
│   │   └── dx.py                     # DxBackend provider (real/mock)
│   └── common/                       # Cross-cutting domain primitives (e.g. query types)
├── tests/
│   ├── conftest.py                   # In-memory SQLite engine, session, TestClient, autouse cleanup fixtures
│   ├── api/<concept>/                # Controller integration tests (TestClient)
│   ├── domain/<concept>/             # Domain unit tests
│   ├── infra/<concept>/              # Repository and hardware adapter tests
│   ├── pact_tests/                   # Pact provider verification (consumes pi-frontend/pacts/*.json)
│   └── app_context_test.py           # Application context smoke test
├── docs/
│   ├── api.md                        # REST + WebSocket endpoint catalog
│   ├── openapi.json                  # Generated OpenAPI spec
│   └── adr/                          # Architecture decision records
├── bruno/pi-backend/<concept>/       # Bruno (.bru) request collections for manual exploration
├── data/                             # SQLite database file (gitignored at deploy time)
├── pacts/                            # Generated/consumed Pact contract files
├── audits/                           # Audit reports written by CMN::AUDITOR
├── Dockerfile                        # python:3.12-slim, port 8001, /data volume; WeasyPrint deps
├── requirements.txt                  # Runtime + test dependencies
├── pyproject.toml                    # Ruff + pytest configuration
└── .env.{prod,dev,mock}              # Per-environment configuration loaded via ENV_FILE
```

### README requirement

The project `README.md` must contain a **"Running locally"** section that covers:

1. **Prerequisites** — Docker only, no local Python toolchain required.
2. **Dev Container** — open in VS Code with the Dev Containers extension for a zero-setup environment.
3. **Environment selection** — how to choose `ENV_FILE` (`.env.mock`, `.env.dev`, `.env.prod`) and which mocks each enables.

---

## Persistence

- **One database engine — SQLite.** Schema lives entirely in SQLModel table classes under `src/infra/<concept>/<concept>_model.py`.
- **No migrations.** `init_db()` calls `SQLModel.metadata.create_all(engine)` plus seed data on every startup. Schema changes are applied by recreating the database (delete the SQLite file). See ADR-002.
- All ORM models must be imported once in `_import_models()` inside `src/infra/database.py` so `metadata.create_all` registers them.
- Repositories are ABC ports in `domain/<concept>/<concept>_repository.py` and concrete `Sql<Concept>Repository` classes in `infra/<concept>/<concept>_repository.py`. Always map ORM rows to domain dataclasses before returning from the repository — never leak `<Concept>Model` outside infra.
- Use SQLModel/`select(...)` expressions; only fall back to raw SQL when an SQLAlchemy expression cannot be expressed cleanly, and document why.
- Avoid N+1 queries. SQLite-backed reads are bounded by the device's data volume, but list endpoints must still be paginated (see ADR-005 for the bounded-enumeration exemption applied to Wi-Fi scan and recent recipients).
- Do not introduce a second database engine, an ORM other than SQLModel, or a migration tool without an ADR.

---

## REST API

- Controllers live in `src/api/<concept>/<concept>_controller.py` and expose one or more `APIRouter` instances. Keep them thin: parse → build command/query → invoke handler/repository → return a typed response.
- Use Pydantic v2 `BaseModel` classes for both **requests** (`requests.py`) and **responses** (`responses.py`). Requests expose `to_command()`; responses expose `from_domain(...)` (or `from_page(...)` for paginated lists).
- Apply explicit validation constraints on Pydantic fields (`min_length`, `max_length`, `ge`, `le`, regex, enum types). Never validate manually inside route functions.
- Use `Annotated[T, Query(...)]` / `Path(...)` / `Body(...)` for query/path/body parameters with metadata.
- HTTP status codes:
  - `200` — successful read returning a body
  - `201` — successful resource creation (rarely used here; favour `204` for accepted relays)
  - `204` — successful command execution returning no body (helper: `no_content()` in `src/api/responses.py`)
  - `400` — caller error in semantics (e.g. Wi-Fi connection failed)
  - `401` — missing or invalid API key
  - `404` — resource not found / no in-flight analysis
  - `409` — DB integrity violation
  - `422` — Pydantic validation failure or invalid value object input (e.g. malformed email)
  - `502` — analysis backend unreachable
  - `503` — local hardware/database temporarily unavailable
- Error responses use plain `JSONResponse` with `{"detail": "..."}` shape (FastAPI default). Do **not** introduce RFC 9457 `application/problem+json` payloads here without an ADR.
- All exception-to-HTTP mapping lives in `src/api/exception_handlers.py`. Add new typed domain exceptions there and register them in `register_exception_handlers(app)`. Never `try/except` for HTTP mapping inside a controller.
- Every list endpoint paginates via 0-indexed `page` + bounded `size` (default 20, max 100). Sort fields and order are explicit `StrEnum` values (`AnalysisSortField`, `SortOrder`). The only exemption is bounded-enumeration endpoints documented in ADR-005.
- The current API surface is unversioned (`/api/...`), reflecting its embedded device-local audience. Do not add `/v1/` versioning prefixes without an ADR.
- Keep OpenAPI metadata accurate: every `@router.<method>` call must set `summary`, `description`, status code, response schema (or `response_model`), and the `responses={...}` dict for documented error paths. The `BE::DOCS` agent owns synchronisation between the controller decorators, `docs/api.md`, and the Bruno collections.

---

## Domain Layer

- Pure Python only — **no FastAPI, Pydantic, SQLModel, or SQLAlchemy imports** under `src/domain/`.
- **Value objects**: `@dataclass(frozen=True)`. Validation runs in `__post_init__`; failures raise typed domain exceptions (e.g. `InvalidEmailAddressError`). Examples: `EmailAddress`, `WifiNetwork`, `AnalysisResult`, `MaterialHealth`.
- **Entities**: regular dataclasses with mutable lifecycle methods that enforce invariants (e.g. `Analysis.apply_start_data`, `Analysis.complete`, `Analysis.add_recipient`). Keep mutation expressed through named methods, not field reassignment from callers.
- **Commands**: `@dataclass(frozen=True)` records grouping the inputs of a single mutation. One `commands.py` per concept holds all of them.
- **Command handlers**: one class per file, one public `handle(command)` method, constructor-injected ports. Return `None` from handlers that mutate state; return query results only when the handler genuinely needs to read after writing.
- **Ports**: ABCs in `domain/<concept>/<port>.py` (or `<port>_repository.py`). Keep method names intention-revealing (`find_recent_recipients`, not `findAll`).
- **Domain exceptions**: subclass `Exception` (or `ValueError` for value-object validation failures). One `exception.py` per concept, plus the per-port file when an exception is tightly coupled to a port (e.g. `DxBackendError` lives next to `DxBackend`).
- Use explicit `T | None` only where absence is part of the contract. Do not use `None` as a substitute for a missing default.
- Type annotations are mandatory on every public function/method signature. Type aliases (`StrEnum`, `Literal`, `Iterable`, etc.) are preferred over implicit primitives.

---

## Python Conventions

- Target Python 3.12 features by default. Use modern syntax: union types (`X | Y`), `match/case`, `StrEnum`, `dataclass(frozen=True)`, generic type aliases.
- **Naming**: `snake_case` for functions, methods, and module-level variables; `PascalCase` for classes/dataclasses/enums; `UPPER_SNAKE_CASE` for module-level constants. **Override the camelCase rule from `CLAUDE.md`** — that rule targets Java; in this Python project, methods and variables are `snake_case`.
- **Test names**: `test_should_<result>_when_<condition>` (note the `test_` prefix is required for pytest discovery). Class-based tests are not used.
- Prefer comprehensions, `map`, `filter`, generator expressions, and `functools.reduce` over imperative `for` loops when the result is clearer. Imperative loops are acceptable when the body has multiple side effects (e.g. `email_outbox_worker` polling loop).
- Side effects (DB I/O, HTTP, hardware calls, WebSocket broadcasts) live in `src/infra/`. Domain code never performs I/O directly.
- Use `Protocol` for read-only structural typing on adapters that come in via dependency injection only when an ABC would force unwanted inheritance; otherwise prefer ABCs (this project's prevailing choice).
- Public collections returned across boundaries must be tuples or frozen sequences when immutability matters (e.g. `Analysis.send_to: tuple[EmailAddress, ...]`).
- No magic numbers or strings — extract module-level constants (e.g. `MAX_PAGE_SIZE`, `RECENT_RECIPIENTS_WINDOW_DAYS`, `MAX_ANIMAL_NAME_LENGTH`).
- All catch (`except`) blocks must rethrow, translate to a typed domain exception, compensate, or log with actionable context. Never `except: pass`.

---

## Error Handling

- Use intention-revealing custom exceptions (`AnalysisNotFoundError`, `NoInFlightAnalysisError`, `DxBackendError`, `InvalidEmailAddressError`, …) — never raise bare `Exception`.
- Raise typed domain exceptions from the layer that detects the violation (typically `domain/` or `infra/` adapters) and let the centralised handlers in `src/api/exception_handlers.py` map them to HTTP responses.
- Log at the boundary entry/exit (controller dispatch, infra adapter calls). Never log inside pure domain methods.
- Use Python's stdlib `logging` (`logger = logging.getLogger(__name__)`); do not introduce `print` statements or other ad-hoc logging.
- Never expose stack traces, internal IDs, or sensitive payload values in API responses. The `_error_response` helper in `exception_handlers.py` enforces a consistent `{"detail": "..."}` shape.

---

## Performance

- No database query inside a loop — batch via `select(...).where(col.in_([...]))` or join.
- Pagination is mandatory on every list endpoint, with bounded page sizes. Bounded-enumeration exemptions are documented in ADR-005.
- Async (`async def` route or handler) is used only when the work is genuinely I/O-bound through an awaitable client (httpx async, WebSocket broadcasts). Synchronous handlers are perfectly acceptable when no awaitable is involved — do not artificially add `async` for stylistic reasons.
- Cache only after measurement; document the cache key and eviction strategy (this project currently caches no application data — the singleton repositories are the closest thing).
- Profile before optimising — do not guess at bottlenecks.

---

## Configuration

- All runtime configuration lives in `src/config.py` as the `Settings` class (`pydantic-settings`). Never read from `os.environ` outside this module.
- The `ENV_FILE` environment variable selects which `.env.*` file is loaded (default: `.env.mock` for local testing). Production sets `ENV_FILE=.env.prod` via the Docker image.
- Required-when-present validators (e.g. `email_from_address` is required when `sendgrid_api_key` is set) live as `@model_validator(mode="after")` methods on `Settings` so misconfiguration fails fast at startup.
- Add new settings as typed fields with explicit defaults or `Field(...)` descriptions; never silently fall back to `None` when a value is required in production.
- `app_env: AppEnv` (`prod` | `dev` | `mock`) drives the mock-injection switch in `src/main.py`. Add new mocks via `app.dependency_overrides` keyed on the composition-root provider, not by editing infra classes directly.

---

## Tooling

- **Lint**: `ruff check`. The configured rule set (see `pyproject.toml`) enforces pyflakes, isort, pyupgrade, bugbear, bandit, comprehensions, simplify, type-checking-import, and Ruff-native rules. Per-file ignores are scoped narrowly (e.g. `S` allowed in tests, `S603/S607` allowed for hardcoded `subprocess` calls in `src/infra/os_control/`).
- **Format**: `ruff format`. Line length 120, double quotes, trailing-comma normalisation, `force-sort-within-sections = true` for imports.
- **Tests**: `pytest`. `asyncio_mode = "strict"`. Filter warnings for known noisy upstreams (websockets legacy, uvicorn ws protocols).
- Run lint, format check, and tests before opening a PR. CI is the gate of last resort, not the first.

The `npm run review:staged` gate referenced by `CMN::GIT` does not exist in this project. Until a Python equivalent is wired up, the staged review consists of: (1) `ruff check && ruff format --check` on staged files, (2) the relevant `pytest` subset, (3) manual visual diff. Document any deviation in the PR.
