# Repository map

This is a navigation guide for the current repository, not a permanent package layout.

## Top level

```text
koba-mcp-bridge/
├── .github/              GitHub CI/CD and collaboration policy
├── deploy/               deployment/runtime support files
├── docs/                 architecture and operational documentation
├── src/koba_mcp_bridge/  current Python implementation
├── tests/                unit/integration tests
├── Dockerfile
├── docker-compose.yaml
├── pyproject.toml
└── README.md
```

## Current Python areas

### Secrets

- `secrets.py` — secret references, Infisical Universal Auth and internal resolver.
- `secrets_tools.py` — redacted MCP diagnostics; never returns plaintext values.

### Server composition

- `server.py` — FastMCP composition, OAuth boundary, local registration, mounted backends and HTTP app wiring.

### Files/file data plane

- `file_store.py` — immutable object storage, metadata, collections and references.
- `file_ingress.py` — attachment/file ingress and resumable uploads.
- `file_tools.py` — MCP surface for file/file operations.

### HTTP

- `curl_tools.py` — structured curl execution, downloads and stream capture.
- `curl_mcp_tools.py` — MCP registration.

### GitHub

The GitHub surface is already split across multiple modules:

- `github_agent.py` and `github_identity.py` — GitHub App identities/client primitives.
- `github_workflow.py`, `github_tools.py` — development workflows.
- `github_review*.py`, `github_reviewer*.py` — review/reviewer identity.
- `github_actions*.py` — Actions diagnostics/control.
- `github_history*.py` — commit/history operations.
- `github_collab*.py` — collaboration/review thread operations.
- `github_admin.py` — administrative helper logic.

This is a natural candidate for packaging behind an independent runtime entry point without rewriting all provider logic.

### GitLab

- `gitlab_client.py` — REST client, multi-profile registry and policy guards.
- `gitlab_tools.py` — reusable MCP tool provider.
- The GitLab tool provider is currently both mounted into the main gateway namespace and exposed through a dedicated sub-endpoint.

### Ghidra integration

- `reverse_workflow.py` — high-level file/file ↔ Ghidra adapter workflows.
- The actual Ghidra MCP runtime lives in its own repository/service.

## Tests

Tests currently live in one directory and generally follow implementation modules. As runtime services split, the repository should define a clear convention for shared tests, connector-specific tests and end-to-end acceptance tests.

## Repository direction

A likely future monorepo shape is:

```text
src/
├── koba_common/
├── gateway/
├── secrets/
└── connectors/
    ├── github/
    ├── gitlab/
    ├── files/
    ├── http/
    └── ghidra/
```

This is a working direction, not an approved migration plan. The split should be performed incrementally with compatibility tests.
