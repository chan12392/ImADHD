"""md_to_tg_html 변환 테스트 — 마크다운 → Telegram HTML."""
from imadhd.reply.markup import md_to_tg_html, flatten_tables


def test_bold():
    assert md_to_tg_html("**굵게**") == "<b>굵게</b>"


def test_inline_code():
    assert md_to_tg_html("`code`") == "<code>code</code>"


def test_code_fence():
    out = md_to_tg_html("```python\nprint(1)\n```")
    assert out == "<pre><code>print(1)\n</code></pre>"


def test_code_fence_escapes_inner_html():
    """코드펜스 내부 < > & 이스케이프 — 마크다운으로 오해 X."""
    out = md_to_tg_html("```\n<a> & b\n```")
    assert "&lt;a&gt;" in out
    assert "&amp; b" in out


def test_ampersand_escaped_outside_code():
    assert md_to_tg_html("a & b") == "a &amp; b"


def test_lt_gt_escaped_outside_code():
    assert md_to_tg_html("x < y > z") == "x &lt; y &gt; z"


def test_italic():
    assert md_to_tg_html("*기울임*") == "<i>기울임</i>"


def test_bold_not_confused_by_inner_star_in_code():
    """코드 안의 ** 가 굵게로 변환되지 않아야 함."""
    out = md_to_tg_html("```\n**not bold**\n```")
    assert "<b>" not in out
    assert "**not bold**" in out


def test_mixed():
    out = md_to_tg_html("**중요**: `cmd` 실행")
    assert out == "<b>중요</b>: <code>cmd</code> 실행"


def test_empty():
    assert md_to_tg_html("") == ""


# ---------- flatten_tables (표 → 평문, 텔레그램 모바일은 표 렌더 못 함) ----------

def test_flatten_simple_table():
    md = "| a | b |\n|---|---|\n| 1 | 2 |"
    assert flatten_tables(md) == "a · b\n1 · 2"


def test_flatten_removes_alignment_separator():
    md = "| 항목 | 값 |\n|:---|---:|\n| x | y |"
    out = flatten_tables(md)
    assert "---" not in out
    assert out == "항목 · 값\nx · y"


def test_flatten_table_inside_code_fence_untouched():
    md = "```\n| a | b |\n|---|---|\n```"
    assert flatten_tables(md) == md


def test_flatten_no_table_passthrough():
    assert flatten_tables("일반 텍스트\n둘째 줄") == "일반 텍스트\n둘째 줄"


def test_flatten_empty():
    assert flatten_tables("") == ""


def test_md_to_tg_html_flattens_table_before_html_convert():
    md = "| 항목 | 값 |\n|---|---|\n| **A** | `1` |"
    out = md_to_tg_html(md)
    assert "|" not in out
    assert "<b>A</b>" in out
    assert "<code>1</code>" in out
