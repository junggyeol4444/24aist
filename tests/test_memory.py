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

    cfg = MemoryConfig(path=str(tmp_path / "mem"))
    m = Memory(cfg)
    m.start_session()
    assert m.current_file.exists()       # 시작하자마자 파일이 있어야 한다
    m._last_save = 0.0                   # 체크포인트 간격을 강제로 지나가게
    m.note_chat(ChatMessage("별하나", "안녕", "chzzk"))
    saved = json.loads(m.current_file.read_text(encoding="utf-8"))
    assert saved["end"] is None
    assert "별하나" in saved["viewers"]

    # 크래시 뒤 새 프로세스가 읽으면 그 기억이 살아 있어야 한다.
    m2 = Memory(cfg)
    assert len(m2._sessions) == 1
    assert "별하나" in m2._sessions[-1]["viewers"]
    # 다음 방송을 시작하면 정식 기억(sessions.json)으로 옮겨 적는다.
    m2.start_session()
    assert len(json.loads(m2.sessions_file.read_text(encoding="utf-8"))) == 1


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


def test_checkpoint_writes_only_current_session(tmp_path):
    """방송 중 체크포인트는 전체 기억이 아니라 진행 중 세션만 써야 한다.

    전체를 쓰면 1년치(약 27MB)에서 한 번에 380ms 씩 이벤트 루프가 멎고,
    3시간 방송이면 9.5GB 를 디스크에 쓴다(실측). 채팅이 밀린다.
    """
    from aist.chat.base import ChatMessage
    from aist.config import MemoryConfig
    from aist.memory import Memory

    cfg = MemoryConfig(path=str(tmp_path / "mem"))
    m = Memory(cfg)
    for _ in range(50):                 # 지난 방송 기록을 잔뜩 쌓아둔다
        m.start_session()
        m.note_chat(ChatMessage("가", "안녕", "chzzk"))
        m.end_session()
    assert not m.current_file.exists()   # 정상 종료면 진행 중 파일은 없다

    m.start_session()
    before = m.sessions_file.stat().st_mtime_ns
    m._last_save = 0.0
    m.note_chat(ChatMessage("나", "하이", "chzzk"))
    # 체크포인트가 전체 파일을 건드리지 않았어야 한다.
    assert m.sessions_file.stat().st_mtime_ns == before
    assert m.current_file.exists()


def test_recent_summary_skips_failed_short_attempt(tmp_path):
    """사고로 몇십 초 만에 끝난 회차를 "저번 방송" 으로 집으면 안 된다.

    재시도가 생기면서 한 슬롯에 15초짜리 세션이 여러 개 남는다. 그걸
    회상하면 오프닝에서 "저번엔 아무도 없었어" 가 나간다.
    """
    from aist.chat.base import ChatMessage
    from aist.config import MemoryConfig
    from aist.memory import Memory

    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()                       # 제대로 된 방송
    for who in ("가", "나", "다"):
        m.note_chat(ChatMessage(who, "안녕", "chzzk"))
    m.end_session()
    m.start_session()                       # 15초 만에 끝난 시도
    m.end_session()
    assert "3명" in m.recent_summary()


def test_disk_full_checkpoint_does_not_flood_the_log(tmp_path, caplog, monkeypatch):
    """디스크가 차면 체크포인트가 30초마다 같은 ERROR 를 찍는다.

    3시간 방송이면 같은 줄이 340개 쌓여서 회전 로그가 밀린다 — 실제로
    디스크를 채우고 돌려보니 그렇게 나왔다. 처음엔 크게, 그 뒤로는 드물게.
    """
    import logging
    import pathlib

    from aist.config import MemoryConfig
    from aist.memory import Memory

    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()

    def boom(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(pathlib.Path, "write_text", boom)
    with caplog.at_level(logging.ERROR, logger="aist.memory"):
        for _ in range(40):
            m._save_current()
    assert len(caplog.records) == 5          # 1·3·10·20·40 회째만


def test_broken_memory_file_is_kept_not_overwritten(tmp_path):
    """깨진 기억 파일을 덮어쓰면 그동안 쌓인 기록이 통째로 사라진다.

    예전에는 경고 한 줄 남기고 빈 상태로 시작한 뒤, 다음 저장에서 그 파일을
    그대로 덮어썼다. 단골·후원·회차 기록을 되살릴 방법이 없어진다.
    """
    from aist.config import MemoryConfig
    from aist.memory import Memory

    mem = tmp_path / "mem"
    mem.mkdir()
    broken_text = '[{"start": "2026-01-01T00:00:00+00:00", "viewers": ["단골A"'
    (mem / "sessions.json").write_text(broken_text, encoding="utf-8")

    m = Memory(MemoryConfig(path=str(mem)))
    assert m._sessions == []
    m.start_session()
    m.end_session()

    spares = [p for p in mem.iterdir() if "깨짐" in p.name]
    assert len(spares) == 1, sorted(p.name for p in mem.iterdir())
    assert spares[0].read_text(encoding="utf-8") == broken_text
    # 새 기억은 정상으로 쌓인다
    assert len(Memory(MemoryConfig(path=str(mem)))._sessions) == 1


def test_memory_file_with_wrong_shape_is_also_kept(tmp_path):
    """문법은 맞는데 목록이 아닌 경우(예: 통째로 dict)도 마찬가지다."""
    from aist.config import MemoryConfig
    from aist.memory import Memory

    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "sessions.json").write_text('{"세션": "아님"}', encoding="utf-8")
    m = Memory(MemoryConfig(path=str(mem)))
    assert m._sessions == []
    assert any("깨짐" in p.name for p in mem.iterdir())


# --------- 방금 끊겼다 돌아온 방송을 "저번 방송" 이라고 부르면 안 된다 ---------
def test_방금_끊겼다_돌아오면_저번_방송이라고_안_한다(tmp_path):
    """윈도우 업데이트 재부팅 → 무인운영.bat 재시작 시나리오.

    실제로 kill -9 하고 다시 켜보니, 3분 전까지 그 방송을 보고 있던
    시청자에게 "저번 방송 땐 5명 정도 왔었고" 라고 인사했다.
    """
    from aist.chat.base import ChatMessage
    from aist.config import MemoryConfig
    from aist.memory import Memory

    d = tmp_path / "mem"
    m = Memory(MemoryConfig(path=str(d)))
    m.start_session()
    m.note_chat(ChatMessage(author="보던사람", text="ㅎㅇ", platform="t"))
    # end_session 없이 프로세스가 죽었다 → current_session.json 만 남는다
    del m

    again = Memory(MemoryConfig(path=str(d)))
    assert "저번 방송" not in again.recent_summary()
    assert "끊겨서" in again.recent_summary()


def test_한참_전에_끊긴_방송은_그냥_저번_방송이다(tmp_path):
    import json
    from datetime import datetime, timedelta, timezone
    from aist.config import MemoryConfig
    from aist.memory import Memory

    d = tmp_path / "mem"
    d.mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    (d / "current_session.json").write_text(json.dumps({
        "start": old, "end": None, "events": [],
        "viewers": ["어제사람", "그저께사람"], "superchats": [], "summary": "",
    }, ensure_ascii=False), encoding="utf-8")

    m = Memory(MemoryConfig(path=str(d)))
    # crashed_at 은 파일 mtime(방금)이라 start 로 판단해야 한다
    m._sessions[-1].pop("crashed_at", None)
    assert "저번 방송 땐 2명" in m.recent_summary()
