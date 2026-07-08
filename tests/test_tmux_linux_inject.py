"""tmux_linux transport 핵심 주입 로직 단위 테스트.

2026-07-08 추가: _paste_inject / _wait_idle / _inject_worker 를 subprocess.run
mock 으로 검증. 이전엔 _resolve_target 순수 함수만 테스트해, Linux 실사고로
만든 회복 로직(Enter→C-j 4회, busy race 재시도, stuck 복구)이 회귀에 무방비했다.

이 테스트는 transport=tmux_linux 경로만 검증. Windows(sendkeys_win/pipe_win)
경로엔 영향 없음.
"""
import importlib
import threading
import time

import imadhd.transports.tmux_linux as tl


def _reload(monkeypatch, **env):
    """모듈 리로드 + TMUX_TARGET 전역값 확정(import 시점 평가)."""
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    importlib.reload(tl)


def _run_recorder(monkeypatch, returncode=0, stdout=""):
    """subprocess.run 기록용. _run() 내부 subprocess.run 을 가로채."""
    calls = []

    class _R:
        pass

    def fake_run(args, input_text=None, **kwargs):
        calls.append(list(args))
        r = _R()
        r.returncode = returncode
        r.stdout = stdout
        return r

    monkeypatch.setattr(tl, "_run", fake_run)
    return calls


def test_paste_inject_success(monkeypatch):
    """paste 직후 stuck → Enter 1회로 busy 전환 = 성공."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    states = iter(["idle", "stuck", "busy"])  # paste전 idle, paste후 stuck, Enter후 busy
    monkeypatch.setattr(tl, "_state", lambda t: next(states))
    calls = _run_recorder(monkeypatch)

    assert tl._paste_inject("%7", "hello") is True
    # load-buffer, paste-buffer 호출 후 Enter 시도.
    flat = [c for c in calls]
    assert any("load-buffer" in c for c in flat)
    assert any("paste-buffer" in c for c in flat)
    assert any("send-keys" in c and "Enter" in c for c in flat)


def test_paste_inject_non_idle_aborts(monkeypatch):
    """paste 직전 idle 아니면 즉시 False (busy race 보호)."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    monkeypatch.setattr(tl, "_state", lambda t: "busy")
    calls = _run_recorder(monkeypatch)

    assert tl._paste_inject("%7", "hello") is False
    # paste 전 busy → load-buffer/paste-buffer 자체 호출 안 함.
    assert not any("paste-buffer" in c for c in calls)


def test_paste_inject_enter_c_j_sequence_until_success(monkeypatch):
    """Enter 만으로 안 풀리는 stuck → C-j 폴백으로 제출(2026-07-07 사고 복구)."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    states = iter(["idle", "stuck", "stuck", "stuck", "busy"])
    monkeypatch.setattr(tl, "_state", lambda t: next(states))
    calls = _run_recorder(monkeypatch)

    assert tl._paste_inject("%7", "hi") is True
    # Enter, C-j, Enter, C-j 순서대로 시도하다 busy 도달.
    send_seqs = [c for c in calls if "send-keys" in c]
    keys_tried = []
    for c in send_seqs:
        for arg in c:
            if arg in ("Enter", "C-j"):
                keys_tried.append(arg)
    # busy 도달 시점까지 Enter→C-j→Enter 시도 후 성공.
    assert "C-j" in keys_tried, "C-j 폴백이 누락되면 안 됨"


def test_paste_inject_all_four_attempts_fail(monkeypatch):
    """4회(Enter/C-j 번갈아) 시도 후에도 stuck → False."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    states = iter(["idle"] + ["stuck"] * 10)
    monkeypatch.setattr(tl, "_state", lambda t: next(states))
    _run_recorder(monkeypatch)

    assert tl._paste_inject("%7", "hi") is False


def test_wait_idle_returns_immediately_when_idle(monkeypatch):
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    monkeypatch.setattr(tl, "_state", lambda t: "idle")
    assert tl._wait_idle("%7", timeout=5.0) == "idle"


def test_wait_idle_returns_dead(monkeypatch):
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    monkeypatch.setattr(tl, "_state", lambda t: "dead")
    assert tl._wait_idle("%7", timeout=5.0) == "dead"


def test_wait_idle_rescues_stuck_with_enter(monkeypatch):
    """stuck → Enter 복구 → idle 전환."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    states = iter(["stuck", "stuck", "idle"])  # 1st stuck, Enter후 still stuck, C-j후 idle
    monkeypatch.setattr(tl, "_state", lambda t: next(states))
    _run_recorder(monkeypatch)

    assert tl._wait_idle("%7", timeout=5.0) == "idle"


def test_inject_worker_dead_aborts(monkeypatch):
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    monkeypatch.setattr(tl, "_wait_idle", lambda t, timeout=45.0: "dead")
    monkeypatch.setattr(tl, "_paste_inject", lambda t, x: True)
    # 예외 없이 종료되면 됨(dead → return).
    tl._inject_worker("%7", "hello")


def test_inject_worker_retries_on_paste_fail_then_succeeds(monkeypatch):
    """busy race 첫 주입 실패 → 재시도 → 성공(2026-07-07 첫 메시지 유실 복구)."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    monkeypatch.setattr(tl, "_wait_idle", lambda t, timeout=45.0: "idle")
    results = iter([False, True])  # 1차 실패, 2차 성공
    monkeypatch.setattr(tl, "_paste_inject", lambda t, x: next(results))
    monkeypatch.setattr(tl.time, "sleep", lambda s: None)

    # _inject_worker 는 결과 반환 없음. 예외 없이 완료되면 성공 경로.
    tl._inject_worker("%7", "hello")


def test_inject_worker_dead_releases_pane_lock(monkeypatch):
    """dead 중단 시에도 pane lock 은 정상 해제(with 블록 종료)."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    monkeypatch.setattr(tl, "_wait_idle", lambda t, timeout=45.0: "dead")
    monkeypatch.setattr(tl, "_paste_inject", lambda t, x: True)
    tl._inject_worker("%7", "hello")

    # lock 이 해제됐는지 직접 획득 시도해 검증(non-blocking).
    lk = tl._get_pane_lock("%7")
    assert lk.acquire(blocking=False), "dead 중단 후 pane lock 이 잔존하면 안 됨"
    lk.release()


def test_pane_lock_is_per_pane(monkeypatch):
    """서로 다른 pane 은 각각 별도 Lock (2026-07-08 전역 Lock → pane별)."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    lk_a = tl._get_pane_lock("%7")
    lk_b = tl._get_pane_lock("%8")
    assert lk_a is not lk_b, "서로 다른 pane 은 별도 Lock 이어야 함"

    # 같은 pane 재조회 = 동일 객체.
    assert tl._get_pane_lock("%7") is lk_a


def test_concurrent_different_panes_not_serialized(monkeypatch):
    """서로 다른 pane 동시 주입은 직렬화되지 않아야 함(전역 Lock 회귀 방지)."""
    _reload(monkeypatch, IMADHD_TMUX_PREFIX=None)
    monkeypatch.setattr(tl, "_wait_idle", lambda t, timeout=45.0: "idle")
    monkeypatch.setattr(tl, "_paste_inject", lambda t, x: (time.sleep(0.1), True)[1])
    monkeypatch.setattr(tl.time, "sleep", lambda s: None)

    order = []

    def worker(pane):
        order.append(("start", pane))
        tl._inject_worker(pane, "x")
        order.append(("end", pane))

    threads = [
        threading.Thread(target=worker, args=("%7",)),
        threading.Thread(target=worker, args=("%8",)),
    ]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    # 전역 Lock 이었다면 %7 end 가 %8 start보다 먼저였을 것.
    # pane별 Lock 이면 두 start 가 연속으로 나오는 구간이 있어야 함.
    starts = [o for o in order if o[0] == "start"]
    assert len(starts) == 2
