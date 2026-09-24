# Architecture overview

MCP Bridge is a small public gateway that composes independent private modules and one
private account management service.

```mermaid
flowchart TB
    Client[ChatGPT / MCP clients] -->|OAuth + MCP| GW[gateway]

    GW --> GH[github]
    GW --> GL[gitlab]
    GW --> FI[files]
    GW --> WE[web]\n    WE --> CU[curl runtime]\n    GW --> AN[analysis]

    GH --> CP[management]
    GL --> CP
    FI --> CP
    CU --> CP
    AN --> CP

    CP --> DB[(SQLite)]
    FI --> STORE[(files-data)]
    CU --> STORE
    AN --> GD[native Ghidra MCP :8081]
```

## Source ownership

- `bridge` — public OAuth boundary and routing only.
- `common` — provider-neutral runtime contracts, settings, HTTP primitives and management client.
- `management.domain` — account and telemetry domain models.
- `management.application` — use cases and repository/crypto/verifier ports.
- `management.infrastructure` — SQLAlchemy, SQLite, encryption, Files administration and provider verification adapters.
- `management.presentation` — private FastAPI and Starlette Admin adapters.
- `modules.github` — GitHub-specific API capabilities.
- `modules.gitlab` — GitLab-specific API capabilities.
- `modules.files` — persistent content-addressed Files data plane.
- `modules.curl` — structured curl request/download/stream support.
- `modules.analysis` — schema-driven terminology facade over native Ghidra MCP.

Provider modules never import each other. GitHub and GitLab do not know SQLAlchemy or
SQLite; they depend on the provider-neutral account contract through the private
management client.

## Configuration and composition roots

Process environment is an infrastructure input. Each ASGI runtime creates typed settings
and composes its dependencies once at startup. Provider/application code does not read
process environment while handling requests.

Dynamic GitHub/GitLab accounts are not deployment settings. They live in the management
account repository and are selected explicitly by `account_id` on MCP calls. Deployment
environment contains only bootstrap values such as internal service auth, encryption key,
admin auth, gateway OAuth and runtime policies.

## Data ownership

Only the `management` process opens its SQLite database. Provider runtimes resolve
account metadata/credentials over authenticated private HTTP. Only the `files`/`curl`
runtimes mount the Files data plane. This keeps persistence ownership explicit even though
all source code remains in one repository.

## Public surfaces

```text
/mcp
/github/mcp
/gitlab/mcp
/files/mcp
/web/mcp
/analysis/mcp
/ghidra/mcp
/admin
```

The management `/internal/*` API remains private. Its Starlette Admin UI is exposed only through the authenticated public origin at `/admin`.

Raw Ghidra remains an independent backend and is also exposed directly through `/ghidra/mcp`. Analysis adapts its live MCP catalog and
normalizes every call back to canonical Ghidra tool names and argument keys.


## Root MCP map

The root `/mcp` surface does not mount provider tool namespaces. It exposes only bridge
diagnostics plus `bridge_backends`, `bridge_tools` and `bridge_call`. Clients can
inspect backend availability and signatures on demand or forward a call through the bridge,
while dedicated provider MCP endpoints remain directly addressable.


## Production deployment isolation

Production deployment units are intentionally finer-grained than the repository. Gateway,
Management and every MCP backend use separate Dockerfile targets and should be configured as
separate Coolify applications on the shared internal network. This prevents an unrelated
provider change from rebuilding or restarting the edge or other providers.

The root `docker-compose.yaml` remains the integration/local topology. Production split
configuration and Watch Paths are documented in `deploy/coolify/README.md`.
