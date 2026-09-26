"""AI 가 쓴 공지를 그대로 올리지 않는다.

말은 흘러가지만 공지는 커뮤니티에 영구히 남는다. 그런데 발화에는 걸려
있던 보호가 공지에는 하나도 없었다 — 길이도, 금지어도, 무대 뒤 지시
누출도 검사 없이 그대로 디스코드·네이버 카페로 나갔다.
"""

from aist.announce.composer import (AnnounceContext, _ANNOUNCE_MAX_CHARS,
                                    announce_problem, compose)
from aist.config import AnnounceConfig
from aist.persona import Persona


class _LLM:
    """LLM 자리에 끼워 원하는 답을 내게 한다."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def available(self):
        return True

    def complete(self, system, user):
        self.calls += 1
        return self.reply


def _compose(reply, banned=()):
    llm = _LLM(reply)
    ctx = AnnounceContext(kind="start", next_stream_hint="내일 20:00")
    return compose(Persona(), ctx, AnnounceConfig(style="varied"),
                   llm=llm, banned=banned)


def test_멀쩡한_공지는_그대로_나간다():
    assert _compose("오늘 방송 켰어요! 놀러와요").startswith("오늘 방송 켰어요")


def test_너무_길면_준비된_문구로_바꾼다():
    """디스코드는 2000자를 넘으면 400 을 준다. 400 은 재시도 대상이 아니라
    그 공지는 조용히 사라진다."""
    out = _compose("가" * (_ANNOUNCE_MAX_CHARS + 1))
    assert "가" * 50 not in out
    assert 0 < len(out) <= _ANNOUNCE_MAX_CHARS


def test_무대_뒤_지시가_새어나오면_안_쓴다():
    out = _compose("오늘 방송 켰어요 (매니저 귓속말: 이건 말하지 마)")
    assert "귓속말" not in out


def test_금지어가_들어가면_안_쓴다():
    out = _compose("오늘 방송 켰어요 시발", banned=["시발"])
    assert "시발" not in out


def test_빈_답도_준비된_문구로_바꾼다():
    assert _compose("   ").strip()


def test_잘라서_올리지_않는다():
    """중간에 끊긴 문장을 올리느니 항상 멀쩡한 문구를 쓴다."""
    out = _compose("오늘 방송 켰어요. " + "그리고 " * 200)
    assert not out.startswith("오늘 방송 켰어요. 그리고 그리고")


def test_사유를_구분해_알려준다():
    assert announce_problem("") == "빈 글"
    assert "너무 김" in announce_problem("가" * (_ANNOUNCE_MAX_CHARS + 1))
    assert "금지어" in announce_problem("나쁜말", ["나쁜말"])
    assert announce_problem("오늘 방송 켰어요") is None
