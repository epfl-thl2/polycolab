<!-- prettier-ignore -->
!!! info
    This page is AI generated.

# Account and security

## Create or access your account

Use [Create account](/signup) for a built-in account, or the sign-in method offered by your deployment.
The deployment administrator controls available registration and identity-provider options.

## Review your identity

Open [Profile](/profile) to inspect your public identity and contributions.
After sign-in, this shortcut opens your canonical `/profiles/{username}` page, which you can share.
Built-in accounts use their login username. With organizational OIDC sign-in, choose an available Polycolab username the first time you sign in.
Your username identifies your account in project membership and attributed agent-library content. It currently cannot be renamed.

## Protect agent credentials

Agent API keys are separate from browser sessions.
Use the key’s actions menu to reveal or copy its secret.
Prefer your agent tool's secret setting.
If you share a key in agent chat, it may remain in chat history.
Never put it in URLs, project files, or logs.
Revoke a key from Settings when it is no longer needed.

## Configure built-in agents

Open **Settings → Model providers** to manage your AI providers.
Select **Add AI provider**, enter a display name, API endpoint, model ID, and API key, then select **Save provider**.
Use a provider’s actions menu to test its connection, replace its API key, or delete it.
Connection test results apply to the current page visit. Full provider keys are never shown again. A masked preview helps you recognize each saved key.
Older keys show **Preview unavailable** until you replace them.
