"""registry.json 동시쓰기 보호(파일 락) 회귀 테스트.

여러 훅(SessionStart/Stop/UserPromptSubmit)이 별도 프로세스로 거의 동시에
같은 registry.json 을 read-modify-write 하면, 락이 없으면 늦게 쓴 쪽이
먼저 쓴 변경을 통째로 덮어써 lost update 가 난다(2026-07-04 session_id
덮어쓰기 사고와 같은 계열). 스레드로 그 상황을 재현해 락이 막는지 검증.
"""
import threading

from imadhd.core.registry import JSONFileRegistry


def test_concurrent_claim_slot_no_duplicate_numbers(tmp_path):
    path = tmp_path / "r.json"
    JSONFileRegistry(path, max_slots=6)  # 파일 초기화

    results = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(6)

    def worker(i):
        reg = JSONFileRegistry(path, max_slots=6)
        barrier.wait()
        n = reg.claim_slot(f"s{i}", hwnd=i, pid=i, cwd="c", started_at="t")
        with results_lock:
            results.append(n)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [1, 2, 3, 4, 5, 6]


def test_concurrent_set_status_by_session_no_lost_update(tmp_path):
    path = tmp_path / "r.json"
    reg = JSONFileRegistry(path, max_slots=6)
    for i in range(6):
        reg.claim_slot(f"s{i}", i, i, "c", "t")

    barrier = threading.Barrier(6)

    def worker(i):
        reg_i = JSONFileRegistry(path, max_slots=6)
        barrier.wait()
        reg_i.set_status_by_session(f"s{i}", "busy")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    reg_final = JSONFileRegistry(path, max_slots=6)
    statuses = {info.session_id: info.status for info in reg_final.active()}
    assert len(statuses) == 6
    assert all(s == "busy" for s in statuses.values()), statuses
