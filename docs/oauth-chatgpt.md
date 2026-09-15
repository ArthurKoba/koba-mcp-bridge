# ChatGPT OAuth flow

The production bridge uses GitHub OAuth through FastMCP with a deliberately narrow client policy:

- Dynamic Client Registration (DCR) is enabled.
- Client ID Metadata Documents (CIMD) are disabled.
- FastMCP's intermediate consent page is skipped because ChatGPT already presents consent to the user.
- The only allowed OAuth client redirect URI is `https://chatgpt.com/connector_platform_oauth_redirect`.
- GitHub remains the identity provider, and `OAUTH_ALLOWED_GITHUB_USERS` remains the final user allowlist.

The GitHub OAuth application's callback URL remains:

```text
https://mcp-bridge.koba-nexus.ru/auth/callback
```
