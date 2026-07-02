"""빈 슬롯 할당 정책. 기본 = 가장 낮은 빈 번호.

확장: sticky(세션별 고정번호), round-robin 등 교체 가능.
"""
from __future__ import annotations


def lowest_free(occupied: set[int], max_slots: int) -> int | None:
    """1..max_slots 중 가장 낮은 빈 번호 반환. 없으면 None."""
    for n in range(1, max_slots + 1):
        if n not in occupied:
            return n
    return None
