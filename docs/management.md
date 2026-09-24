# Account management

The management service is the private account, credential and lightweight telemetry
service for MCP Bridge. It is part of the same source repository and runs as its own
container so provider runtimes do not share a SQLite connection or encryption key.

## Responsibilities

The management service owns only:

- GitHub and GitLab account metadata;
- encrypted provider credentials;
- account lookup by UUID or human-readable alias;
- connection verification;
- recent MCP invocation metadata;
- the private Starlette Admin interface.

It does not implement GitHub or GitLab repository operations. Those remain in their
provider modules.

## Storage

Production storage is one persistent SQLite database on the historical
`/control-plane` data mount. SQLAlchemy is the persistence adapter and Alembic is the
schema migration authority. The database is owned only by the `management` process.

The storage path and `control-plane-data` volume name are retained during the live
migration so existing data does not need to move again merely for naming cleanup.

Credential plaintext is encrypted with Fernet before persistence. The Fernet master key is
a deployment bootstrap secret and is never stored in SQLite.

## Account model

Every account has a stable UUID and a unique alias. MCP clients use `account_id`; the
selector may be the UUID or the alias.

GitHub accounts use `github_app` authentication and a role of `development` or
`reviewer`. `external_id` stores the GitHub App ID and the encrypted credential stores
the App private key.

GitLab accounts use the `general` role and one of `private_token`, `bearer` or
`job_token`. `base_url` is stored per account, so gitlab.com and self-hosted GitLab
instances use the same contract. TLS verification and an optional CA certificate PEM are
also per account.

## Internal API

Provider runtimes authenticate with `MANAGEMENT_SERVICE_TOKEN`. The internal API lets
runtimes list public account metadata, resolve one credential for an explicit provider and
role, and append telemetry events. It never exposes an account-management mutation API to
MCP runtimes.

## Admin

Starlette Admin is mounted at `/admin` inside the private management runtime and
reverse-proxied by the public gateway at the same `/admin` path. Admin login is
configured with deployment bootstrap settings. The credential field is write-only in the
UI: existing ciphertext and plaintext are excluded from list/detail surfaces; leaving the
field blank while editing keeps the existing credential. The admin home dashboard shows
active/GitHub/GitLab account counts, total MCP calls, errors and average duration.

## Telemetry

FastMCP middleware records only:

- request id when available;
- module and tool name;
- selected account id;
- provider;
- success/error;
- duration;
- exception type on failure.

Tool argument values are deliberately not persisted.

## Coolify bootstrap

The old Infisical provider/account registry is removed. Configure the management bootstrap
and gateway OAuth secrets in the deployment environment:

```text
MANAGEMENT_ENCRYPTION_KEY=<Fernet key>
MANAGEMENT_SERVICE_TOKEN=<random internal token>
MANAGEMENT_ADMIN_USERNAME=admin
MANAGEMENT_ADMIN_PASSWORD=<strong password>
MANAGEMENT_SESSION_SECRET=<random session secret>
MANAGEMENT_SESSION_HTTPS_ONLY=true

GITHUB_OAUTH_CLIENT_ID=<gateway OAuth app id>
GITHUB_OAUTH_CLIENT_SECRET=<gateway OAuth secret>
GITHUB_OAUTH_JWT_SIGNING_KEY=<gateway signing key>
GITHUB_OAUTH_ALLOWED_USERS=<comma-separated logins>
```

During the live rename, Compose accepts existing `CONTROL_PLANE_*` deployment values as
fallbacks. New configuration should use the `MANAGEMENT_*` names.

After deployment, create provider accounts through the private admin UI instead of adding
provider credentials to Coolify environment variables.

The public deployment uses a single origin, `https://mcp.koba-nexus.ru`. No separate
admin subdomain is required.
