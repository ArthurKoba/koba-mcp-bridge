# Components

| Source module | Runtime service | Responsibility |
| --- | --- | --- |
| `bridge` | `gateway` | OAuth, aggregate routing, dedicated public facades |
| `common` | — | shared runtime/config, management client, HTTP transport and Git-domain primitives |
| `management` | `management` | provider account registry, encrypted credentials, admin UI and invocation telemetry |
| `modules.github` | `github` | GitHub App repository, review, history and Actions capabilities |
| `modules.gitlab` | `gitlab` | GitLab accounts, repositories, merge requests, issues and CI |
| `modules.files` | `files` | immutable object storage, metadata, uploads, collections, references and lifecycle |
| `modules.curl` | `curl` | request preparation, curl execution, response parsing, downloads and stream capture |
| `modules.analysis` | `analysis` | schema-driven terminology facade over native Ghidra MCP |

## Internal architecture

`management.domain` and `management.application` are independent of FastAPI,
Starlette Admin, SQLAlchemy, SQLite and provider SDK details. Infrastructure and
presentation adapters depend inward on the application ports.

GitHub and GitLab runtimes do not open the account database. They resolve an explicit
`account_id` over the authenticated private management API. Provider credentials are
never returned by public MCP tools.

Shared mechanisms belong in `common` only when they are provider-neutral. Provider API
semantics remain inside the owning module.

Each private runtime gets its own ASGI entrypoint under
`modules.<name>.runtime:app` or `management.runtime:app`. Only `gateway` is public.
