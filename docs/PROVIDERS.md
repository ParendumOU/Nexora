# LLM Provider System

## Philosophy

AgenticChats does **not** require API keys. Instead it uses OAuth tokens from your existing subscriptions (Claude.ai, Google One / Gemini Advanced, OpenAI Plus). API keys are supported as a fallback for power users.

## Supported Providers

| Provider | Auth Method | Rate Limit Strategy |
|---------|------------|-------------------|
| Claude (Anthropic) | OAuth session token | 60s cooldown on 429 |
| Gemini (Google) | Google OAuth2 access token | 60s cooldown on 429 |
| OpenAI (GPT / Codex) | OAuth or API key | 60s cooldown on 429 |
| Ollama | No auth (local URL) | Never rate-limited |
| Custom | Bearer / API key | Configurable |

## How to Obtain OAuth Tokens

### Claude (claude.ai)
1. Log in to claude.ai in your browser
2. Open DevTools → Application → Cookies → `anthropic-claude.ai`
3. Copy `sessionKey` value — this is your OAuth token
4. Paste into AgenticChats Settings → Providers → Claude

Alternatively, if you have the Claude CLI installed:
```bash
cat ~/.config/anthropic/auth.json  # contains access_token
```

### Gemini (gemini.google.com)
1. Install `gcloud` CLI and run `gcloud auth login`
2. Run `gcloud auth print-access-token`
3. Paste the access token into AgenticChats Settings → Providers → Gemini

The backend automatically refreshes expired Google tokens using the stored refresh_token.

### OpenAI (platform.openai.com)
1. Go to platform.openai.com → API Keys → Create key
2. Paste the key into AgenticChats Settings → Providers → OpenAI

## Fallback Chain

A **Provider Chain** is an ordered list of providers tried in sequence:

```yaml
default_chain:
  - claude          # primary: use Claude OAuth
  - gemini          # fallback 1: use Gemini OAuth  
  - openai          # fallback 2: use OpenAI key
  - ollama          # last resort: local model
```

When a provider returns 429 (rate limited):
1. Provider is marked as "cooling" for `cooldown_seconds` (default: 60)
2. Next provider in chain is tried immediately
3. If all providers are cooling: request is queued for `retry_after` seconds
4. Redis TTL automatically clears cooldown state

## Provider Router (Backend)

```python
class ProviderRouter:
    async def chat(self, messages, chain_id, **kwargs) -> AsyncIterator[str]:
        chain = await self.get_chain(chain_id)
        for provider in chain.providers:
            if await self.is_cooling(provider.id):
                continue
            try:
                async for chunk in provider.stream(messages, **kwargs):
                    yield chunk
                return
            except RateLimitError:
                await self.set_cooling(provider.id, provider.cooldown_seconds)
            except ProviderError as e:
                logger.warning(f"Provider {provider.name} failed: {e}")
        raise AllProvidersExhausted("No providers available")
```

## Rate Limit Detection

Each provider adapter catches its specific rate limit signals:

- **Claude**: HTTP 429, or `{"error": {"type": "rate_limit_error"}}`
- **Gemini**: HTTP 429, or `RESOURCE_EXHAUSTED` status  
- **OpenAI**: HTTP 429, or `{"error": {"type": "requests", "code": "rate_limit_exceeded"}}`
- **Ollama**: Never rate-limited (local), but can timeout (treated as transient error)

## Token Refresh

OAuth tokens expire. The backend handles refresh automatically:

```python
class ClaudeProvider:
    async def ensure_valid_token(self):
        if self.token_expires_at < utcnow() + timedelta(minutes=5):
            # attempt silent refresh; if fails, mark provider as needs-reauth
            await self.refresh_token()
```

Users are notified in the UI when a provider needs re-authentication.
