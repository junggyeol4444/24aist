from aist.chat.base import ChatMessage
from aist.config import MemoryConfig
from aist.memory import Memory


def msg(author, sc=False):
    return ChatMessage(author=author, text="hi", platform="twitch",
                       is_superchat=sc, amount="100" if sc else "")


def test_session_roundtrip(tmp_path):
    m = Memory(MemoryConfig(path=str(tmp_path)))
    m.start_session()
    m.note_chat(msg("neo"))
    m.note_chat(msg("trin", sc=True))
    m.end_session()
    # 새 인스턴스로 재로딩 → 디스크에 저장됐는지
    m2 = Memory(MemoryConfig(path=str(tmp_path)))
    s = m2.recent_summary()
    assert "2명" in s
    assert "슈퍼챗" in s


def test_recent_summary_empty_when_no_history(tmp_path):
    m = Memory(MemoryConfig(path=str(tmp_path)))
    assert m.recent_summary() == ""


def test_regulars_need_two_appearances(tmp_path):
    m = Memory(MemoryConfig(path=str(tmp_path)))
    for _ in range(2):
        m.start_session()
        m.note_chat(msg("regular"))
        m.note_chat(msg("oneoff" if _ == 0 else "another"))
        m.end_session()
    regs = m.regulars()
    assert "regular" in regs
    assert "oneoff" not in regs
