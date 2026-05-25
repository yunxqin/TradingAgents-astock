"""Generate HTML reports from analysis results, designed for browser print-to-PDF."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": True}).enable("table")


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def _signal_color(signal: str) -> str:
    s = signal.upper()
    if "BUY" in s:
        return "#22c55e"
    if "SELL" in s:
        return "#ef4444"
    return "#fbbf24"


_REPORT_SECTIONS = [
    ("market_report", "技术分析报告"),
    ("sentiment_report", "市场情绪报告"),
    ("news_report", "新闻舆情报告"),
    ("fundamentals_report", "基本面报告"),
    ("policy_report", "政策分析报告"),
    ("hot_money_report", "游资追踪报告"),
    ("lockup_report", "解禁/减持报告"),
]

_CSS = """\
/* ── Reset & Base ─────────────────────────────────────────── */
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
  font-size: 14px;
  line-height: 1.8;
  color: #1a1a1a;
  background: #fff;
  max-width: 900px;
  margin: 0 auto;
  padding: 20px 40px;
}

/* ── Cover ────────────────────────────────────────────────── */
.cover {
  text-align: center;
  padding: 80px 0 60px;
  page-break-after: always;
}
.cover .report-label {
  font-size: 20px;
  font-weight: 700;
  color: #ff5a1f;
  margin-bottom: 20px;
  letter-spacing: 4px;
}
.cover .ticker {
  font-size: 40px;
  font-weight: 900;
  color: #1a1a1a;
  margin-bottom: 12px;
}
.cover .meta {
  font-size: 14px;
  color: #666;
  margin-bottom: 6px;
}
.cover .signal {
  font-size: 44px;
  font-weight: 900;
  margin: 24px 0;
}
.cover .disclaimer {
  font-size: 11px;
  color: #999;
  max-width: 500px;
  margin: 30px auto 0;
  line-height: 1.7;
}

/* ── Header / Footer (screen only) ───────────────────────── */
@media screen {
  .page-header, .page-footer { display: none; }
}

/* ── Sections ─────────────────────────────────────────────── */
.section {
  page-break-before: always;
  padding-top: 20px;
}
.section-title {
  font-size: 22px;
  font-weight: 700;
  color: #ff5a1f;
  border-bottom: 3px solid #ff5a1f;
  padding-bottom: 8px;
  margin-bottom: 20px;
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

/* ── Print styles ─────────────────────────────────────────── */
@media print {
  body {
    font-size: 11px;
    line-height: 1.6;
    padding: 0;
    max-width: none;
  }
  .cover {
    padding: 40px 0 30px;
  }
  .section {
    page-break-before: always;
    padding-top: 10px;
  }
  .section-title { font-size: 17px; }
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
      font-family: "Noto Sans CJK SC", "PingFang SC", sans-serif;
    }
    @bottom-left {
      content: "仅供学习研究，不构成投资建议";
      font-size: 7px;
      color: #aaa;
      font-family: "Noto Sans CJK SC", "PingFang SC", sans-serif;
    }
  }
}

/* ── Debate / Risk subsections ────────────────────────────── */
.subsection-title {
  font-size: 16px;
  font-weight: 700;
  color: #333;
  border-bottom: 1px solid #e0e0e0;
  padding-bottom: 4px;
  margin: 20px 0 10px;
}
"""

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>TradingAgents-Astock {ticker} {trade_date}</title>
<style>
{css}
</style>
</head>
<body>

<!-- ── Cover ─────────────────────────────── -->
<div class="cover">
  <div class="report-label">A股多Agent投研分析报告</div>
  <div class="ticker">{ticker}</div>
  <div class="meta">分析日期: {trade_date}</div>
  <div class="meta">生成时间: {gen_time}</div>
  <div class="signal" style="color: {signal_color};">{signal}</div>
  <div class="disclaimer">
    ⚠️ 免责声明: 本报告由 AI 多 Agent 系统自动生成，仅供学习研究与技术演示，
    不构成任何投资建议。投资决策请咨询持牌专业机构。使用本报告所产生的任何损失由使用者自行承担。
  </div>
</div>

{sections}

<!-- ── Footer note ────────────────────────── -->
<div style="text-align:center;color:#aaa;font-size:10px;margin-top:40px;padding-top:20px;border-top:1px solid #e0e0e0;">
  仅供学习研究，不构成投资建议
</div>

</body>
</html>"""


def _render_section(title: str, content: str) -> str:
    html_body = _md.render(content)
    return f"""\
<div class="section">
  <div class="section-title">{title}</div>
  <div class="content">
{html_body}
  </div>
</div>"""


def _render_subsection(title: str, content: str) -> str:
    html_body = _md.render(content)
    return f"""\
<div class="subsection-title">{title}</div>
<div class="content">
{html_body}
</div>"""


def generate_pdf_bytes(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> bytes:
    """Generate a PDF report via WeasyPrint HTML→PDF conversion and return as bytes."""
    html_str = generate_html(final_state, ticker, trade_date, signal)
    from weasyprint import HTML

    return HTML(string=html_str).write_pdf()


def generate_html(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> str:
    """Generate a complete HTML report and return it as a string."""

    sections_parts: list[str] = []

    for key, title in _REPORT_SECTIONS:
        content = final_state.get(key, "")
        if content:
            cleaned = _strip_think(str(content))
            sections_parts.append(_render_section(title, cleaned))

    debate = final_state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        parts: list[str] = []
        if debate.get("bull_history"):
            parts.append(_render_subsection("多方论点", _strip_think(debate["bull_history"])))
        if debate.get("bear_history"):
            parts.append(_render_subsection("空方论点", _strip_think(debate["bear_history"])))
        if debate.get("judge_decision"):
            parts.append(_render_subsection("研究经理决策", _strip_think(debate["judge_decision"])))
        if parts:
            sections_parts.append(
                f'<div class="section"><div class="section-title">多空辩论</div>{"".join(parts)}</div>'
            )

    trader_decision = final_state.get("trader_investment_decision", "")
    if trader_decision:
        sections_parts.append(_render_section("交易员决策", _strip_think(str(trader_decision))))

    inv_plan = final_state.get("investment_plan", "")
    if inv_plan:
        sections_parts.append(_render_section("最终投资建议", _strip_think(str(inv_plan))))

    risk = final_state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        parts = []
        for key_name, label in [
            ("aggressive_history", "激进观点"),
            ("conservative_history", "保守观点"),
            ("neutral_history", "中性观点"),
        ]:
            if risk.get(key_name):
                parts.append(_render_subsection(label, _strip_think(risk[key_name])))
        if risk.get("judge_decision"):
            parts.append(_render_subsection("风控决策", _strip_think(risk["judge_decision"])))
        if parts:
            sections_parts.append(
                f'<div class="section"><div class="section-title">风控评估</div>{"".join(parts)}</div>'
            )

    final_decision = final_state.get("final_trade_decision", "")
    if final_decision:
        sections_parts.append(_render_section("最终决策", _strip_think(str(final_decision))))

    return _HTML_TEMPLATE.format(
        ticker=ticker,
        trade_date=trade_date,
        gen_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
        signal=signal.upper(),
        signal_color=_signal_color(signal),
        sections="\n".join(sections_parts),
        css=_CSS,
    )
