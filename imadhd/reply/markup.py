"""마크다운 → Telegram HTML 변환.

배경(2026-07-03): 답장 회신을 Markdown V1(parse_mode="Markdown")로 보냈으나
코드펜스(\\`\\`\\`) 미지원 → 400 → plain 폴백 → "마크다운 안 됨" 증상.
Telegram HTML 모드(`parse_mode="HTML"`)는 <pre><code>/<b>/<i> 지원, 이스케이프는
&<> 만이라 가장 견고. 본 모듈이 마크다운을 HTML로 변환.

지원:
  - ```lang\\n...```  → <pre><code>...</code></pre> (lang 무시, 내부 이스케이프)
  - `inline`          → <code>...</code> (내부 이스케이프)
  - **굵게**          → <b>굵게</b>
  - *이탤릭*          → <i>이탤릭</i>
  - & < >             → 이스케이프 (코드 블록 밖)
  - 마크다운 표        → 평문 줄(가운뎃점 구분)로 평탄화 — 텔레그램 모바일은
    표를 렌더 못 해 파이프/구분선이 그대로 깨져 보임(대표님 지적, 2026-07-04)

코드 블록은 변환 중 sentinel(private use area)로 치환해 둔 뒤, 본문 이스케이프/
굵게 변환 후 복원 → 코드 내부의 * & < 가 마크다운으로 오해되지 않음.
"""
from __future__ import annotations

import re

# private use area sentinel — _esc() 와 마크다운 정규식에 안 걸림.
_SENT = ""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")


def _is_separator_row(line: str) -> bool:
    """표 헤더 구분선(예: |---|:--:|) 여부. -/:/|/공백만으로 구성 + '-' 최소 1개."""
    s = line.strip()
    return bool(s) and bool(re.fullmatch(r"[|\-:\s]+", s)) and "-" in s


def flatten_tables(text: str) -> str:
    """마크다운 표를 가운뎃점 구분 평문 줄로 평탄화. 코드펜스 내부는 건드리지 않음.

    "| a | b |" 행 → "a · b". 구분선("|---|---|") 행은 제거.
    표가 아닌 일반 텍스트는 그대로 통과.
    """
    if not text or "|" not in text:
        return text
    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out_lines.append(line)
            continue
        if in_fence:
            out_lines.append(line)
            continue
        if _is_separator_row(line):
            continue  # 구분선은 통째로 제거(정보 없음)
        m = _ROW_RE.match(line)
        if m:
            cells = [c.strip() for c in m.group(1).split("|")]
            out_lines.append(" · ".join(cells))
        else:
            out_lines.append(line)
    return "\n".join(out_lines)


def md_to_tg_html(text: str) -> str:
    """마크다운 텍스트 → Telegram HTML 문자열. 표는 먼저 평문으로 평탄화."""
    if not text:
        return ""
    text = flatten_tables(text)
    slots: list[str] = []

    # 1) 코드펜스 ```lang\n...\n```  (lang/개행 옵션, 비탐욕 본문)
    def _fence(m: re.Match) -> str:
        slots.append(f"<pre><code>{_esc(m.group(1))}</code></pre>")
        return f"{_SENT}{len(slots) - 1}{_SENT}"

    text = re.sub(r"```[^\n`]*\n?(.*?)```", _fence, text, flags=re.DOTALL)

    # 2) 인라인 코드 `...`
    def _inline(m: re.Match) -> str:
        slots.append(f"<code>{_esc(m.group(1))}</code>")
        return f"{_SENT}{len(slots) - 1}{_SENT}"

    text = re.sub(r"`([^`\n]+)`", _inline, text)

    # 3) 본문 이스케이프 (코드는 이미 sentinel 치환됨)
    text = _esc(text)

    # 4) 굵게 / 이탤릭
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", text)

    # 5) 코드 슬롯 복원
    def _restore(m: re.Match) -> str:
        return slots[int(m.group(1))]

    text = re.sub(f"{_SENT}(\\d+){_SENT}", _restore, text)
    return text
