# koba-mcp-bridge

Extensible MCP gateway for AI agents, local tools, isolated compute workers, development automation, and reverse-engineering workflows.

## Purpose

`koba-mcp-bridge` is the single authenticated MCP entry point for tools and workloads running on user-owned infrastructure.

The project is designed around a few core ideas:

- expose local and self-hosted tools through one MCP endpoint;
- aggregate other MCP servers behind a single OAuth boundary;
- keep long-running or compute-heavy work outside the chat process;
- persist task state, logs, artifacts, and errors so work can survive interrupted sessions;
- isolate workers and constrain CPU, memory, storage, network, and filesystem access;
- make integrations modular so new development and analysis tools can be added over time.

## Architecture

```text
AI client / MCP client
        |
        | OAuth + MCP
        v
koba-mcp-bridge
        |
        +-- local bridge_* tools
        +-- ghidra_* -> optional Ghidra MCP backend
        +-- future mounted MCP backends
        +-- task/state management
        +-- workers / artifacts / automation
```

Mounted MCP backends are optional. The public bridge starts normally when none are configured. FastMCP proxy providers connect lazily, so a temporarily unavailable backend does not prevent the gateway itself from starting.

## Ghidra backend

Set the runtime variable below to mount an internal Ghidra MCP server:

```text
GHIDRA_MCP_URL=http://ghidra-mcp:8081/mcp
```

The mounted backend is namespaced as `ghidra`, so its tools are exposed through the public gateway with `ghidra_` prefixes. Ghidra itself does not need to be exposed publicly; it should share a private Docker network with this bridge.

## GitHub OAuth

OAuth is disabled by default so a deployment can be upgraded before credentials are configured. When `OAUTH_ENABLED=true`, the bridge requires all of the following runtime environment variables:

- `OAUTH_GITHUB_CLIENT_ID`
- `OAUTH_GITHUB_CLIENT_SECRET`
- `OAUTH_JWT_SIGNING_KEY`
- `OAUTH_ALLOWED_GITHUB_USERS`

The public OAuth base URL defaults to:

```text
https://mcp.koba-nexus.ru
```

and can be changed with `OAUTH_BASE_URL`.

The GitHub OAuth application callback URL is:

```text
https://mcp.koba-nexus.ru/auth/callback
```

OAuth client registrations and token state are stored below `FASTMCP_HOME`, which defaults to `/data/fastmcp` in the container. Production deployments should mount `/data/fastmcp` as persistent storage before enabling OAuth.

Secrets belong in runtime environment variables or the deployment secret store. They must not be committed to the repository or injected at image build time.

## Project status

The bridge is operational as an authenticated MCP gateway. Backend integrations and worker interfaces are still evolving.

## License

MIT
