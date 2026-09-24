# MCP management

The private `management` runtime owns provider accounts, encrypted credentials, MCP invocation history, Files administration and the Starlette Admin console. Provider runtimes never open the management database directly.

## Storage

Management owns a persistent SQLite database at `/management/management.sqlite3` on the `management-data` volume. SQLAlchemy is the persistence adapter. The project is currently deployed against an empty database, so the schema is created from current metadata at startup; there is no legacy migration compatibility layer.

Credentials are encrypted with Fernet before persistence. The master key is a deployment bootstrap secret and is never stored in SQLite.

## Provider accounts

Account roles do not exist. Every account has a stable UUID and a provider-local unique alias. MCP calls select accounts explicitly by UUID or alias.

### GitHub

GitHub has a dedicated account table and admin view. The public API URL is fixed to `https://api.github.com`. Supported auth types are:

- `github_app`: App ID plus encrypted private-key PEM;
- `github_token`: encrypted PAT/user token, with no App ID requirement.

### GitLab

GitLab has a separate account table and admin view. Each account stores its own `base_url`, so `gitlab.com` and self-hosted instances use the same runtime contract. Supported auth types are `private_token`, `bearer` and `job_token`; TLS verification and an optional custom CA PEM are per account.

## MCP account selection and permissions

Provider tool catalogs are static. Adding, disabling or removing an account never adds or removes GitHub/GitLab tools. Account-scoped calls always accept `account_id`; if the selector is missing, disabled, inaccessible or insufficiently privileged, that call returns a runtime/provider error.

Discovery is explicit:

- GitHub: `github_accounts` lists all configured identities (including disabled accounts) and potential capability classes; `github_account_capabilities` reports GitHub-App permission ceilings and optionally repository-effective permissions. User-token account-global permissions are reported as unknown when GitHub does not expose a reliable global map.
- GitLab: `accounts` lists all configured identities (including disabled accounts) and potential capability classes; `account_capabilities` reports PAT scopes when the server exposes `/personal_access_tokens/self` and optionally project-level access. Other token types are explicitly reported as project/resource dependent.

These capability tools are informational. Provider authorization remains authoritative at invocation time.

## Internal API

Private runtimes authenticate with `MANAGEMENT_SERVICE_TOKEN`. The internal API lists public account metadata, resolves one credential for an explicit provider/account selector, and accepts invocation events. It does not expose account mutation to MCP runtimes.

## Admin

The gateway exposes the private Starlette Admin surface at `/admin` on the main MCP origin. The console contains:

- separate GitHub Accounts and GitLab Accounts sections;
- write-only credential replacement and connection tests;
- MCP invocation history including captured arguments/results/errors;
- Settings for logging enable/disable, payload capture, retention/max-record limits, Files auto-cleanup and maintenance cadence;
- a Files section for search/inspection, upload, download, guarded deletion, cleanup preview and manual cleanup.

## Invocation logging

Tool-call logging is best-effort and never makes a successful MCP call depend on management availability. Payload capture is bounded and can be disabled independently. Sensitive structured fields such as authorization headers, cookies, tokens, passwords, secrets, private keys and API keys are redacted before an event is sent to management.

Retention is enforced both while appending events and by the periodic management maintenance task. Logs can also be cleared or retention can be applied immediately from Admin.

## Files lifecycle

Management mounts the same `files-data` volume used by the Files/Curl runtimes and uses the canonical `FileStore`, not a second storage implementation. Automatic cleanup is disabled by default and only removes old unreferenced files. The same cleanup can be previewed and triggered manually from Admin.

## Coolify bootstrap

Dynamic provider credentials do not belong in deployment environment variables. Production bootstrap requires:

```text
MANAGEMENT_DATABASE_PATH=/management/management.sqlite3
MANAGEMENT_ENCRYPTION_KEY=<Fernet key>
MANAGEMENT_SERVICE_TOKEN=<random internal token>
MANAGEMENT_ADMIN_USERNAME=admin
MANAGEMENT_ADMIN_PASSWORD=<strong password>
MANAGEMENT_SESSION_SECRET=<random session secret>
MANAGEMENT_SESSION_HTTPS_ONLY=true
```

Gateway OAuth remains deployment configuration (`GITHUB_OAUTH_*`). Provider accounts are created through `/admin`.
