"""Generate PDF reports from analysis results using fpdf2."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

from fpdf import FPDF
from fpdf.errors import FPDFException


_FONT_CJK_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf",
    "/usr/share/fonts/noto-cjk/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]

_FONT_EMOJI_CANDIDATES = [
    "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
]


def _find_font(candidate_paths: list[str]) -> str | None:
    for path in candidate_paths:
        if Path(path).exists():
            return path
    return None


def _is_emoji_char(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    # Common emoji/graphic symbol ranges and variation selectors
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x26FF
        or 0x2700 <= cp <= 0x27BF
        or 0xFE0E <= cp <= 0xFE0F
        or cp == 0x200D  # ZWJ
        or cp == 0x20E3  # combining enclosing keycap (e.g., 1️⃣)
        or unicodedata.category(ch) in {"So", "Sk", "Cf"}
    )


def _contains_emoji(text: str) -> bool:
    return any(_is_emoji_char(ch) for ch in text)


def _split_text_by_emoji_runs(text: str) -> list[tuple[str, bool]]:
    runs: list[tuple[str, bool]] = []
    current: str = ""
    current_is_emoji = False
    for ch in text:
        is_emoji = _is_emoji_char(ch)
        if current == "":
            current = ch
            current_is_emoji = is_emoji
            continue
        if is_emoji == current_is_emoji:
            current += ch
        else:
            runs.append((current, current_is_emoji))
            current = ch
            current_is_emoji = is_emoji
    if current:
        runs.append((current, current_is_emoji))
    return runs


def _strip_think(text: str) -> str:
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


# Inline token types for markdown parsing
_INLINE_TOKEN_RE = re.compile(
    r"(\*\*(.+?)\*\*)"       # **bold**
    r"|(\*(.+?)\*)"           # *italic*
    r"|(`(.+?)`)"             # `code`
    r"|(\[([^\]]+)\]\([^)]+\))"  # [link](url)
)


def _parse_inline(text: str) -> list[tuple[str, str]]:
    """Parse inline markdown into (text, style) segments.
    style is one of: '', 'B' (bold), 'I' (italic), 'code', or 'link'.
    """
    segments: list[tuple[str, str]] = []
    pos = 0
    for m in _INLINE_TOKEN_RE.finditer(text):
        # Text before this match (plain)
        if m.start() > pos:
            segments.append((text[pos : m.start()], ""))
        if m.group(1):  # **bold**
            segments.append((m.group(2), "B"))
        elif m.group(3):  # *italic*
            segments.append((m.group(4), "I"))
        elif m.group(5):  # `code`
            segments.append((m.group(6), "code"))
        elif m.group(7):  # [link](url)
            segments.append((m.group(8), "link"))
        pos = m.end()
    # Remaining text
    if pos < len(text):
        segments.append((text[pos:], ""))
    if not segments:
        segments.append((text, ""))
    return segments


# Basic mapping of common emoji glyphs to short text placeholders.
# This is intentionally conservative and only maps a handful of frequent symbols.
_EMOJI_WORDS: dict[str, str] = {
    "📌": "[pin]",
    "📈": "[up]",
    "📉": "[down]",
    "✅": "[check]",
    "❌": "[cross]",
    "⚠": "[warning]",
    "⚠️": "[warning]",
    "🟡": "[yellow]",
    "🟢": "[green]",
    "🔸": "[diamond]",
    "🔴": "[red]",
    "📊": "[chart]",
    "📋": "[clip]",
    "🔥": "[hot]",
    "🛡": "[shield]",
    "🚧": "[barrier]",
    "⭐": "[star]",
    "🥇": "[rank1]",
    "\u20e3": "",          # combining keycap (e.g. 1️⃣ → just show the number)
    "⬆": "[up_arrow]",
    "⬇": "[down_arrow]",
    "🔒": "[lock]",
    "📢": "[announce]",
    "💡": "[idea]",
    "🔍": "[search]",
    "📝": "[note]",
    "🧠": "[brain]",
    "⚡": "[lightning]",
    "💎": "[diamond]",
    "🏛": "[building]",
    "\ufe0f": "",           # variation selector, strip silently
}


def _emoji_to_text_run(token: str) -> str:
    # Normalize/strip common invisible joiners/selectors then map per-codepoint.
    norm = "".join(ch for ch in token if ord(ch) not in (0xFE0F, 0x200D))
    out: list[str] = []
    for ch in norm:
        out.append(_EMOJI_WORDS.get(ch, "[emoji]"))
    return "".join(out)


def _replace_emojis(text: str) -> str:
    if not text or not _contains_emoji(text):
        return text
    parts: list[str] = []
    for token, is_emoji in _split_text_by_emoji_runs(text):
        if is_emoji:
            parts.append(_emoji_to_text_run(token))
        else:
            parts.append(token)
    return "".join(parts)


def _sanitize_state(obj: Any) -> Any:
    # Recursively replace emoji in all strings inside the final_state structure.
    if isinstance(obj, str):
        return _replace_emojis(obj)
    if isinstance(obj, list):
        return [_sanitize_state(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _sanitize_state(v) for k, v in obj.items()}
    return obj


def _signal_color(signal: str) -> tuple[int, int, int]:
    s = signal.upper()
    if "BUY" in s:
        return (34, 197, 94)
    if "SELL" in s:
        return (239, 68, 68)
    return (251, 191, 36)


_REPORT_SECTIONS = [
    ("market_report", "技术分析报告"),
    ("sentiment_report", "市场情绪报告"),
    ("news_report", "新闻舆情报告"),
    ("fundamentals_report", "基本面报告"),
    ("policy_report", "政策分析报告"),
    ("hot_money_report", "游资追踪报告"),
    ("lockup_report", "解禁/减持报告"),
]


class _ReportPDF(FPDF):
    def __init__(self, ticker: str, trade_date: str, signal: str) -> None:
        super().__init__()
        self.ticker = ticker
        self.trade_date = trade_date
        self.signal = signal
        self._has_cjk = False
        self._has_emoji = False
        # track last-used font size (points) for safe resizing on errors
        self._current_font_size = 10
        cjk_font_path = _find_font(_FONT_CJK_CANDIDATES)
        if cjk_font_path:
            font_regular = str(cjk_font_path)
            bold_candidate = font_regular.replace("Regular", "Bold")
            if Path(bold_candidate).exists():
                font_bold = bold_candidate
            else:
                font_bold = font_regular

            try:
                self.add_font("CJK", "", font_regular, uni=True)
                try:
                    self.add_font("CJK", "B", font_bold, uni=True)
                except Exception:
                    pass
                self._has_cjk = True
            except Exception:
                self._has_cjk = False

        emoji_font_path = _find_font(_FONT_EMOJI_CANDIDATES)
        if emoji_font_path:
            try:
                self.add_font("EMOJI", "", str(emoji_font_path), uni=True)
                self._has_emoji = True
            except Exception:
                self._has_emoji = False

    def _use_font(self, style: str = "", size: int = 10) -> None:
        if self._has_cjk:
            self.set_font("CJK", style, size)
        else:
            self.set_font("Helvetica", style, size)
        # remember for safe retries
        try:
            self._current_font_size = int(size)
        except Exception:
            self._current_font_size = size

    def _safe_multi_cell(self, w, h, txt, **kwargs) -> None:
        """Call multi_cell but handle FPDFException by retrying with smaller font sizes.

        If retries fail, write a short placeholder line instead of raising.
        """
        if self._has_emoji and _contains_emoji(txt):
            try:
                self._render_text_with_emoji(w, h, txt, **kwargs)
                return
            except Exception:
                pass

        min_size = 6
        tried_sizes = []
        base_size = int(getattr(self, "_current_font_size", 10))
        for size in (base_size, max(min_size, base_size - 2), max(min_size, base_size - 4), min_size):
            if size in tried_sizes:
                continue
            tried_sizes.append(size)
            try:
                family = getattr(self, "font_family", None)
                style = getattr(self, "font_style", "")
                if family and family != "":
                    self.set_font(family, style, size)
                else:
                    self.set_font(self.current_font, style, size)
            except Exception:
                try:
                    self.set_font("Helvetica", "", size)
                except Exception:
                    pass
            try:
                self.multi_cell(w, h, txt, **kwargs)
                self._current_font_size = base_size
                return
            except FPDFException:
                continue
        try:
            self.set_font("Helvetica", "", min_size)
            self.multi_cell(w, h, "[内容无法渲染，已被截断]")
        except Exception:
            pass

    def _render_text_with_emoji(self, w, h, txt, **kwargs) -> None:
        align = kwargs.get("align", "L")
        if w == 0:
            w = self.w - self.l_margin - self.r_margin
        lines = txt.split("\n")
        for line in lines:
            self._render_mixed_line(line, w, h, align)

    def _render_mixed_line(self, line: str, w: float, h: float, align: str) -> None:
        tokens = _split_text_by_emoji_runs(line)
        current_line: list[tuple[str, str, str]] = []
        current_width = 0.0
        base_font = "CJK" if self._has_cjk else "Helvetica"
        base_style = getattr(self, "font_style", "")
        base_size = int(getattr(self, "_current_font_size", 10))

        def flush_line() -> None:
            nonlocal current_line, current_width
            if not current_line:
                return
            total_width = 0.0
            for font_name, style, token in current_line:
                self.set_font(font_name, style, base_size)
                total_width += self.get_string_width(token)
            x_start = self.get_x()
            if align == "C":
                x_start += max(0, (w - total_width) / 2)
            elif align == "R":
                x_start += max(0, w - total_width)
            self.set_x(x_start)
            for font_name, style, token in current_line:
                self.set_font(font_name, style, base_size)
                self.cell(self.get_string_width(token), h, token, ln=0)
            self.ln(h)
            current_line = []
            current_width = 0.0

        for token, is_emoji in tokens:
            font_name = "EMOJI" if is_emoji and self._has_emoji else base_font
            token_style = "" if font_name == "EMOJI" else base_style
            self.set_font(font_name, token_style, base_size)
            token_width = self.get_string_width(token)
            if current_line and current_width + token_width > w:
                flush_line()
            if token_width > w and not is_emoji:
                for ch in token:
                    self.set_font(font_name, token_style, base_size)
                    ch_width = self.get_string_width(ch)
                    if current_line and current_width + ch_width > w:
                        flush_line()
                    current_line.append((font_name, token_style, ch))
                    current_width += ch_width
            else:
                current_line.append((font_name, token_style, token))
                current_width += token_width
        flush_line()

    def header(self) -> None:
        self._use_font("", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 6, f"A股多Agent投研分析  |  {self.ticker}  |  {self.trade_date}", align="C")
        self.ln(8)
        self.set_draw_color(60, 60, 60)
        self.line(10, self.get_y(), self.w - 10, self.get_y())
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self._use_font("", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, f"Page {self.page_no()}/{{nb}}", align="C")
        self.ln(4)
        self._use_font("", 6)
        self.set_text_color(160, 160, 160)
        self.cell(0, 4, "仅供学习研究，不构成投资建议", align="C")

    def add_cover(self) -> None:
        self.add_page()
        self.ln(60)

        self._use_font("B", 24)
        self.set_text_color(255, 90, 31)
        self.cell(0, 12, "A股多Agent投研分析报告", align="C")
        self.ln(20)

        self._use_font("B", 36)
        self.set_text_color(30, 30, 30)
        self.cell(0, 18, self.ticker, align="C")
        self.ln(16)

        self._use_font("", 14)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, f"分析日期: {self.trade_date}", align="C")
        self.ln(8)
        self.cell(0, 10, f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}", align="C")
        self.ln(20)

        r, g, b = _signal_color(self.signal)
        self._use_font("B", 40)
        self.set_text_color(r, g, b)
        self.cell(0, 20, self.signal.upper(), align="C")
        self.ln(20)

        self._use_font("", 9)
        self.set_text_color(120, 120, 120)
        usable_width = max(10, self.w - self.l_margin - self.r_margin)

        self._safe_multi_cell(usable_width, 5,
            "免责声明: 本报告由 AI 多 Agent 系统自动生成, 仅供学习研究与技术演示, "
            "不构成任何投资建议。投资决策请咨询持牌专业机构。"
            "使用本报告所产生的任何损失由使用者自行承担。",
            align="C",
        )

    def add_section(self, title: str, content: str) -> None:
        self.add_page()
        self._use_font("B", 16)
        self.set_text_color(255, 90, 31)
        self.cell(0, 10, title)
        self.ln(12)

        cleaned = _strip_think(content)
        self._render_markdown(cleaned)

    def _render_inline_text(self, w: float, h: float, text: str, base_style: str = "", **kwargs) -> None:
        """Render a line of text with preserved inline markdown formatting (**bold**, *italic*, `code`, [links])."""
        segments = _parse_inline(text)
        if not segments:
            return

        align = kwargs.get("align", "L")
        base_size = int(getattr(self, "_current_font_size", 10))
        font_family = "CJK" if self._has_cjk else "Helvetica"

        # Calculate total width of all segments
        total_width = 0.0
        for seg_text, seg_style in segments:
            style = self._segment_font_style(base_style, seg_style)
            self.set_font(font_family, style, base_size)
            total_width += self.get_string_width(seg_text)

        # Handle alignment
        x_start = self.get_x()
        if align == "C":
            x_start += max(0, (w - total_width) / 2)
        elif align == "R":
            x_start += max(0, w - total_width)
        self.set_x(x_start)

        for seg_text, seg_style in segments:
            style = self._segment_font_style(base_style, seg_style)
            self.set_font(font_family, style, base_size)
            seg_w = self.get_string_width(seg_text)
            # Use different color for code and links
            if seg_style == "code":
                self.set_text_color(120, 120, 120)
                self.set_font(font_family, style, base_size - 1)
            elif seg_style == "link":
                self.set_text_color(50, 100, 200)
            self.cell(seg_w, h, seg_text, ln=0)
            # Reset color for next segment
            if seg_style in ("code", "link"):
                self.set_text_color(40, 40, 40)

    def _segment_font_style(self, base_style: str, seg_style: str) -> str:
        """Combine base font style with segment style for bold/italic."""
        if seg_style in ("B", "I"):
            if seg_style in base_style:
                return base_style
            return base_style + seg_style
        return base_style

    def _render_inline_para(self, w: float, h: float, text: str, base_style: str = "") -> None:
        """Render paragraph text wrapping while preserving inline bold/italic/code formatting."""
        segments = _parse_inline(text)
        if not segments:
            return

        base_size = int(getattr(self, "_current_font_size", 10))
        font_family = "CJK" if self._has_cjk else "Helvetica"

        # Build line-wrapped segments
        current_line: list[tuple[str, str]] = []
        current_width = 0.0

        def flush_inline_line() -> None:
            nonlocal current_line, current_width
            if not current_line:
                return
            x_start = self.get_x()
            self.set_x(x_start)
            for t, s in current_line:
                fs = self._segment_font_style(base_style, s)
                self.set_font(font_family, fs, base_size)
                sw = self.get_string_width(t)
                if s == "code":
                    self.set_text_color(120, 120, 120)
                elif s == "link":
                    self.set_text_color(50, 100, 200)
                self.cell(sw, h, t, ln=0)
                if s in ("code", "link"):
                    self.set_text_color(40, 40, 40)
            self.ln(h)
            current_line = []
            current_width = 0.0

        for seg_text, seg_style in segments:
            fs = self._segment_font_style(base_style, seg_style)
            self.set_font(font_family, fs, base_size)
            seg_width = self.get_string_width(seg_text)

            if seg_width > w:
                # Character-by-character wrapping for very long segments
                for ch in seg_text:
                    self.set_font(font_family, fs, base_size)
                    ch_width = self.get_string_width(ch)
                    if current_line and current_width + ch_width > w:
                        flush_inline_line()
                    current_line.append((ch, seg_style))
                    current_width += ch_width
            elif current_line and current_width + seg_width > w:
                flush_inline_line()
                current_line.append((seg_text, seg_style))
                current_width = seg_width
            else:
                current_line.append((seg_text, seg_style))
                current_width += seg_width

        flush_inline_line()

    def _render_table(self, rows: list[str]) -> None:
        """Render a markdown table with proper column alignment and borders."""
        if not rows:
            return

        # Parse rows into cells, skip separator rows
        parsed_rows: list[list[str]] = []
        for r in rows:
            r = r.strip()
            if not r.startswith("|") or not r.endswith("|"):
                continue
            if re.match(r"^\|[-:\s|]+\|$", r):
                continue
            cells = [c.strip() for c in r.strip("|").split("|")]
            parsed_rows.append(cells)

        if len(parsed_rows) < 1:
            return

        num_cols = max(len(r) for r in parsed_rows)

        usable_width = max(10, self.w - self.l_margin - self.r_margin)
        col_padding = 3  # points per side

        base_size = int(getattr(self, "_current_font_size", 9))
        font_family = "CJK" if self._has_cjk else "Helvetica"

        # Estimate column widths from content
        col_max_widths = [0.0] * num_cols
        for row in parsed_rows:
            for ci in range(min(num_cols, len(row))):
                cell_text = row[ci]
                # Measure plain text width (without formatting)
                plain = "".join(t for t, _ in _parse_inline(cell_text))
                self.set_font(font_family, "", base_size)
                w = self.get_string_width(plain)
                if w > col_max_widths[ci]:
                    col_max_widths[ci] = w

        total_max = sum(col_max_widths)
        if total_max <= 0:
            col_widths = [usable_width / num_cols] * num_cols
        else:
            col_widths = [max(20, usable_width * cw / total_max) for cw in col_max_widths]

        # Scale to fit usable width
        total_col_w = sum(col_widths)
        if total_col_w > usable_width:
            scale = usable_width / total_col_w
            col_widths = [max(15, cw * scale) for cw in col_widths]

        # Draw table
        row_h = 5.5
        self.set_draw_color(200, 200, 200)
        self.set_line_width(0.2)

        x0 = self.l_margin

        for ri, row in enumerate(parsed_rows):
            # Estimate row height
            max_lines = 1
            for ci in range(min(num_cols, len(row))):
                cell_text = row[ci]
                cell_w = col_widths[ci] - 2 * col_padding
                if cell_w <= 0:
                    continue
                plain = "".join(t for t, _ in _parse_inline(cell_text))
                self.set_font(font_family, "", base_size)
                text_w = self.get_string_width(plain)
                est_lines = max(1, int(text_w / cell_w) + (1 if text_w % cell_w > 0 else 0))
                max_lines = max(max_lines, min(est_lines, 8))  # cap at 8 lines

            cell_height = max(row_h, row_h * max_lines)
            y0 = self.get_y()

            # Page break check
            if y0 + cell_height > self.h - self.b_margin:
                self.add_page()
                y0 = self.get_y()

            # Row background (alternating)
            if ri % 2 == 1:
                self.set_fill_color(248, 248, 248)
                self.rect(x0, y0, sum(col_widths), cell_height, "F")

            # Draw cells
            x_cursor = x0
            for ci in range(num_cols):
                cell_text = row[ci] if ci < len(row) else ""
                cw = col_widths[ci]

                # Cell border
                self.set_draw_color(210, 210, 210)
                self.rect(x_cursor, y0, cw, cell_height, "D")

                # Cell content
                inner_w = cw - 2 * col_padding
                if inner_w > 0 and cell_text:
                    self.set_xy(x_cursor + col_padding, y0 + 1)
                    # Render cell as inline para (single line, truncated to cell width)
                    self._render_inline_para(inner_w, 5, cell_text)

                x_cursor += cw

            # Move to next row
            self.set_xy(x0, y0 + cell_height)

        self.ln(4)

    def _render_markdown(self, text: str) -> None:
        """Render markdown-formatted text with styling, preserving inline formatting and tables."""
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Empty line → small vertical gap
            if not stripped:
                self.ln(3)
                i += 1
                continue

            # Headings: ### → 11pt, ## → 13pt, # → 14pt
            heading_match = re.match(r"^(#{1,4})\s+(.*)", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                if level <= 4:
                    heading_text = heading_match.group(2)
                    sizes = {1: 14, 2: 13, 3: 11, 4: 10}
                    colors = {1: (255, 90, 31), 2: (40, 40, 40), 3: (50, 50, 50), 4: (60, 60, 60)}
                    size = sizes.get(level, 11)
                    r, g, b = colors.get(level, (50, 50, 50))
                    self._use_font("B", size)
                    self.set_text_color(r, g, b)
                    usable_width = max(10, self.w - self.l_margin - self.r_margin)
                    # Strip inline markdown and emoji from headings for clean rendering
                    clean_heading = _replace_emojis(heading_text)
                    clean_heading = re.sub(r"\*\*(.+?)\*\*", r"\1", clean_heading)
                    clean_heading = re.sub(r"\*(.+?)\*", r"\1", clean_heading)
                    clean_heading = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", clean_heading)
                    self._safe_multi_cell(usable_width, size * 0.55, clean_heading)
                    self.ln(4)
                i += 1
                continue

            # Horizontal rule
            if stripped in ("---", "***", "___"):
                self.set_draw_color(180, 180, 180)
                y = self.get_y() + 2
                self.line(self.l_margin, y, self.w - self.r_margin, y)
                self.ln(6)
                i += 1
                continue

            # Blockquote
            if stripped.startswith(">"):
                quote_lines = []
                while i < len(lines):
                    ln = lines[i].strip()
                    if ln.startswith(">"):
                        quote_lines.append(ln.lstrip(">").strip())
                        i += 1
                    elif not ln:
                        i += 1
                        break
                    else:
                        break
                if quote_lines:
                    quote_text = " ".join(quote_lines)
                    self.set_draw_color(220, 220, 220)
                    self.set_line_width(1.5)
                    x0 = self.l_margin + 3
                    y0 = self.get_y()
                    est_lines = max(1, int(len(quote_text) / 60) + 1)
                    self.line(x0, y0, x0, y0 + est_lines * 6)
                    self.set_x(x0 + 5)
                    self._use_font("", 9)
                    self.set_text_color(100, 100, 100)
                    usable_width = max(10, self.w - self.l_margin - self.r_margin - 8)
                    self._render_inline_para(usable_width, 5, quote_text)
                    self.ln(4)
                continue

            # Bullet points (-, *)
            bullet_match = re.match(r"^[-*]\s+(.*)", stripped)
            if bullet_match:
                self._use_font("", 10)
                self.set_text_color(40, 40, 40)
                body = bullet_match.group(1)
                self.cell(6, 5.5, "\u2022")  # bullet character
                self._render_inline_para(self.w - self.l_margin - self.r_margin - 6, 5.5, body)
                i += 1
                continue

            # Numbered list
            num_match = re.match(r"^(\d+[.)])\s+(.*)", stripped)
            if num_match:
                self._use_font("", 10)
                self.set_text_color(40, 40, 40)
                num = num_match.group(1)
                body = num_match.group(2)
                num_w = self.get_string_width(num + "  ")
                self.cell(num_w, 5.5, num)
                self._render_inline_para(self.w - self.l_margin - self.r_margin - num_w, 5.5, body)
                i += 1
                continue

            # Table rows — collect consecutive table lines
            if stripped.startswith("|") and stripped.endswith("|"):
                table_lines = []
                while i < len(lines):
                    ln = lines[i].strip()
                    if ln.startswith("|") and ln.endswith("|"):
                        table_lines.append(ln)
                        i += 1
                    elif not ln:
                        break
                    else:
                        break
                if table_lines:
                    self._render_table(table_lines)
                continue

            # Regular paragraph — collect consecutive non-special lines
            para_lines = []
            while i < len(lines) and lines[i].strip():
                ln = lines[i].strip()
                if ln.startswith("#") or ln.startswith("|") or ln.startswith(">") or \
                   re.match(r"^[-*]\s", ln) or re.match(r"^\d+[.)]\s", ln) or \
                   ln in ("---", "***", "___"):
                    break
                para_lines.append(ln)
                i += 1

            if para_lines:
                self._use_font("", 10)
                self.set_text_color(40, 40, 40)
                para = " ".join(para_lines)
                usable_width = max(10, self.w - self.l_margin - self.r_margin)
                self._render_inline_para(usable_width, 5.5, para)
                self.ln(2)
                continue

            i += 1


def generate_pdf(final_state: dict[str, Any], ticker: str, trade_date: str, signal: str) -> bytes:
    """Generate a PDF report and return it as bytes."""
    # sanitize state: replace emoji with textual placeholders to avoid font embedding issues
    state = _sanitize_state(final_state)

    pdf = _ReportPDF(ticker, trade_date, signal)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    pdf.add_cover()

    for key, title in _REPORT_SECTIONS:
        content = state.get(key, "")
        if content:
            pdf.add_section(title, str(content))

    debate = state.get("investment_debate_state")
    if debate and isinstance(debate, dict):
        parts = []
        if debate.get("bull_history"):
            parts.append(f"=== 多方论点 ===\n{debate['bull_history']}")
        if debate.get("bear_history"):
            parts.append(f"\n=== 空方论点 ===\n{debate['bear_history']}")
        if debate.get("judge_decision"):
            parts.append(f"\n=== 研究经理决策 ===\n{debate['judge_decision']}")
        if parts:
            pdf.add_section("多空辩论", "\n".join(parts))

    trader_decision = state.get("trader_investment_decision", "")
    if trader_decision:
        pdf.add_section("交易员决策", _strip_think(str(trader_decision)))

    inv_plan = state.get("investment_plan", "")
    if inv_plan:
        pdf.add_section("最终投资建议", _strip_think(str(inv_plan)))

    risk = state.get("risk_debate_state")
    if risk and isinstance(risk, dict):
        parts = []
        for key_name, label in [("aggressive_history", "激进观点"),
                                 ("conservative_history", "保守观点"),
                                 ("neutral_history", "中性观点")]:
            if risk.get(key_name):
                parts.append(f"=== {label} ===\n{risk[key_name]}")
        if risk.get("judge_decision"):
            parts.append(f"\n=== 风控决策 ===\n{risk['judge_decision']}")
        if parts:
            pdf.add_section("风控评估", "\n".join(parts))

    final_decision = state.get("final_trade_decision", "")
    if final_decision:
        pdf.add_section("最终决策", _strip_think(str(final_decision)))

    return bytes(pdf.output())
