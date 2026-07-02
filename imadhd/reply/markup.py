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

코드 블록은 변환 중 sentinel(private use area)로 치환해 둔 뒤, 본문 이스케이프/
굵게 변환 후 복원 → 코드 내부의 * & < 가 마크다운으로 오해되지 않음.
"""
from __future__ import annotations

import re

# private use area sentinel — _esc() 와 마크다운 정규식에 안 걸림.
_SENT = ""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def md_to_tg_html(text: str) -> str:
    """마크다운 텍스트 → Telegram HTML 문자열."""
    if not text:
        return ""
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
