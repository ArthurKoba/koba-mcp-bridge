# mcp-bridge

Extensible MCP gateway for AI agents, local tools, isolated compute workers, development automation, and reverse-engineering workflows.

## Purpose

`mcp-bridge` is a modular MCP platform with one authenticated edge gateway and isolated provider/runtime processes.

The project is designed around a few core ideas:

- expose local and self-hosted tools through one MCP endpoint;
- aggregate other MCP servers behind a single OAuth boundary;
- keep long-running or compute-heavy work outside the chat process;
- persist task state, logs, files, and errors so work can survive interrupted sessions;
- isolate workers and constrain CPU, memory, storage, network, and filesystem access;
- make integrations modular so new development and analysis tools can be added over time.

## Documentation

The documentation entry point is [docs/README.md](docs/README.md). It links the current
architecture map, component catalog, repository map, roadmap, existing technical notes,
and future architecture decision records.

The repository is already split into independent source packages and runtime services.
The gateway package stays intentionally small; provider implementations live in their
own packages.

## Repository layout

```text
src/
├── bridge/
├── common/
├── management/
└── modules/
    ├── github/
    ├── gitlab/
    ├── files/
    ├── curl/
    └── analysis/
```

## Architecture

```text
ChatGPT / MCP clients
        |
        | OAuth + MCP
        v
gateway
        |
        +-- github   (private)
        +-- gitlab   (private)
        +-- files    (private)
        +-- curl     (private)
        +-- analysis (private)
                              |
                              +-- ghidra-mcp (native/private)
```

The gateway is the only public process. It exposes both an aggregate MCP and dedicated
authenticated surfaces:

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

Deploying or restarting one private runtime does not require restarting the others.
The raw Ghidra MCP remains native and is available directly at `/ghidra/mcp`; Analysis remains the terminology facade over the same backend.

## Files service

MCP Bridge provides one universal persistent file service for every backend and worker.
Files are immutable and content-addressed. The public identifier is:

```text
sha256:<digest>
```

Physical storage paths are private implementation details and are never used as
cross-service identifiers.

For client/chat attachments, agents should call `file_ingest` with the
attachment/file argument itself. The tool marks `file` in
`_meta["openai/fileParams"]`, so ChatGPT supplies a structured file payload
containing `download_url`, `file_id`, and optional MIME/name metadata. MCP Bridge
streams the authorized temporary URL directly into canonical storage and returns
`file_id`. Attachment bytes never need to be serialized through
model-visible base64.

For generic MCP clients that cannot provide a file-capable argument, MCP Bridge also
provides a resumable fallback protocol:

- `file_upload_begin` creates an upload session from file metadata;
- `file_upload_write` appends one bounded base64 chunk at the exact next offset;
- `file_upload_list` enumerates open/completed sessions for autonomous recovery;
- `file_upload_status` resumes interrupted transfers from the server-confirmed offset;
- `file_upload_finish` verifies size and optional SHA-256, commits the immutable
  object, and returns its `file_id`;
- `file_upload_cleanup` previews or removes stale upload-session state by age without deleting committed files;
- `file_upload_cancel` discards a specific unfinished transfer.

The protocol is transport-only. The agent does not choose a MCP Bridge filesystem path
and no backend-specific directory participates in upload. After commit, every
consumer receives only the immutable `file_id`.

The generic file surface also provides:

- `file_status`, `file_list`, `file_info`, `file_read`;
- `file_create_text`;
- `file_extract`, `file_collection_list`,
  `file_collection_resolve`, `file_collection_delete`;
- `file_references`, `file_release_reference`;
- `file_delete`, `file_gc`.

Archive extraction creates a collection manifest whose members are themselves
immutable files. The same object can therefore be reused by multiple
projects, workers, and backends without copying it again in the file store.

Consumers hold durable references to source files. Normal deletion refuses
to remove referenced objects; garbage collection only targets objects with no
consumer or collection references.

## Web tools

`/web/mcp` currently exposes the structured curl tools. The Web surface is intentionally broader than curl so browser automation, Selenium and persistent web sessions can be added later without changing the public endpoint.

The structured curl tools use the `chrome-desktop` HTTP header preset by
default. This applies to `curl_request`, `curl_download`, and
`curl_stream_capture`, so ordinary requests present a current desktop Chrome
User-Agent and matching browser navigation headers unless the caller selects a
different preset.

Use `preset="curl"` for native curl-style defaults, `preset="json-api"` for
JSON APIs, or `preset="none"` when only explicitly supplied headers should be
sent. Caller-provided headers always override preset headers.

Browser presets reproduce HTTP request headers only. They do not emulate Chrome
JavaScript execution, cookies/session state beyond what the caller supplies,
TLS fingerprints, or browser HTTP/2 settings.

## Analysis and Ghidra boundary

Native `ghidra-mcp` remains an independent private backend and keeps its canonical
tool names, argument names and implementation unchanged.

The Analysis runtime is intentionally thin. It reads the live Ghidra MCP tool catalog
and creates an Analysis-facing facade dynamically rather than reimplementing Ghidra
operations. Tool descriptions and selected domain terms are exposed using the
behavior-analysis vocabulary used by the project.

Argument compatibility is handled in the Analysis adapter with Pydantic-backed dynamic
models. The preferred public names are the Analysis aliases (for example
`action_name`, `inbound_actions`, `low_level_view`); legacy Ghidra argument names
remain accepted as a compatibility fallback. If both forms are supplied, the Analysis
alias takes precedence. Before dispatch, the adapter always normalizes the payload back
to the canonical Ghidra argument keys and calls the original Ghidra tool.

This keeps one implementation of the actual analysis behavior: Ghidra. MCP Bridge owns
only the facade, terminology mapping, validation and result-envelope normalization.

## Account management

GitHub and GitLab accounts are managed by the private `management` runtime. The
management service owns a persistent SQLite database through SQLAlchemy. The current zero-state schema is created directly at startup; provider runtimes never read the database directly and use an authenticated internal HTTP API.

Account metadata and credentials are separate concerns. Credentials are encrypted before
they are written to SQLite using a deployment Fernet master key. Plaintext credentials
are returned only to authenticated private runtimes for the explicitly selected
`account_id`; they are never exposed by MCP tools or the admin list/detail views.

Starlette Admin is owned by the private management runtime and reverse-proxied by the gateway at `/admin` on the same public origin. GitHub and GitLab accounts have separate management surfaces. The console also provides write-only credential replacement, connection verification, MCP call logging controls/history, and Files inspection/upload/download/cleanup.

See [docs/management.md](docs/management.md).

## GitLab connector

GitLab account selection is explicit. Each GitLab MCP operation accepts `account_id`,
which can be either the stable account UUID or its unique human-readable alias.

A GitLab account stores:

- alias;
- arbitrary HTTP(S) `base_url`, including self-hosted GitLab and URL prefixes;
- auth mode: `private_token`, `bearer` or `job_token`;
- encrypted token;
- TLS verification flag and optional custom CA certificate PEM.

There is no process-global current GitLab account. Concurrent agents can safely use
different accounts or servers without switching shared process state. GitLab tool registration is also static. `accounts` lists configured identities and potential capability classes; `account_capabilities` reports PAT scopes when GitLab exposes them and can additionally report project-level access for a selected project.

## GitHub provider accounts

GitHub provider identities are explicit accounts with no application-defined role. An account can authenticate either as a GitHub App (`github_app`) or with a personal/user token (`github_token`). GitHub App accounts store the App ID as `external_id` and encrypt the App private key; token accounts encrypt the token and do not require an App ID. Repository installation access remains GitHub's source of truth for App accounts.

All account-scoped GitHub tools require `account_id`. Tool registration is static: an account being absent, disabled, or under-privileged never removes tools from the catalog; the individual call returns the provider/runtime error instead. `github_accounts` lists configured identities with potential capability classes, while `github_account_capabilities` reports provider-visible account permissions and can additionally inspect repository-effective rights.

GitHub Enterprise Server API URLs are intentionally not enabled by the current account
contract. GitHub provider accounts target `https://api.github.com`.

## GitHub OAuth

GitHub OAuth protects the public MCP gateway and is deployment bootstrap configuration,
not a provider account. Configure:

```text
GITHUB_OAUTH_CLIENT_ID
GITHUB_OAUTH_CLIENT_SECRET
GITHUB_OAUTH_JWT_SIGNING_KEY
GITHUB_OAUTH_ALLOWED_USERS
```

Dynamic provider account credentials do not live in deployment environment variables.

## Invocation telemetry

Private runtimes register a lightweight FastMCP middleware. Each tool call may append a best-effort event containing module/tool name, selected account, provider, duration, status, error details and bounded argument/result payloads. Sensitive structured fields such as authorization headers, cookies, tokens, passwords, secrets and private keys are redacted before transport.

The management Settings page can disable logging, disable payload capture, configure retention/max records and trigger cleanup. Telemetry uses a bounded background task set and does not block a successful tool call if the management service is slow or unavailable.

## Project status

The bridge is operational as an authenticated MCP gateway with isolated provider runtimes,
a persistent account management service, explicit multi-account GitHub/GitLab selection, Files
storage, structured curl and the Analysis facade over native Ghidra.

## License

MIT
