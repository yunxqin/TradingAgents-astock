"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.
"""

from __future__ import annotations

import re
from typing import Tuple


# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: Tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# Chinese → English rating mapping (LLMs often output Chinese despite the
# English schema, especially when config.output_language == "Chinese").
_CHINESE_RATING_MAP: dict[str, str] = {
    "买入": "Buy",
    "增持": "Overweight",
    "持有": "Hold",
    "观望": "Hold",
    "减持": "Underweight",
    "卖出": "Sell",
}

# Matches "Rating: X" / "rating - X" / "**评级**：X" — tolerates markdown
# bold wrappers and either English or Chinese labels.
_RATING_LABEL_RE = re.compile(
    r"(?:rating|评级)\s*[:\-]\s*\*{0,2}\s*(\S+)", re.IGNORECASE
)


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.

    Three-pass strategy:
    1. Look for an explicit "Rating / 评级: X" label.
    2. Scan for English 5-tier keywords (Buy, Hold, Sell, etc.).
    3. Scan for Chinese rating keywords (买入, 持有, 减持, etc.).

    Returns a Title-cased English rating string, or ``default``.
    """
    # Pass 1: explicit rating label (English or Chinese)
    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m:
            word = m.group(1).strip("*")
            word_lower = word.lower()
            if word_lower in _RATING_SET:
                return word.capitalize()
            if word_lower in _CHINESE_RATING_MAP:
                return _CHINESE_RATING_MAP[word_lower]

    # Pass 2: first English 5-tier keyword anywhere in text
    for line in text.splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,，")
            if clean in _RATING_SET:
                return clean.capitalize()

    # Pass 3: first Chinese rating keyword anywhere in text
    for line in text.splitlines():
        for cn_word, en_word in _CHINESE_RATING_MAP.items():
            if cn_word in line:
                return en_word

    return default
