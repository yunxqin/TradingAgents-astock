"""Generate HTML reports from analysis results, designed for browser print-to-PDF."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": True}).enable("table")


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _signal_color(signal: str) -> str:
    s = signal.upper()
    if "BUY" in s or "OVERWEIGHT" in s:
        return "#22c55e"
    if "SELL" in s or "UNDERWEIGHT" in s:
        return "#ef4444"
    return "#fbbf24"


_REPORT_SECTIONS = [
    ("market_report", "📊 技术分析"),
    ("sentiment_report", "💬 市场情绪"),
    ("news_report", "📰 新闻舆情"),
    ("fundamentals_report", "📋 基本面"),
    ("policy_report", "🏛️ 政策分析"),
    ("hot_money_report", "🔥 游资追踪"),
    ("lockup_report", "🔒 解禁/减持"),
]

_CSS = """\
/* ── Reset & Base ─────────────────────────────────────────── */
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
  font-size: 14px;
  line-height: 1.8;
  color: #1a1a1a;
  background: #f5f5f5;
  max-width: 960px;
  margin: 0 auto;
  padding: 24px 32px;
}

/* ── Cover Card ───────────────────────────────────────────── */
.cover {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  border: 1px solid #333;
  border-radius: 16px;
  padding: 2.5rem 2rem;
  text-align: center;
  margin: 1rem 0 2rem;
}
.cover .report-label {
  font-size: 0.9rem;
  color: #888;
  letter-spacing: 2px;
  margin-bottom: 0.5rem;
}
.cover .ticker {
  font-size: 1.3rem;
  font-weight: 500;
  color: #f5f1eb;
  margin-bottom: 0.3rem;
}
.cover .meta {
  font-size: 0.85rem;
  color: #999;
  margin-bottom: 0.2rem;
}
.cover .signal {
  font-size: 3.5rem;
  font-weight: 900;
  margin: 0.6rem 0 0.3rem;
}
.cover .disclaimer {
  font-size: 0.75rem;
  color: #777;
  max-width: 520px;
  margin: 1.2rem auto 0;
  line-height: 1.7;
}

/* ── <details> Accordion ──────────────────────────────────── */
details.section {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  margin-bottom: 12px;
  overflow: hidden;
}
details.section > summary {
  cursor: pointer;
  padding: 14px 20px;
  font-size: 15px;
  font-weight: 700;
  color: #1a1a1a;
  background: #fafafa;
  border-bottom: 1px solid #eee;
  list-style: none;
  display: flex;
  align-items: center;
  gap: 8px;
}
details.section > summary::-webkit-details-marker { display: none; }
details.section > summary::before {
  content: "▶";
  display: inline-block;
  font-size: 10px;
  transition: transform 0.2s;
  color: #999;
}
details.section[open] > summary::before {
  transform: rotate(90deg);
}
details.section[open] > summary {
  border-bottom: 1px solid #e0e0e0;
}
details.section .content {
  padding: 16px 20px;
}

/* ── CSS Tabs (radio-driven) ──────────────────────────────── */
.tabs-section {
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  margin-bottom: 12px;
  overflow: hidden;
}
.tabs-section > .tabs-header {
  display: flex;
  background: #fafafa;
  border-bottom: 1px solid #e0e0e0;
}
.tabs-section > input[type="radio"] {
  display: none;
}
.tabs-section > .tabs-header > label {
  flex: 1;
  text-align: center;
  padding: 12px 8px;
  font-size: 13px;
  font-weight: 600;
  color: #888;
  cursor: pointer;
  border-bottom: 3px solid transparent;
  transition: color 0.15s, border-color 0.15s;
  user-select: none;
}
.tabs-section > .tabs-header > label:hover {
  color: #444;
}
.tabs-section > .tab-panel {
  display: none;
  padding: 16px 20px;
}

/* ── Markdown content ─────────────────────────────────────── */
.content h1 { font-size: 20px; color: #ff5a1f; margin: 20px 0 10px; }
.content h2 { font-size: 17px; color: #333; margin: 18px 0 8px; border-bottom: 1px solid #e0e0e0; padding-bottom: 4px; }
.content h3 { font-size: 15px; color: #444; margin: 14px 0 6px; }
.content h4 { font-size: 14px; color: #555; margin: 10px 0 4px; }
.content p { margin: 6px 0; }
.content strong { color: #1a1a1a; }

.content table {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 12px;
}
.content table th,
.content table td {
  border: 1px solid #d0d0d0;
  padding: 6px 8px;
  text-align: left;
  vertical-align: top;
}
.content table th {
  background: #f5f5f5;
  font-weight: 700;
  white-space: nowrap;
}
.content table tr:nth-child(even) td {
  background: #fafafa;
}

.content ul, .content ol {
  margin: 6px 0 6px 24px;
}
.content li { margin: 2px 0; }

.content blockquote {
  border-left: 3px solid #ff5a1f;
  padding: 4px 12px;
  margin: 10px 0;
  color: #666;
  background: #fafafa;
}

.content hr {
  border: none;
  border-top: 1px solid #d0d0d0;
  margin: 16px 0;
}

.content code {
  background: #f0f0f0;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 13px;
  font-family: "SF Mono", "Cascadia Code", "Consolas", monospace;
}

.content pre {
  background: #f5f5f5;
  border: 1px solid #e0e0e0;
  border-radius: 4px;
  padding: 10px 14px;
  margin: 10px 0;
  overflow-x: auto;
  font-size: 12px;
  line-height: 1.6;
}
.content pre code {
  background: none;
  padding: 0;
}

/* ── Footer ───────────────────────────────────────────────── */
.footer-note {
  text-align: center;
  color: #aaa;
  font-size: 10px;
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid #e0e0e0;
}

/* ── Print styles ─────────────────────────────────────────── */
@media print {
  body {
    font-size: 11px;
    line-height: 1.6;
    background: #fff;
    padding: 0;
    max-width: none;
  }
  .cover {
    background: #fff !important;
    border: 1px solid #ccc;
    padding: 30px 20px;
    page-break-after: always;
  }
  .cover .report-label { color: #ff5a1f; }
  .cover .ticker { color: #1a1a1a; }
  .cover .signal { font-size: 2.5rem; }
  .cover .disclaimer { color: #999; }

  details.section {
    page-break-before: always;
    border: none;
    border-radius: 0;
    margin-bottom: 0;
  }
  details.section > summary {
    font-size: 17px;
    color: #ff5a1f;
    border-bottom: 3px solid #ff5a1f;
    pointer-events: none;
  }
  details.section > summary::before { content: none; }
  details.section .content { padding: 10px 0; }
  /* Force all details open in print */
  details.section { display: block; }

  .tabs-section {
    page-break-before: always;
    border: none;
  }
  .tabs-section > .tabs-header { display: none; }
  .tabs-section > .tab-panel {
    display: block !important;
    padding: 0 0 16px 0;
    page-break-inside: avoid;
  }
  .tabs-section > .tab-panel::before {
    display: block;
    font-size: 14px;
    font-weight: 700;
    color: #555;
    border-bottom: 1px solid #ccc;
    padding-bottom: 4px;
    margin-bottom: 10px;
    content: attr(data-label);
  }

  .content table { font-size: 9px; }
  .content table th, .content table td { padding: 3px 5px; }
  .content h1 { font-size: 15px; }
  .content h2 { font-size: 13px; }
  .content h3 { font-size: 12px; }
  .content pre { font-size: 9px; }

  @page {
    size: A4;
    margin: 18mm 15mm 22mm 15mm;
    @bottom-center {
      content: "Page " counter(page) " / " counter(pages);
      font-size: 8px;
      color: #888;
    }
    @bottom-left {
      content: "仅供学习研究，不构成投资建议";
      font-size: 7px;
      color: #aaa;
    }
  }
}
"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TradingAgents-Astock {ticker} {trade_date}</title>
<style>
{css}
</style>
</head>
<body>

<!-- ── Cover ─────────────────────────────── -->
<div class="cover">
  <div class="report-label">TRADING SIGNAL</div>
  <div class="signal" style="color: {signal_color};">{signal}</div>
  <div class="ticker">{ticker} · {trade_date}</div>
  <div class="meta">生成时间: {gen_time}</div>
  <div class="disclaimer">
    ⚠️ 免责声明: 本报告由 AI 多 Agent 系统自动生成，仅供学习研究与技术演示，
    不构成任何投资建议。投资决策请咨询持牌专业机构。使用本报告所产生的任何损失由使用者自行承担。
  </div>
</div>

{sections}

<div class="footer-note">
  TradingAgents-Astock · 仅供学习研究，不构成投资建议
</div>

</body>
</html>"""

# Counter for generating unique tab group names
_tab_counter: int = 0


def _next_tab_group() -> str:
    global _tab_counter
    _tab_counter += 1
    return f"tg{_tab_counter}"


def _render_section(title: str, content: str) -> str:
    """Render an analyst report as a <details> accordion (open by default)."""
    html_body = _md.render(content)
    return f"""\
<details class="section" open>
  <summary>{title}</summary>
  <div class="content">
{html_body}
  </div>
</details>"""


def _render_tabs_section(title: str, tabs: list[tuple[str, str]], group: str, checked_idx: int = 0) -> str:
    """Render a tabbed section using CSS radio buttons.

    Each tab group gets scoped CSS rules keyed by unique radio/panel IDs,
    so multiple sections on the same page don't interfere.
    """
    n = len(tabs)
    parts: list[str] = []

    # Radio inputs
    for i in range(n):
        checked = " checked" if i == checked_idx else ""
        parts.append(f'<input type="radio" name="{group}" id="{group}-r{i}"{checked}>')

    # Labels row
    labels_html = "".join(
        f'<label for="{group}-r{i}">{tabs[i][0]}</label>'
        for i in range(n)
    )
    parts.append(f'<div class="tabs-header">{labels_html}</div>')

    # Panels
    for i, (label, body) in enumerate(tabs):
        parts.append(f'<div class="tab-panel" id="{group}-p{i}" data-label="{label}">{body}</div>')

    # Per-group scoped CSS
    css_rules: list[str] = []
    for i in range(n):
        # Highlight active label
        css_rules.append(
            f'#{group}-r{i}:checked ~ .tabs-header > label[for="{group}-r{i}"]'
            f'{{ color: #ff5a1f; border-bottom-color: #ff5a1f; }}'
        )
        # Show corresponding panel
        css_rules.append(
            f'#{group}-r{i}:checked ~ #{group}-p{i}{{ display: block; }}'
        )

    return f"""\
<style>{" ".join(css_rules)}</style>
<div class="tabs-section" id="sec-{group}">
  {"".join(parts)}
</div>"""


def _pdf_cache_dir(ticker: str) -> Path:
    return Path.home() / ".tradingagents" / "logs" / ticker / "TradingAgentsStrategy_logs"


def generate_pdf_bytes(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> bytes:
    """Generate a PDF report via WeasyPrint HTML→PDF conversion, cached to disk."""
    cache_path = _pdf_cache_dir(ticker) / f"cache_pdf_{trade_date}.pdf"

    # Hit disk cache — skip expensive WeasyPrint run
    if cache_path.exists():
        return cache_path.read_bytes()

    html_str = generate_html(final_state, ticker, trade_date, signal)

    # Save HTML alongside PDF for direct browser viewing
    html_path = cache_path.with_suffix(".html")
    html_path.write_text(html_str, encoding="utf-8")

    from weasyprint import HTML

    pdf_bytes = HTML(string=html_str).write_pdf()

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(pdf_bytes)
    return pdf_bytes


def generate_html(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> str:
    """Generate a complete interactive HTML report and return it as a string."""

    sections_parts: list[str] = []

    # ── Analyst reports as <details> accordion ──
    for key, title in _REPORT_SECTIONS:
        content = final_state.get(key, "")
        if content:
            cleaned = _strip_think(str(content))
            sections_parts.append(_render_section(title, cleaned))

    # ── Debate as CSS tabs ──
    debate = final_state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        tabs: list[tuple[str, str]] = []
        if debate.get("bull_history"):
            tabs.append(("多方", _md.render(_strip_think(debate["bull_history"]))))
        if debate.get("bear_history"):
            tabs.append(("空方", _md.render(_strip_think(debate["bear_history"]))))
        if debate.get("judge_decision"):
            tabs.append(("研究经理", _md.render(_strip_think(debate["judge_decision"]))))
        if tabs:
            sections_parts.append(_render_tabs_section("⚔️ 多空辩论", tabs, _next_tab_group()))

    # ── Trader as <details> accordion ──
    trader_decision = final_state.get("trader_investment_decision", "")
    if trader_decision:
        sections_parts.append(_render_section("💹 交易员决策", _strip_think(str(trader_decision))))

    # ── Risk as CSS tabs ──
    risk = final_state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        tabs = []
        for key_name, label in [
            ("aggressive_history", "激进"),
            ("conservative_history", "保守"),
            ("neutral_history", "中性"),
        ]:
            if risk.get(key_name):
                tabs.append((label, _md.render(_strip_think(risk[key_name]))))
        if risk.get("judge_decision"):
            tabs.append(("风控决策", _md.render(_strip_think(risk["judge_decision"]))))
        if tabs:
            sections_parts.append(_render_tabs_section("🛡️ 风控评估", tabs, _next_tab_group()))

    # ── Final decision as <details> ──
    final_decision = final_state.get("final_trade_decision", "")
    if final_decision:
        sections_parts.append(_render_section("📝 最终决策", _strip_think(str(final_decision))))

    return _HTML_TEMPLATE.format(
        ticker=ticker,
        trade_date=trade_date,
        gen_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        signal=signal.upper(),
        signal_color=_signal_color(signal),
        sections="\n".join(sections_parts),
        css=_CSS,
    )
