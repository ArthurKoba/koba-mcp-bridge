# Infisical integration

Production Infisical is deployed as the native one-click Infisical Service in Coolify.
The repository does not own a second Compose definition for that service.

Koba only needs the runtime bootstrap:

```text
INFISICAL_HOST=https://secrets.koba-nexus.ru
INFISICAL_PROJECT_ID=<project UUID>
INFISICAL_ENVIRONMENT=prod
INFISICAL_BASE_PATH=/
INFISICAL_CLIENT_ID=<machine identity client id>
INFISICAL_CLIENT_SECRET=<machine identity client secret>
INFISICAL_VERIFY_TLS=true
```

Provider-specific credentials and configuration live inside Infisical below the base
path and are resolved by convention.

Current layout:

```text
/github/development
  APP_ID
  PRIVATE_KEY_PEM

/github/reviewer
  APP_ID
  PRIVATE_KEY_PEM

/github/oauth
  CLIENT_ID
  CLIENT_SECRET
  JWT_SIGNING_KEY
  ALLOWED_USERS

/gitlab/accounts/<profile_id>
  BASE_URL
  AUTH_TYPE
  TOKEN
  LABEL        # optional
  VERIFY_TLS   # optional
  CA_FILE      # optional
```

The Koba machine identity uses Universal Auth with Viewer access to the project.
Access tokens are short-lived; the bootstrap client secret remains in the deployment
system because it is required to authenticate to Infisical itself.

MCP diagnostics must never return plaintext secret values.
