from imadhd.core.numberalloc import lowest_free


def test_returns_lowest_free_when_empty():
    assert lowest_free(set(), 6) == 1


def test_returns_next_lowest():
    assert lowest_free({1}, 6) == 2
    assert lowest_free({1, 2, 4}, 6) == 3


def test_fills_gap():
    assert lowest_free({1, 3}, 6) == 2


def test_returns_none_when_full():
    assert lowest_free({1, 2, 3, 4, 5, 6}, 6) is None


def test_ignores_out_of_range():
    assert lowest_free({1, 2, 3, 4, 5, 6, 7, 8}, 6) is None
