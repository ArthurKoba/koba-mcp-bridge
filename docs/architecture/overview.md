# Architecture overview

## Current platform

The current Koba platform scope is intentionally narrow:

- Secrets;
- GitHub;
- GitLab;
- Ghidra;
- Files/artifact storage;
- HTTP/curl.

Other future platform ideas are explicitly outside the current stabilization pass.

```mermaid
flowchart LR
    C[ChatGPT / MCP clients] -->|OAuth + MCP| B[koba-mcp-bridge]

    B --> S[Secrets resolver]
    S --> I[Infisical]

    B --> GH[GitHub]
    B --> GL[GitLab]
    B --> HTTP[HTTP / curl]
    B --> F[Files / artifact store]
    B --> GA[Ghidra adapters]
    B -->|mounted MCP| GM[ghidra-mcp]

    GH --> GitHub[GitHub API]
    GL --> GitLab[GitLab instances]
    HTTP --> Internet[HTTP endpoints]
    F --> Store[(content-addressed storage)]
    GM --> Ghidra[Ghidra workers]
```

## Stabilization direction

The repository may remain a monorepo, but connector/runtime failure domains should become independent.

```mermaid
flowchart TB
    Client[ChatGPT / MCP clients]

    GW[gateway-mcp]
    GH[github-mcp]
    GL[gitlab-mcp]
    FI[files-mcp]
    HT[http-mcp]
    GD[ghidra-mcp]
    SEC[Infisical]

    Client --> GW
    Client --> GH
    Client --> GL
    Client --> FI
    Client --> HT
    Client --> GD

    GW -. optional aggregation .-> GH
    GW -. optional aggregation .-> GL
    GW -. optional aggregation .-> FI
    GW -. optional aggregation .-> HT
    GW -. optional aggregation .-> GD

    GH --> SEC
    GL --> SEC
    HT --> SEC
```

The aggregate gateway may remain for compatibility, while dedicated endpoints let a client attach only the capabilities it needs.

## Design principles

- No process-global current account/project/provider state.
- Explicit selectors such as `profile_id` and `project_id`.
- Provider secrets are resolved internally and are never model-visible.
- Infisical machine identities replace scattered provider credentials.
- Connectors should fail and deploy independently.
- Provider-side permissions remain authoritative; Koba adds guardrails.
- Shared libraries are preferred over duplicated provider logic.
- Files are the user-facing concept; immutable artifact IDs can remain an internal/public compatibility primitive.
- Migrations are incremental: old credential env variables remain until each secret reference is accepted in production.
