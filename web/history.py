"""Manage analysis history by scanning existing log files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _results_dir() -> Path:
    return Path.home() / ".tradingagents" / "logs"


def get_history() -> list[dict[str, str]]:
    """Scan saved analysis logs and return a sorted list (newest first).

    Each entry: {"ticker": "300750", "date": "2026-05-12", "path": "/abs/path/...json"}
    """
    root = _results_dir()
    if not root.exists():
        return []

    entries: list[dict[str, str]] = []
    for log_file in root.rglob("full_states_log_*.json"):
        match = re.search(r"full_states_log_(\d{4}-\d{2}-\d{2})\.json$", log_file.name)
        if not match:
            continue
        date = match.group(1)
        ticker = log_file.parent.parent.name
        entries.append({"ticker": ticker, "date": date, "path": str(log_file)})

    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries


def load_analysis(path: str) -> dict[str, Any]:
    """Load a saved analysis JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_signal(state: dict[str, Any]) -> str:
    """Extract the short signal (Buy/Sell/Hold/Overweight/Underweight) from a final state dict."""
    from tradingagents.agents.utils.rating import parse_rating

    for field in (
        "final_trade_decision",
        "trader_investment_decision",
        "investment_plan",
    ):
        text = state.get(field, "")
        if not text:
            continue
        result = parse_rating(text)
        # parse_rating returns "Hold" as default — only accept it if we
        # actually found the field had content (not a fallback).
        if result != "Hold" or len(text) > 50:
            return result
    return "N/A"
