"""host._decode_console_input CP 인식 디코딩 테스트.

2026-07-06 실사고: host.py keyboard_loop 가 콘솔 STDIN 을 utf-8 하드코딩
디코딩. 한국어 Windows 콘솔 입력 CP=949 → 한글 바이트(CP949)를 UTF-8 로
오해석 → mojibake(영어 ASCII 는 CP 무관 정상). 수리 = GetConsoleCP 기반
디코딩(_decode_console_input).
"""


from imadhd.host import _decode_console_input


def test_decode_cp949_korean():
    """한글 Windows 기본 CP949 바이트 → 정확 한글 복원."""
    raw = "한글".encode("cp949")
    assert _decode_console_input(raw, 949) == "한글"


def test_decode_cp949_english_passthrough():
    """영어 ASCII 는 CP 무관 그대로(버그 상태서도 정상이던 이유)."""
    assert _decode_console_input(b"hello", 949) == "hello"


def test_decode_utf8_cp_65001():
    """WT 등 CP=65001(UTF-8) 환경에서도 정상."""
    raw = "한글".encode("utf-8")
    assert _decode_console_input(raw, 65001) == "한글"


def test_decode_cp949_not_misread_as_utf8():
    """예전 버그(CP949 바이트를 utf-8 로 풀면 mojibake) 회귀 방지."""
    raw = "안녕".encode("cp949")
    bad = raw.decode("utf-8", "replace")  # 예전 하드코딩 utf-8 동작
    assert bad != "안녕"  # 실제 깨짐 확인
    assert _decode_console_input(raw, 949) == "안녕"  # 수리 후 정상


def test_decode_unknown_cp_falls_back_utf8():
    """Python 이 모르는 CP 번호 → utf-8 replace 폴백(크래시 방지)."""
    raw = "한글".encode("utf-8")
    # 존재 않는 임의 CP 번호 — LookupError → utf-8 폴백
    assert _decode_console_input(raw, 99999) == "한글"
