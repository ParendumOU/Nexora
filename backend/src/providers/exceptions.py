"""Provider exception hierarchy."""


class ProviderError(Exception):
    pass


class RateLimitError(ProviderError):
    """Rate-limit signal. Optional cooldown_seconds overrides the provider default."""

    def __init__(self, message: str = "", cooldown_seconds: int | None = None):
        super().__init__(message)
        self.cooldown_seconds = cooldown_seconds


class AllProvidersExhausted(ProviderError):
    pass
