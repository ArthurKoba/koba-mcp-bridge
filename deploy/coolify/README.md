# Coolify split deployment

Production should run MCP Bridge as independent Coolify applications rather than one
Docker Compose application. The repository still keeps `docker-compose.yaml` as a
local/integration topology, but production deployment ownership is per runtime.

This preserves the OAuth gateway as a stable edge while allowing GitHub, GitLab, Files,
Web/curl, Analysis, Ghidra and Management to rebuild/restart independently.

## Shared Dockerfile targets

Create one Coolify Dockerfile application per row, all from this repository and branch.
Set the Dockerfile to `Dockerfile`, the target build stage to the value below, and the
custom internal name to the listed hostname.

| Application | Docker target | Internal name | Persistent storage |
| --- | --- | --- | --- |
| gateway | `gateway` | `gateway` | `fastmcp-data:/data/fastmcp` |
| management | `management` | `management` | `management-data:/management`, `files-data:/files` |
| github | `github` | `github` | none |
| gitlab | `gitlab` | `gitlab` | none |
| files | `files` | `files` | `files-data:/files` |
| curl | `curl` | `curl` | `files-data:/files` |
| analysis | `analysis` | `analysis` | none |
| ghidra | `ghidra` | `ghidra` | none |

All applications must join the same Coolify network. Only gateway receives the public
MCP domain/host port. The provider runtimes are private and are reached by their stable
internal names.

The native Ghidra backend remains external to this repository and must remain reachable
from the `ghidra` runtime as configured by `GHIDRA_MCP_URL`.

## Watch paths

Configure Coolify Watch Paths per application so an unrelated commit does not trigger
that application's deployment.

Every application watches:

```text
Dockerfile
docker-entrypoint.sh
pyproject.toml
src/common/**
```

Add the runtime-specific paths:

```text
gateway:
  src/bridge/**

management:
  src/management/**
  src/modules/files/**

github:
  src/modules/github/**

gitlab:
  src/modules/gitlab/**

files:
  src/modules/files/**

curl:
  src/modules/curl/**
  src/modules/files/**

analysis:
  src/modules/analysis/**

ghidra:
  src/modules/ghidra/**
```

A `src/common/**` or dependency/Dockerfile change intentionally redeploys every runtime,
because those files are shared runtime authority. A provider-only change redeploys only
that provider.

## Availability model

Gateway does not require provider containers to be running in order to start. Backend
catalog/call failures are isolated and reported for the selected backend. Management
availability is also runtime-resolved; a provider can stay running while Management is
restarted, although account-scoped calls will fail until Management returns.

This means a GitHub deployment should not interrupt GitLab, Files, Analysis or the root
gateway surface. A Management deployment should affect the Admin page and account
resolution, not restart the MCP edge.

## Build cache

The Dockerfile installs third-party dependencies before copying source code. As a result,
ordinary source changes no longer invalidate `uv sync`. Each target then copies only
`src/common` plus the source owned by that runtime.

Do not enable Coolify "Disable Build Cache" for normal deployments. Keep "Include Source
Commit in Build" disabled unless the image content must embed the commit through a
separate cache-safe mechanism.

## Health/readiness

Every runtime image has a TCP healthcheck for port 8000. Configure Coolify health checks
to honor container readiness before replacing public gateway traffic. Provider health
does not gate gateway startup.
