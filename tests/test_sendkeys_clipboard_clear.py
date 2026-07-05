"""_paste_clipboard 클립보드 보안 단위 테스트.

백업이 없던(bak is None) 경우, 주입한 텍스트가 전역 클립보드에 잔류하면
안 됨 — Telegram 명령에 토큰/민감 지시가 섞일 수 있으므로 EmptyClipboard 로 비움.
user32/클립보드 헬퍼 monkeypatch 로 검증 (실제 클립보드 사용 안 함)."""
import imadhd.transports.sendkeys_win as sk


class _FakeUser32:
    def __init__(self):
        self.emptied = 0
        self.opened = 0
        self.closed = 0

    def OpenClipboard(self, *_a):
        self.opened += 1
        return True

    def EmptyClipboard(self, *_a):
        self.emptied += 1
        return True

    def CloseClipboard(self, *_a):
        self.closed += 1
        return True

    def keybd_event(self, *_a, **_k):
        return None


def _patch(monkeypatch, bak):
    fake = _FakeUser32()
    monkeypatch.setattr(sk, "user32", fake)
    monkeypatch.setattr(sk, "_clipboard_read_text", lambda: bak)
    set_calls = []
    monkeypatch.setattr(sk, "_clipboard_set_text", lambda t: set_calls.append(t) or True)
    monkeypatch.setattr(sk.time, "sleep", lambda *_a: None)
    return fake, set_calls


def test_paste_clears_clipboard_when_no_backup(monkeypatch):
    fake, _ = _patch(monkeypatch, bak=None)
    sk._paste_clipboard("top-secret-command")
    # 백업 없으면 주입 텍스트 잔류 방지 위해 EmptyClipboard 1회 호출
    assert fake.emptied == 1
    assert fake.opened == 1
    assert fake.closed == 1


def test_paste_restores_backup_when_present(monkeypatch):
    fake, set_calls = _patch(monkeypatch, bak="original-clip")
    sk._paste_clipboard("command-text")
    # 백업 있으면 복원 경로 — EmptyClipboard(주입용)는 _clipboard_set_text 내부에서
    # 호출되지만 finally의 else(클리어) 분기는 안 탄다 → fake.emptied == 0
    # (주입은 _clipboard_set_text 가 처리, finally는 복원만)
    assert fake.emptied == 0
    # 마지막 set 호출 = 백업 복원
    assert set_calls[-1] == "original-clip"
