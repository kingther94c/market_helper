# IBKR Web API Auth Notes

## Recommended Path for This Repo
- For individual IBKR accounts, use the local Client Portal Gateway / IB Gateway path first.
- Put your IBKR username in `provider.username`.
- Keep the password out of the config file. Store it in the environment variable named by `provider.password_env_var` such as `IBKR_CP_PASSWORD`.
- Point `provider.web_api_base_url` to your local gateway, typically `https://localhost:5000/v1/api`.

## When OAuth / API Key Matters
- `oauth_consumer_key_env_var` is only relevant when you are using an approved OAuth flow, which is more common for institutional or third-party integrations.
- If you are just connecting your own individual account, you usually do not need to go fetch an API key before starting the Client Portal Web API flow.

## Suggested Local Setup
1. Copy the structure from `configs/settings.example.json` into your local settings file.
2. Fill `provider.account_id` with your IBKR account id such as `U1234567`.
3. Fill `provider.username` with your IBKR login username.
4. Export your password in the shell: `export IBKR_CP_PASSWORD='your-password'`
5. Launch the local IBKR gateway and complete the normal login / 2FA flow there.

## Current Repo Boundary
- The repo now records where username and credential env-var names belong.
- Automated credential submission is still intentionally out of scope until we add a real HTTP transport and decide whether to keep login manual through the local gateway session.
