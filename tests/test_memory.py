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


# --------------------- 크래시(정전) 중에도 기억이 남아야 한다 ---------------
def test_memory_survives_crash_midway(tmp_path):
    """방송 중 프로세스가 죽어도 그때까지의 기억이 파일에 남아 있어야 한다.

    예전에는 end_session() 에서만 저장해서, 정전·강제 재부팅이면 그날
    방송 기억이 통째로 사라졌다(실제 실행에서 sessions.json 이 아예
    만들어지지 않는 것을 확인했다).
    """
    import json
    from aist.chat.base import ChatMessage
    from aist.config import MemoryConfig
    from aist.memory import Memory

    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()
    assert m.sessions_file.exists()      # 시작하자마자 파일이 있어야 한다
    m._last_save = 0.0                   # 체크포인트 간격을 강제로 지나가게
    m.note_chat(ChatMessage("별하나", "안녕", "chzzk"))
    saved = json.loads(m.sessions_file.read_text(encoding="utf-8"))
    assert len(saved) == 1
    assert saved[0]["end"] is None
    assert "별하나" in saved[0]["viewers"]


def test_memory_session_not_counted_twice(tmp_path):
    """정상 종료해도 세션이 두 번 들어가면 안 된다(리포트·단골 집계가 틀어진다)."""
    from aist.config import MemoryConfig
    from aist.memory import Memory

    cfg = MemoryConfig(path=str(tmp_path / "mem"))
    m = Memory(cfg)
    m.start_session()
    m.end_session("테스트")
    assert len(m._sessions) == 1
    assert len(Memory(cfg)._sessions) == 1


def test_recent_summary_ignores_live_session(tmp_path):
    """방송 중인 세션은 '저번 방송'이 아니다."""
    from aist.chat.base import ChatMessage
    from aist.config import MemoryConfig
    from aist.memory import Memory

    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()
    m.note_chat(ChatMessage("가", "안녕", "chzzk"))
    m.end_session()
    m.start_session()
    m.note_chat(ChatMessage("나", "하이", "chzzk"))
    assert "1명" in m.recent_summary()
