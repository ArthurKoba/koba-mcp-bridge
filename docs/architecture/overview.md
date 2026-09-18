# Architecture overview

## Current state

Today, `koba-mcp-bridge` is both the public MCP gateway and the runtime for several local integration surfaces.

```mermaid
flowchart LR
    C[ChatGPT / MCP clients] -->|OAuth + MCP| B[koba-mcp-bridge]

    B --> GH[GitHub modules]
    B --> GL[GitLab subserver]
    B --> HTTP[curl / HTTP tools]
    B --> FILES[artifact/file service]
    B --> GA[Ghidra adapters]
    B -->|mounted MCP| GHMCP[ghidra-mcp]

    GH --> GitHub[GitHub API]
    GL --> GitLab[GitLab instances]
    HTTP --> Internet[HTTP endpoints]
    FILES --> Store[(artifact storage)]
    GHMCP --> Ghidra[Ghidra workers]
```

This model is operational, but several unrelated integration surfaces share one Python process and one deployment lifecycle. A startup or deployment regression in one surface can therefore reduce access to otherwise healthy tools.

## Direction

The target direction is a modular Koba integration platform: shared code and one repository are acceptable, but runtime failure domains should be separated.

```mermaid
flowchart TB
    Client[ChatGPT / MCP clients]

    subgraph Public["Public MCP entry points"]
      GW[gateway-mcp]
      GHEP[github-mcp]
      GLEP[gitlab-mcp]
      FEP[files-mcp]
      HEP[http-mcp]
      AEP[agents-mcp]
      GDEP[ghidra-mcp]
    end

    Client --> GW
    Client --> GHEP
    Client --> GLEP
    Client --> FEP
    Client --> HEP
    Client --> AEP
    Client --> GDEP

    GW -. optional aggregation .-> GHEP
    GW -. optional aggregation .-> GLEP
    GW -. optional aggregation .-> FEP
    GW -. optional aggregation .-> HEP
    GW -. optional aggregation .-> AEP
    GW -. optional aggregation .-> GDEP

    CP[Koba control plane / dashboard]
    SM[Secret manager]
    IDP[Future shared IdP / SSO]

    CP --> SM
    IDP -. future authentication .-> CP
    IDP -. future authentication .-> Public

    GHEP --> SM
    GLEP --> SM
    HEP --> SM
    AEP --> SM
```

The aggregate gateway remains useful for clients that want a broad tool catalog, but individual endpoints allow different clients or agents to attach only the capabilities they need.

## Design principles

- No process-global "current account", "current project", or "current provider" state.
- Explicit selectors such as `profile_id` and `project_id` are preferred.
- Secrets should not be stored in repository configuration or model-visible context.
- Connectors should fail independently.
- Provider-side permissions remain authoritative; Koba policy is an additional guardrail.
- Shared libraries are preferred over duplicated connector logic.
- Public names should describe user intent; internal storage terminology can remain implementation-specific.
- Documentation should describe both current state and intended boundaries until migration is complete.

## Near-term architectural questions

The repository intentionally does not finalize these decisions yet:

- secret manager selection and deployment model;
- control-plane/dashboard data model;
- common SSO/IdP adoption;
- final runtime packaging boundaries;
- whether the aggregate gateway remains enabled for all clients;
- artifact-service public naming and migration toward a Files surface;
- agent runtime boundaries;
- Camera Manager ownership and protocol model.

Each question should be resolved through a focused issue and, where architectural impact is significant, an ADR.
