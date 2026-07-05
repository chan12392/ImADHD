"""PipeWinTransport 단위 테스트.

실제 named pipe / Windows 창 / ctypes 호출 없이
_pipe_write 헬퍼와 캐시된 SendKeysWinTransport 만 monkeypatch 해서 검증.
"""
from imadhd.transports.base import InjectResult
from imadhd.transports.pipe_win import PipeWinTransport


class _FakeSendKeys:
    """SendKeysWinTransport 대용. 호출 기록 + 제어 가능한 반환값."""

    def __init__(self) -> None:
        self.inject_calls: list = []
        self.is_alive_calls: list = []
        self.send_key_calls: list = []
        self.inject_ret = InjectResult(delivered=True, method="focus",
                                       note="fake-focus")
        self.is_alive_ret = True

    def inject(self, target, text, background=False):
        self.inject_calls.append((target, text, background))
        return self.inject_ret

    def is_alive(self, target):
        self.is_alive_calls.append(target)
        return self.is_alive_ret

    def send_key(self, target, vk):
        self.send_key_calls.append((target, vk))
        return InjectResult(delivered=True, method="focus-vk", note="fake-vk")


def _new_with_fake_fallback():
    """PipeWinTransport 인스턴스 + 이미 주입된 fake fallback."""
    t = PipeWinTransport()
    fake = _FakeSendKeys()
    t._fallback = fake  # lazy 생성 우회: 직접 fake 주입
    return t, fake


# ---------------------------------------------------------------------------
# 1. pipe open/write 성공 → method="pipe", fallback 미호출
# ---------------------------------------------------------------------------
def test_pipe_success(monkeypatch):
    t, fake = _new_with_fake_fallback()

    writes = []

    def fake_pipe_write(path, data):
        writes.append((path, data))
        return True

    monkeypatch.setattr(t, "_pipe_write", fake_pipe_write)

    result = t.inject({"number": 3}, "hello\nworld")

    assert result.delivered is True
    assert result.method == "pipe"
    assert result.note.startswith("named pipe")
    # payload: text 내 \n → space 치환 + 끝에 \n append
    assert writes == [(r"\\.\pipe\imadhd-slot-3", b"hello world\n")]
    # 폴백 미호출
    assert fake.inject_calls == []


# ---------------------------------------------------------------------------
# 2. pipe open 예외 → fallback 위임 + method "fallback:" prefix
# ---------------------------------------------------------------------------
def test_pipe_raise_falls_back(monkeypatch):
    t, fake = _new_with_fake_fallback()
    fake.inject_ret = InjectResult(delivered=True, method="focus", note="ok")

    def boom(path, data):
        raise FileNotFoundError("pipe not found")

    monkeypatch.setattr(t, "_pipe_write", boom)

    target = {"number": 3, "hwnd": 12345}
    result = t.inject(target, "hello")

    # 폴백 호출 — 동일 target/text/background
    assert fake.inject_calls == [(target, "hello", False)]
    # method 앞에 fallback: prefix
    assert result.method == "fallback:focus"
    assert result.delivered is True


# ---------------------------------------------------------------------------
# 3. pipe_write 가 False 리턴하는(예외 아닌) 경로도 폴백
# ---------------------------------------------------------------------------
def test_pipe_false_falls_back(monkeypatch):
    t, fake = _new_with_fake_fallback()
    monkeypatch.setattr(t, "_pipe_write", lambda p, d: False)

    result = t.inject({"number": 5}, "x")

    assert result.method.startswith("fallback:")
    assert len(fake.inject_calls) == 1


# ---------------------------------------------------------------------------
# 4. target 에 number 없으면 _pipe_write 부르지 않고 폴백 (no crash)
# ---------------------------------------------------------------------------
def test_no_number_falls_back(monkeypatch):
    t, fake = _new_with_fake_fallback()

    pipe_calls = []
    monkeypatch.setattr(t, "_pipe_write",
                        lambda p, d: pipe_calls.append((p, d)) or True)

    target = {"hwnd": 12345}  # number 키 없음
    result = t.inject(target, "hello")

    assert pipe_calls == []  # 파이프 경로 진입 안 함
    assert len(fake.inject_calls) == 1
    assert fake.inject_calls[0][0] is target
    assert fake.inject_calls[0][1] == "hello"


# ---------------------------------------------------------------------------
# 5. is_alive 위임
# ---------------------------------------------------------------------------
def test_is_alive_delegates():
    t, fake = _new_with_fake_fallback()
    fake.is_alive_ret = True

    target = {"number": 1, "pid": 100}
    out = t.is_alive(target)

    assert out is True
    assert fake.is_alive_calls == [target]


# ---------------------------------------------------------------------------
# 6. send_key 위임 (PoC: 포커스 경로)
# ---------------------------------------------------------------------------
def test_send_key_delegates():
    t, fake = _new_with_fake_fallback()

    target = {"number": 1, "hwnd": 999}
    out = t.send_key(target, 0x1B)

    assert out.method == "focus-vk"
    assert fake.send_key_calls == [(target, 0x1B)]


# ---------------------------------------------------------------------------
# 7. UTF-8 다중바이트 payload (한글 등) 도 그대로 write
# ---------------------------------------------------------------------------
def test_utf8_payload(monkeypatch):
    t, fake = _new_with_fake_fallback()

    writes = []
    monkeypatch.setattr(t, "_pipe_write",
                        lambda p, d: writes.append((p, d)) or True)

    t.inject({"number": 7}, "안녕\n클로이")

    path, data = writes[0]
    assert path == r"\\.\pipe\imadhd-slot-7"
    assert data == "안녕 클로이\n".encode("utf-8")
