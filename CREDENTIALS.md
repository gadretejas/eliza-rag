# POC Credentials

> **These are demo credentials for local development only. Do not use in production.**

| Role | Email | Password | Corpus access |
|---|---|---|---|
| admin | admin@example.com | admin-pass-123 | All 54 companies |
| analyst | analyst@example.com | analyst-pass-123 | All 54 companies |
| viewer | viewer@example.com | viewer-pass-123 | AAPL, MSFT, NVDA, GOOG, AMZN |

## Role differences

- **admin** — full corpus, all models, no rate limit, can manage users via the Admin panel
- **analyst** — full corpus, all models, 200 requests/hour
- **viewer** — restricted to 5 tickers above, `gpt-5.4-mini` only, 20 requests/hour

## Changing passwords

Use the Admin panel (sign in as admin → sidebar → Admin) to create new users or deactivate existing ones.
