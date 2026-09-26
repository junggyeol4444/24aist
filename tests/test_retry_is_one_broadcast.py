"""같은 슬롯을 다시 켜는 건 '같은 방송'이다 — 회차를 쪼개면 안 된다.

실제 실행(LLM 을 죽여놓고 스케줄러를 돌림)에서, 10초 만에 죽고 두 번
다시 켠 슬롯 하나가 기억에 회차 3개로 남았다. 그러면:
  - 그 10초짜리에 들어온 시청자가 '세 방송 출석'으로 세어져 단골이 된다
  - 다음 방송 오프닝이 그 10초짜리를 "저번 방송" 이라고 부른다
  - 리포트는 마지막 시도만 담아서 앞 시도에 온 시청자가 통째로 빠진다
"""

from aist.config import MemoryConfig
from aist.memory import Memory
from aist.chat.base import ChatMessage


def _mem(tmp_path):
    return Memory(MemoryConfig(path=str(tmp_path / "mem")))


def _chat(nick):
    return ChatMessage(author=nick, text="안녕", platform="test")


def test_재시도는_같은_회차로_이어진다(tmp_path):
    m = _mem(tmp_path)
    m.start_session()
    m.note_chat(_chat("첫시도에온사람"))
    # 사고 → 회차를 닫지 않고 다시 켠다
    m.start_session(resume=True)
    m.note_chat(_chat("두번째시도에온사람"))
    m.end_session()

    assert len(m._sessions) == 1
    viewers = m._sessions[0]["viewers"]
    # 앞 시도에 온 시청자가 사라지면 안 된다
    assert viewers == ["첫시도에온사람", "두번째시도에온사람"]


def test_재시도가_아니면_새_회차를_연다(tmp_path):
    m = _mem(tmp_path)
    m.start_session()
    m.note_chat(_chat("어제사람"))
    m.end_session()
    m.start_session()
    m.note_chat(_chat("오늘사람"))
    m.end_session()
    assert len(m._sessions) == 2


def test_한_슬롯_세_번_시도해도_단골이_되지_않는다(tmp_path):
    """전에는 한 슬롯을 세 번 시도하면 그 사람이 단골로 잡혔다."""
    m = _mem(tmp_path)
    m.start_session()
    for _ in range(3):
        m.start_session(resume=True)
        m.note_chat(_chat("한번왔을뿐인사람"))
    m.end_session()
    assert m.regulars() == []


def test_안_닫힌_회차가_남아_있으면_다음_시작때_닫는다(tmp_path):
    """재시도 도중 중단되면 끝 시각 없는 회차가 남을 수 있다."""
    m = _mem(tmp_path)
    m.start_session()
    m.note_chat(_chat("사람"))
    # end_session 없이 다음 방송이 시작된 상황
    m.start_session()
    assert m._sessions[0]["end"] is not None
    assert len(m._sessions) == 2
