"""TradingAgents A股分析 — Streamlit Web UI."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

load_dotenv(_PROJECT_ROOT / ".env")

from tradingagents.default_config import DEFAULT_CONFIG  # noqa: E402

from web.components.progress_panel import render_progress  # noqa: E402
from web.components.report_viewer import render_report  # noqa: E402
from web.components.sidebar import render_sidebar  # noqa: E402
from web.history import extract_signal, load_analysis  # noqa: E402
from web.progress import ProgressTracker  # noqa: E402
from web.runner import run_analysis_in_thread, run_debug_analysis_in_thread  # noqa: E402

# ── Page config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="TradingAgents-Astock A股分析",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────

_CSS = (Path(__file__).parent / "static" / "style.css").read_text(encoding="utf-8")
st.markdown(f"<style>{_CSS}</style>", unsafe_allow_html=True)


# ── Build config ─────────────────────────────────────────────────────────────

def _build_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = st.session_state.get("llm_provider", "deepseek")
    config["deep_think_llm"] = st.session_state.get("deep_think_llm", "deepseek-v4-pro")
    config["quick_think_llm"] = st.session_state.get("quick_think_llm", "deepseek-v4-flash")
    config["data_vendors"] = {
        "core_stock_apis": "a_stock",
        "technical_indicators": "a_stock",
        "fundamental_data": "a_stock",
        "news_data": "a_stock",
        "signal_data": "a_stock",
    }
    config["max_debate_rounds"] = 1
    config["max_risk_discuss_rounds"] = 1
    config["output_language"] = "Chinese"
    return config


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    render_sidebar()


# ── Handle "Start Analysis" trigger ──────────────────────────────────────────

start_req = st.session_state.pop("start_analysis", None)
if start_req:
    tracker = ProgressTracker(
        ticker=start_req["ticker"],
        trade_date=start_req["trade_date"],
    )
    st.session_state["tracker"] = tracker
    if st.session_state.get("debug_mode"):
        run_debug_analysis_in_thread(
            ticker=start_req["ticker"],
            trade_date=start_req["trade_date"],
            tracker=tracker,
        )
        st.toast(f"🐛 Debug 分析: {start_req['ticker']} {start_req['trade_date']}", icon="🧪")
    else:
        run_analysis_in_thread(
            ticker=start_req["ticker"],
            trade_date=start_req["trade_date"],
            config=_build_config(),
            tracker=tracker,
        )
        st.toast(f"分析已启动: {start_req['ticker']} {start_req['trade_date']}", icon="🚀")


# ── Main area state machine ─────────────────────────────────────────────────

tracker: ProgressTracker | None = st.session_state.get("tracker")
viewing_history: str | None = st.session_state.get("viewing_history")

# State 1: Viewing a historical analysis
if viewing_history:
    try:
        cache_key = f"hist_{viewing_history}"
        if cache_key not in st.session_state:
            st.session_state[cache_key] = load_analysis(viewing_history)
        state = st.session_state[cache_key]
        signal = extract_signal(state)
        ticker = Path(viewing_history).parent.parent.name
        trade_date = Path(viewing_history).stem.replace("full_states_log_", "")
        render_report(state, ticker, trade_date, signal)
    except Exception as exc:
        st.error(f"加载失败: {exc}")

# State 2: Analysis running
elif tracker and tracker.is_running:
    render_progress(tracker)
    time.sleep(2)
    st.rerun()

# State 3: Analysis complete
elif tracker and tracker.is_complete:
    render_report(
        tracker.final_state,
        tracker.ticker,
        tracker.trade_date,
        tracker.signal,
        elapsed=tracker.elapsed,
    )

# State 4: Analysis errored
elif tracker and tracker.error:
    st.error(f"分析失败: {tracker.error}")
    if st.button("重试"):
        st.session_state.pop("tracker", None)
        st.rerun()

# State 0: Idle — welcome screen
else:
    st.markdown(
        """
        <div style="
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            min-height: 60vh;
            text-align: center;
        ">
            <div style="font-size: 4rem; margin-bottom: 1rem;">📈</div>
            <div style="
                font-size: 2.5rem;
                font-weight: 900;
                margin-bottom: 0.5rem;
            ">
                <span style="color: #ff5a1f;">Trading</span><span style="color: #f5f1eb;">Agents</span><span style="color: #f5f1eb;">-</span><span style="color: #ff5a1f;">Astock</span>
            </div>
            <div style="color: #888; font-size: 1.1rem; max-width: 500px; line-height: 1.6;">
                A股多Agent投研分析系统<br>
                7位AI分析师 → 质量门控 → 多空辩论 → 风控评估 → 最终决策
            </div>
            <div style="
                margin-top: 2rem;
                padding: 1rem 2rem;
                border: 1px solid #222;
                border-radius: 12px;
                color: #666;
                font-size: 0.9rem;
            ">
                ← 在左侧输入股票代码，开始分析
            </div>
            <div style="
                margin-top: 2.5rem;
                padding: 0.8rem 1.5rem;
                color: #555;
                font-size: 0.75rem;
                max-width: 500px;
                line-height: 1.6;
                border-top: 1px solid #1a1a1a;
            ">
                ⚠️ 本项目仅供学习研究与技术演示，不构成任何投资建议。<br>
                投资决策请咨询持牌专业机构。作者不对使用本工具产生的任何损失承担责任。
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
