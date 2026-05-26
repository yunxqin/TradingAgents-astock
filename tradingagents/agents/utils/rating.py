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
    "增配": "Overweight",
    "持有": "Hold",
    "观望": "Hold",
    "减持": "Underweight",
    "减配": "Underweight",
    "轻仓": "Underweight",
    "卖出": "Sell",
}

# Strip parenthesised Chinese annotations from a rating word — e.g.
# "Underweight（减配）" → "Underweight", "减持/轻仓" → "减持/轻仓".
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")

# Matches "Rating: X" / "评级：X" / "RATING: Buy" / "RECOMMENDATION: Hold" /
# "ACTION: Sell" — bold markers are stripped before matching.
_RATING_LABEL_RE = re.compile(
    r"(?:rating|recommendation|action|评级|建议|操作)\s*[:\-：]\s*(\S+)", re.IGNORECASE
)


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from prose text.

    Strategy (ordered by reliability):
    1. Strip markdown bold, then look for "Rating / 评级: X" label line.
    2. Scan for Chinese rating keywords (买入, 持有, 减持, etc.).
    3. Fall back to English 5-tier keywords as a last resort.

    Returns a Title-cased English rating string, or ``default``.
    """
    # Pass 1: explicit "Rating / 评级: X" label.
    # Strip bold markers first so "**评级**：**Underweight**" → "评级：Underweight".
    clean_text = text.replace("**", "").replace("*", "")
    for line in clean_text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m:
            word = _PAREN_RE.sub("", m.group(1)).strip("()（）[]【】/")
            word_lower = word.lower()
            if word_lower in _RATING_SET:
                return word.capitalize()
            if word_lower in _CHINESE_RATING_MAP:
                return _CHINESE_RATING_MAP[word_lower]

    # Pass 2: Chinese rating keywords (first match wins).
    for line in clean_text.splitlines():
        for cn_word, en_word in _CHINESE_RATING_MAP.items():
            if cn_word in line:
                return en_word

    # Pass 3: English 5-tier keywords as last resort.
    for line in clean_text.splitlines():
        for word in line.lower().split():
            clean = word.strip("*:.,，()（）[]【】")
            if clean in _RATING_SET:
                return clean.capitalize()

    return default
