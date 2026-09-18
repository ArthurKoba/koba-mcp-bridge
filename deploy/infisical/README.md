# Infisical deployment for Koba

This directory contains the first Koba secrets-management deployment baseline.

It is intentionally a single-node stack: Infisical + PostgreSQL + Redis. PostgreSQL is
the durable source of truth. Redis is treated as regenerable cache/background state.

## Security boundary

Infisical stores provider credentials. Koba connectors should receive only a machine
identity bootstrap credential and resolve provider secrets at runtime.

Do not expose provider secret plaintext through MCP tools.

## 1. Prepare configuration

Copy `.env.example` to a local/deployment secret environment and generate:

```bash
openssl rand -hex 16
openssl rand -base64 32
openssl rand -base64 36
```

Use the outputs for `ENCRYPTION_KEY`, `AUTH_SECRET`, and `POSTGRES_PASSWORD`.

The encryption key is critical recovery material. Losing it can make encrypted Infisical
data unrecoverable. Back it up separately from the PostgreSQL database.

## 2. Deploy

For a local/private proof of concept:

```bash
docker compose --env-file .env -f deploy/infisical/compose.yaml up -d
curl --fail http://127.0.0.1:8080/api/status
```

For Coolify, deploy the same stack as a separate application/service and route
`https://secrets.koba-nexus.ru` to the Infisical container port 8080. Keep PostgreSQL
and Redis private.

Do not place Infisical inside the Koba MCP container. It must survive connector
redeployments independently.

## 3. Initial Infisical setup

Create the first administrator through the Infisical UI, then create:

- organization: `Koba`;
- secrets project: `Koba Platform`;
- environment: `prod`.

Initial folder convention:

```text
/
├── github/
│   ├── development/
│   ├── reviewer/
│   └── oauth/
├── gitlab/
│   └── accounts/
├── http/
└── bootstrap/
```

The folder list is a starting convention, not a requirement imposed by Infisical.

## 4. Create the Koba machine identity

Create a Machine Identity using Universal Auth, add it to the Koba Platform project,
and initially grant read access only to the folders required by the current bridge.

The bridge needs these bootstrap values:

```text
INFISICAL_HOST=https://secrets.koba-nexus.ru
INFISICAL_PROJECT_ID=<project id>
INFISICAL_CLIENT_ID=<machine identity client id>
INFISICAL_CLIENT_SECRET=<machine identity client secret>
INFISICAL_VERIFY_TLS=true
```

`INFISICAL_CLIENT_ID_FILE` and `INFISICAL_CLIENT_SECRET_FILE` are also supported for
mounted secret files.

These bootstrap credentials are the last secrets that need to remain in the runtime
deployment system. Provider tokens/keys should move to Infisical.

## 5. Migrate provider credentials incrementally

The Koba resolver supports:

```text
env://NAME
file:///run/secrets/name
infisical://prod/path/to/folder#SECRET_NAME
```

Examples:

```text
GITHUB_AGENT_PRIVATE_KEY_REF=infisical://prod/github/development#PRIVATE_KEY_PEM
GITHUB_REVIEWER_PRIVATE_KEY_REF=infisical://prod/github/reviewer#PRIVATE_KEY_PEM
OAUTH_GITHUB_CLIENT_SECRET_REF=infisical://prod/github/oauth#CLIENT_SECRET
OAUTH_JWT_SIGNING_KEY_REF=infisical://prod/github/oauth#JWT_SIGNING_KEY
```

GitLab profiles can use:

```json
{
  "profile_id": "gitlab-com-arthur",
  "base_url": "https://gitlab.com",
  "auth_type": "private_token",
  "secret_ref": "infisical://prod/gitlab/accounts/arthur#TOKEN"
}
```

Old environment/file credential fields remain supported during migration.

## 6. Verify before removing old credentials

After configuring the bootstrap identity and secret references:

1. call `secrets_status_tool(authenticate=true)`;
2. call `secrets_check_reference(...)` for each migrated reference;
3. verify GitHub/GitLab read operations;
4. verify a safe development write path;
5. only then remove the old provider secret from Coolify.

The diagnostics never return plaintext secret values.

## Backup baseline

Back up at minimum:

- PostgreSQL;
- `ENCRYPTION_KEY`;
- `AUTH_SECRET`;
- deployment configuration needed to recreate the stack.

Do not treat Redis as durable secret storage.
