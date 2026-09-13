"""
Token accounting for the model calls behind a chat turn or a mapping run.

Two SDKs report usage differently, so both are normalised into `TokenUsage`
before anything else sees them:

* the Anthropic SDK reports `input_tokens` *excluding* anything served from or
  written to the prompt cache, so the cached figures must be added back;
* LangChain's `usage_metadata` already folds them in, and splits the cache
  creation figure across per-TTL keys.

`input_tokens` here always means the full prompt, cached or not, so
`cache_read_tokens + cache_write_tokens` is the share of it that the prompt
cache accounted for.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# Anthropic bills a cached prefix at a fraction of the input rate on a hit, and
# at a premium when it is written. Used only to express the saving as tokens.
CACHE_READ_RATE = 0.1
CACHE_WRITE_RATE = 1.25

# Rough conversion for the one case where the real number is unavailable: a
# system prompt that was never cached (below the cacheable minimum, or caching
# switched off). Flagged as an estimate wherever it is used.
_CHARS_PER_TOKEN = 4


def approx_tokens(text: str) -> int:
    """Order-of-magnitude token count for a prompt, when no usage is reported."""
    return max(0, round(len(text or "") / _CHARS_PER_TOKEN))


def _as_int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and value > 0 else 0


@dataclass(frozen=True)
class TokenUsage:
    """What one or more model calls cost, in tokens."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cached_prefix_tokens: int = 0   # largest cached prefix seen — the system block
    calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def uncached_input_tokens(self) -> int:
        return max(
            0, self.input_tokens - self.cache_read_tokens - self.cache_write_tokens
        )

    @property
    def cache_hit_rate(self) -> Optional[int]:
        """Percentage of prompt tokens served from cache, or None if no prompt."""
        if not self.input_tokens:
            return None
        return round(100 * self.cache_read_tokens / self.input_tokens)

    @property
    def tokens_saved_by_cache(self) -> int:
        """
        Input tokens avoided by the cache, net of what writing it cost.

        A cache read is billed at a tenth of the input rate and a write at a
        quarter above it, so the saving is expressed as the equivalent number of
        uncached input tokens. Negative while the cache is still being paid for.
        """
        saved = self.cache_read_tokens * (1 - CACHE_READ_RATE)
        spent = self.cache_write_tokens * (CACHE_WRITE_RATE - 1)
        return round(saved - spent)

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        if not isinstance(other, TokenUsage):
            return NotImplemented
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cached_prefix_tokens=max(
                self.cached_prefix_tokens, other.cached_prefix_tokens
            ),
            calls=self.calls + other.calls,
        )

    def as_detail(self, system_prompt: str = "") -> dict[str, Any]:
        """
        Run-log detail for this usage. Empty when nothing was measured, so an
        offline run does not carry a row of misleading zeroes.

        The system prompt is the only cached block, so its size is read from the
        cached prefix; `system_prompt` is only used to estimate that figure when
        nothing was cached at all.
        """
        if not self.calls:
            return {}
        measured = self.cached_prefix_tokens > 0
        detail: dict[str, Any] = {
            "llm_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "system_prompt_tokens": (
                self.cached_prefix_tokens if measured else approx_tokens(system_prompt)
            ),
            "system_prompt_measured": measured,
        }
        return detail

    # ── Normalisation ──────────────────────────────────────────────────────

    @classmethod
    def from_anthropic(cls, usage: Any) -> "TokenUsage":
        """Read an `anthropic.types.Usage`, folding cached tokens into the input."""
        if usage is None:
            return cls()
        read = _as_int(getattr(usage, "cache_read_input_tokens", 0))
        write = _as_int(getattr(usage, "cache_creation_input_tokens", 0))
        return cls(
            input_tokens=_as_int(getattr(usage, "input_tokens", 0)) + read + write,
            output_tokens=_as_int(getattr(usage, "output_tokens", 0)),
            cache_read_tokens=read,
            cache_write_tokens=write,
            cached_prefix_tokens=read + write,
            calls=1,
        )

    @classmethod
    def from_langchain(cls, usage_metadata: Any) -> "TokenUsage":
        """
        Read a LangChain `usage_metadata` dict.

        `input_tokens` already includes the cached tokens. Cache creation is
        reported either as one figure or split across per-TTL keys, never both.
        """
        if not isinstance(usage_metadata, dict):
            return cls()
        details = usage_metadata.get("input_token_details") or {}
        read = _as_int(details.get("cache_read"))
        write = _as_int(details.get("cache_creation")) + sum(
            _as_int(details.get(key))
            for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
        )
        input_tokens = _as_int(usage_metadata.get("input_tokens"))
        output_tokens = _as_int(usage_metadata.get("output_tokens"))
        if not (input_tokens or output_tokens):
            return cls()
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=read,
            cache_write_tokens=write,
            cached_prefix_tokens=read + write,
            calls=1,
        )


def from_detail(detail: dict[str, Any]) -> TokenUsage:
    """Rebuild usage from a logged event so totals can be re-aggregated."""
    calls = _as_int(detail.get("llm_calls"))
    if not calls:
        return TokenUsage()
    return TokenUsage(
        input_tokens=_as_int(detail.get("input_tokens")),
        output_tokens=_as_int(detail.get("output_tokens")),
        cache_read_tokens=_as_int(detail.get("cache_read_tokens")),
        cache_write_tokens=_as_int(detail.get("cache_write_tokens")),
        cached_prefix_tokens=(
            _as_int(detail.get("system_prompt_tokens"))
            if detail.get("system_prompt_measured")
            else 0
        ),
        calls=calls,
    )
