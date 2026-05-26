"""Extract the 5-tier portfolio rating from the Portfolio Manager's decision.

The Portfolio Manager produces a typed ``PortfolioDecision`` via structured
output and renders it to markdown that always carries a ``**Rating**: X``
header (see :func:`tradingagents.agents.schemas.render_pm_decision`).  The
deterministic heuristic in :mod:`tradingagents.agents.utils.rating` handles
the vast majority of cases; a tiny LLM call serves as last-resort fallback
for free-text outputs that don't match the expected format.

This module exists for backwards compatibility with callers that expect a
``SignalProcessor.process_signal(text)`` interface.
"""

from __future__ import annotations

import logging
from typing import Any

from tradingagents.agents.utils.rating import RATINGS_5_TIER, parse_rating

logger = logging.getLogger(__name__)

# Quick, cheap prompt to extract the rating from a free-text decision.
_RATING_EXTRACT_PROMPT = """Extract the final trading decision rating from this text.
Reply with exactly one word: Buy, Overweight, Hold, Underweight, or Sell.

Text:
{text}

Rating:"""


class SignalProcessor:
    """Read the 5-tier rating out of a Portfolio Manager decision."""

    def __init__(self, quick_thinking_llm: Any = None):
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str) -> str:
        """Return one of Buy / Overweight / Hold / Underweight / Sell."""
        rating = parse_rating(full_signal)

        # If the parser returned a result but the text doesn't actually
        # contain that keyword (English or Chinese), it's likely a default
        # fallback.  Use a tiny LLM call as the final safety net.
        if self.quick_thinking_llm is not None and not _text_confirms(full_signal, rating):
            try:
                llm_rating = self._llm_extract(full_signal)
                if llm_rating:
                    logger.info("LLM fallback extracted rating: %s", llm_rating)
                    return llm_rating
            except Exception:
                logger.warning("LLM rating extraction fallback failed; keeping parser result")

        return rating

    def _llm_extract(self, text: str) -> str | None:
        """Use the quick-thinking LLM to extract a rating from text."""
        # Truncate — the first 3000 chars are enough to find the rating.
        prompt = _RATING_EXTRACT_PROMPT.format(text=text[:3000])
        response = self.quick_thinking_llm.invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        content = content.strip().capitalize()
        if content in set(RATINGS_5_TIER):
            return content
        return None


def _text_confirms(text: str, rating: str) -> bool:
    """Check whether *text* actually contains *rating* in English or Chinese."""
    cn_map = {
        "Buy": "买入", "Overweight": "增持", "Hold": "持有",
        "Underweight": "减持", "Sell": "卖出",
    }
    rating_lower = rating.lower()
    cn_term = cn_map.get(rating, "")
    return rating_lower in text.lower() or (cn_term and cn_term in text)
