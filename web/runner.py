"""Background thread runner for TradingAgentsGraph pipeline."""

from __future__ import annotations

import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from web.progress import PIPELINE_STAGES, ProgressTracker


_REPORT_KEY_TO_STAGE = {s["report_key"]: s["id"] for s in PIPELINE_STAGES}

_ANALYST_REPORT_KEYS = [
    "market_report", "sentiment_report", "news_report",
    "fundamentals_report", "policy_report", "hot_money_report", "lockup_report",
]


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output."""
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


_STAGE_NAMES: dict[str, str] = {s["id"]: s["name"] for s in PIPELINE_STAGES}


def _detect_completed_stages(
    chunk: dict[str, Any],
    tracker: ProgressTracker,
) -> None:
    """Check the streamed chunk for newly completed stages."""
    for report_key in _ANALYST_REPORT_KEYS:
        stage_id = _REPORT_KEY_TO_STAGE[report_key]
        content = chunk.get(report_key, "")
        if content and tracker.stage_status(stage_id) != "done":
            tracker.mark_stage_done(stage_id, _strip_think_tags(str(content)))
            print(f"  ✓ {_STAGE_NAMES[stage_id]} 完成", file=sys.stderr)

    dqs = chunk.get("data_quality_summary", "")
    if dqs and tracker.stage_status("quality_gate") != "done":
        tracker.mark_stage_done("quality_gate", str(dqs))
        print(f"  ✓ {_STAGE_NAMES['quality_gate']} 完成", file=sys.stderr)

    debate = chunk.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        judge = debate.get("judge_decision", "")
        if judge and tracker.stage_status("debate") != "done":
            tracker.mark_stage_done("debate", str(judge))
            print(f"  ✓ {_STAGE_NAMES['debate']} 完成", file=sys.stderr)

    trader_plan = chunk.get("trader_investment_plan", "")
    if trader_plan and tracker.stage_status("trader") != "done":
        tracker.mark_stage_done("trader", _strip_think_tags(str(trader_plan)))
        print(f"  ✓ {_STAGE_NAMES['trader']} 完成", file=sys.stderr)

    risk = chunk.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        risk_judge = risk.get("judge_decision", "")
        if risk_judge and tracker.stage_status("risk") != "done":
            tracker.mark_stage_done("risk", str(risk_judge))
            print(f"  ✓ {_STAGE_NAMES['risk']} 完成", file=sys.stderr)

    final = chunk.get("final_trade_decision", "")
    if final and tracker.stage_status("pm") != "done":
        tracker.mark_stage_done("pm", _strip_think_tags(str(final)))
        print(f"  ✓ {_STAGE_NAMES['pm']} 完成", file=sys.stderr)


def _infer_active_stage(tracker: ProgressTracker) -> None:
    """Set the current_stage to the first non-completed stage."""
    from web.progress import STAGE_IDS
    for sid in STAGE_IDS:
        if tracker.stage_status(sid) == "pending":
            tracker.mark_stage_active(sid)
            return


def _log_dir(ticker: str) -> Path:
    return Path.home() / ".tradingagents" / "logs" / ticker / "TradingAgentsStrategy_logs"


def _run(ticker: str, trade_date: str, config: dict, tracker: ProgressTracker) -> None:
    """Execute the full pipeline in the current thread."""
    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    log_dir = _log_dir(ticker)
    log_dir.mkdir(parents=True, exist_ok=True)
    debug_path = log_dir / f"debug_{trade_date}.log"

    print(f"\n{'='*50}")
    print(f"分析启动: {ticker} {trade_date}")
    print(f"Debug 日志: {debug_path}")
    print(f"{'='*50}")

    stats = StatsCallbackHandler()

    graph = TradingAgentsGraph(
        debug=True,
        config=config,
        callbacks=[stats],
    )

    init_state = graph.propagator.create_initial_state(ticker, trade_date)
    args = graph.propagator.get_graph_args(callbacks=[stats])

    last_chunk: dict[str, Any] = {}

    # Redirect stdout to debug log file — keeps terminal clean while
    # preserving all LLM prompts/responses for later review.
    old_stdout = sys.stdout
    with open(debug_path, "w", encoding="utf-8") as debug_log:
        sys.stdout = debug_log
        try:
            for chunk in graph.graph.stream(init_state, **args):
                last_chunk = chunk
                _detect_completed_stages(chunk, tracker)
                _infer_active_stage(tracker)

                s = stats.get_stats()
                tracker.update_stats(s["llm_calls"], s["tool_calls"], s["tokens_in"], s["tokens_out"])
        finally:
            sys.stdout = old_stdout

    signal = graph.process_signal(last_chunk.get("final_trade_decision", ""))

    # Print stage summary to terminal from tracker state
    completed = tracker.completed_stages
    for stage in PIPELINE_STAGES:
        sid = stage["id"]
        if sid in completed:
            print(f"  ✓ {stage['icon']} {stage['name']}")

    graph.ticker = ticker
    graph._log_state(trade_date, last_chunk)

    tracker.mark_complete(last_chunk, signal)
    print(f"  信号: {signal}")
    print(f"  LLM 调用: {tracker.llm_calls}  工具调用: {tracker.tool_calls}")
    print(f"{'='*50}\n")


def run_analysis_in_thread(
    ticker: str,
    trade_date: str,
    config: dict,
    tracker: ProgressTracker,
) -> threading.Thread:
    """Launch the pipeline in a daemon thread. Returns the thread handle."""
    tracker.ticker = ticker
    tracker.trade_date = trade_date
    tracker.is_running = True
    tracker.mark_stage_active("market")

    def _target() -> None:
        try:
            _run(ticker, trade_date, config, tracker)
        except Exception as exc:
            tracker.mark_error(str(exc))

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t


def run_debug_analysis_in_thread(
    ticker: str,
    trade_date: str,
    tracker: ProgressTracker,
) -> threading.Thread:
    """Launch a debug pipeline that uses canned data instead of LLM calls."""

    tracker.ticker = ticker
    tracker.trade_date = trade_date
    tracker.is_running = True

    def _target() -> None:
        try:
            _run_debug(ticker, trade_date, tracker)
        except Exception as exc:
            tracker.mark_error(str(exc))

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    return t


def _run_debug(ticker: str, trade_date: str, tracker: ProgressTracker) -> None:
    """Simulate pipeline stages using pre-canned analysis data."""
    fixture_path = Path(__file__).resolve().parent / "debug_state.json"
    debug_state = json.loads(fixture_path.read_text(encoding="utf-8"))

    # Override with actual user input
    debug_state["company_of_interest"] = ticker
    debug_state["trade_date"] = trade_date

    # Simulate each stage completing with realistic delays
    stages = [
        ("market", "market_report"),
        ("social", "sentiment_report"),
        ("news", "news_report"),
        ("fundamentals", "fundamentals_report"),
        ("policy", "policy_report"),
        ("hot_money", "hot_money_report"),
        ("lockup", "lockup_report"),
        ("quality_gate", "data_quality_summary"),
        ("debate", "investment_plan"),
        ("trader", "trader_investment_plan"),
        ("risk", "risk_debate_state"),
        ("pm", "final_trade_decision"),
    ]

    print(f"\n{'='*50}")
    print(f"🐛 DEBUG 模式: {ticker} {trade_date}")
    print(f"{'='*50}")

    from tradingagents.agents.utils.rating import parse_rating

    for stage_id, _ in stages:
        if not tracker.is_running:
            return

        tracker.mark_stage_active(stage_id)
        time.sleep(0.15)

        if stage_id == "debate":
            tracker.mark_stage_done(stage_id, debug_state.get("investment_plan", ""))

            # Build a minimal last_chunk for signal extraction
            last_chunk: dict[str, Any] = {}
            for k in [
                "market_report", "sentiment_report", "news_report",
                "fundamentals_report", "policy_report", "hot_money_report",
                "lockup_report",
            ]:
                if debug_state.get(k):
                    last_chunk[k] = debug_state[k]
        elif stage_id == "pm":
            tracker.mark_stage_done(stage_id, debug_state.get("final_trade_decision", ""))
        else:
            report = debug_state.get(stage_id, "") if stage_id in ["quality_gate"] else ""
            if not report:
                report = debug_state.get(
                    {"market": "market_report", "social": "sentiment_report",
                     "news": "news_report", "fundamentals": "fundamentals_report",
                     "policy": "policy_report", "hot_money": "hot_money_report",
                     "lockup": "lockup_report", "trader": "trader_investment_decision",
                     "risk": "risk_debate_state"}.get(stage_id, ""), ""
                )
            tracker.mark_stage_done(stage_id, str(report) if not isinstance(report, dict) else "")

        tracker.update_stats(0, 0, 0, 0)

    signal = parse_rating(debug_state.get("final_trade_decision", ""))

    completed = tracker.completed_stages
    for stage in PIPELINE_STAGES:
        sid = stage["id"]
        if sid in completed:
            print(f"  ✓ {stage['icon']} {stage['name']}")

    print(f"  信号: {signal}")
    print(f"  LLM 调用: 0  工具调用: 0")
    print(f"{'='*50}\n")

    tracker.mark_complete(debug_state, signal)
