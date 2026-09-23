# Repository map

```text
mcp-bridge/
├── .github/
├── docs/
├── src/
│   ├── mcp_bridge/       # thin public gateway only
│   ├── mcp_common/       # shared runtime + secrets primitives
│   ├── github_mcp/       # GitHub provider runtime
│   ├── gitlab_mcp/       # GitLab provider runtime
│   ├── files_mcp/        # persistent Files runtime
│   ├── http_mcp/         # HTTP/curl runtime
│   └── analysis_mcp/     # analysis/Ghidra adapter runtime
├── tests/
│   ├── mcp_bridge/
│   ├── mcp_common/
│   ├── github_mcp/
│   ├── gitlab_mcp/
│   ├── files_mcp/
│   ├── http_mcp/
│   └── analysis_mcp/
├── Dockerfile
├── docker-compose.yaml
├── docker-entrypoint.sh
├── otel-collector.yaml
├── pyproject.toml
└── README.md
```

## Gateway

`src/mcp_bridge/` contains only version metadata and the public gateway composition.
It proxies the private runtimes and owns OAuth/public HTTP surfaces.

## Shared layer

`src/mcp_common/` contains shared runtime helpers, tool annotations and the Infisical
secret resolver. Provider-specific behavior does not belong here.

## Runtime packages

Every runtime package owns its implementation and its `runtime.py` entry point:

- `github_mcp.runtime`
- `gitlab_mcp.runtime`
- `files_mcp.runtime`
- `http_mcp.runtime`
- `analysis_mcp.runtime`

The production Compose file in the repository root is the single deployment definition.
There is no separate local/development Compose and no `deploy/` source tree.
