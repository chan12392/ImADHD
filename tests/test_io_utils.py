import json

from imadhd.core import io_utils


def test_atomic_write_json_creates_parent_and_cleans_tmp(tmp_path):
    path = tmp_path / "nested" / "data.json"
    io_utils.atomic_write_json(path, {"x": "한글", "n": 1})

    assert json.loads(path.read_text(encoding="utf-8")) == {"x": "한글", "n": 1}
    assert not list(path.parent.glob("*.tmp"))


def test_atomic_write_json_replaces_existing_file(tmp_path):
    path = tmp_path / "data.json"
    path.write_text('{"old": true}', encoding="utf-8")

    io_utils.atomic_write_json(path, {"new": True})

    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}


def test_debug_log_appends_under_imadhd_home(monkeypatch, tmp_path):
    monkeypatch.setattr(io_utils.Path, "home", lambda: tmp_path)

    io_utils.debug_log("line 1")
    io_utils.debug_log("line 2")

    assert (tmp_path / ".imadhd" / "debug.log").read_text(encoding="utf-8") == (
        "line 1\nline 2\n"
    )
