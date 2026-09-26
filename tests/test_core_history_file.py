"""코어의 대화 기록 파일(chat_history)이 무인 운영에서 끝없이 커지던 것.

코어는 메시지 하나마다 기록 파일 전체를 읽고 다시 쓴다. OBS 가 몇 주씩
켜져 있으면(웹UI 가 새로고침되지 않으면) 한 파일이 계속 커진다. 실측:
2만 개에 저장 1회 0.12초, 14만 개에 0.86초 — 한 턴에 두 번씩, 코어의
이벤트 루프를 멈춘 채로. 그리고 원본을 열어 바로 쓰기 때문에, 쓰기가
실패하면(디스크 가득) 원본이 0바이트로 잘려 기록이 통째로 사라졌다.

코어 패키지는 CI 에 없는 loguru 를 쓰므로 그 모듈만 흉내 내고 불러온다.
"""
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

_SRC = (Path(__file__).resolve().parents[1] / "Open-LLM-VTuber" / "src"
        / "open_llm_vtuber" / "chat_history_manager.py")


@pytest.fixture
def chm(tmp_path, monkeypatch):
    if "loguru" not in sys.modules:
        fake = types.ModuleType("loguru")
        fake.logger = types.SimpleNamespace(
            debug=lambda *a, **k: None, info=lambda *a, **k: None,
            warning=lambda *a, **k: None, error=lambda *a, **k: None)
        monkeypatch.setitem(sys.modules, "loguru", fake)
    spec = importlib.util.spec_from_file_location("_chm_under_test", _SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.chdir(tmp_path)
    return mod


def _path(uid):
    return Path("chat_history") / "c" / f"{uid}.json"


def test_기록은_상한까지만_남고_메타데이터는_지켜진다(chm, monkeypatch):
    monkeypatch.setattr(chm, "MAX_HISTORY_MESSAGES", 5)
    uid = chm.create_new_history("c")
    for i in range(12):
        chm.store_message("c", uid, "human", f"말 {i}")
    data = json.loads(_path(uid).read_text(encoding="utf-8"))
    assert data[0]["role"] == "metadata"
    assert [d["content"] for d in data[1:]] == [f"말 {i}" for i in range(7, 12)]


def test_쓰기가_실패해도_원래_기록은_남는다(chm, monkeypatch):
    uid = chm.create_new_history("c")
    chm.store_message("c", uid, "human", "지난 기록")
    before = _path(uid).read_text(encoding="utf-8")

    real_dump = json.dump

    def full_disk(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(chm.json, "dump", full_disk)
    with pytest.raises(OSError):
        chm.store_message("c", uid, "human", "새 기록")
    monkeypatch.setattr(chm.json, "dump", real_dump)
    assert _path(uid).read_text(encoding="utf-8") == before
    # 목록에는 기록 파일만 보인다(쓰다 만 임시 파일은 안 섞인다)
    assert all(h["uid"] != f"{uid}.json.tmp" for h in chm.get_history_list("c"))
