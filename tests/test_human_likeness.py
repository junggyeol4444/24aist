"""AI티 제거(운영자 지시) 검증: 무대규칙·귓속말·태그·공지 반복·눈치 종료."""

import asyncio
import random

from aist.announce.composer import AnnounceContext, compose
from aist.config import AnnounceConfig, WindDown
from aist.persona import Persona
from aist.vtuber_bridge import format_chat_line
import aist.orchestrator as orch_mod


# ------------------------- ① 무대규칙 / 귓속말 은닉 -------------------------
def test_persona_has_stage_rules():
    out = Persona(name="별이").render_system_prompt()
    assert "무대 규칙" in out
    assert "귓속말" in out                      # 괄호 안내는 읽지 않는다
    assert "능청스럽게 받아친다" in out          # "AI지?" → RP 로 받아치기(승인)
    assert "구어체" in out                      # 비서 말투 금지
    # 메타 문장(운영자 얘기)이 프롬프트에서 제거됐는지
    assert "운영자가 알려주면" not in out


def test_cues_are_whispers_with_no_leak_instruction():
    for cue in (orch_mod._CUE_WIND_DOWN, orch_mod._CUE_CLOSING):
        assert cue.startswith("(매니저 귓속말:")
        assert "언급하지 마" in cue


# ------------------------- ② 채팅 태그 자연화 -------------------------
def test_chat_line_natural_format():
    assert format_chat_line("안녕", "neo") == "neo: 안녕"
    assert format_chat_line("안녕", "neo", "chzzk") == "neo (치지직): 안녕"
    assert format_chat_line("안녕") == "안녕"
    # 로봇 태그 형식이 아님
    assert "[" not in format_chat_line("안녕", "neo", "twitch")
    assert "/" not in format_chat_line("안녕", "neo", "twitch")


# ------------------------- ③ 공지 반복 방지 -------------------------
def test_announce_history_avoids_repeats(tmp_path):
    persona = Persona()
    cfg = AnnounceConfig(history_size=8)
    hist = tmp_path / "announce_history.json"
    bases = []
    for i in range(6):
        compose(persona, AnnounceContext(kind="start"), cfg,
                rng=random.Random(i), history_path=hist)
    import json
    bases = json.loads(hist.read_text(encoding="utf-8"))
    assert len(bases) == 6
    assert len(set(bases)) == 6      # 최근 이력 안에서 같은 조합 반복 없음


def test_announce_no_history_still_works():
    out = compose(Persona(), AnnounceContext(kind="end"), AnnounceConfig(),
                  rng=random.Random(1))
    assert out


# ------------------------- 눈치껏 종료 -------------------------
def test_wind_down_defaults_are_streamer_like():
    """예고 20분 전, 마무리 인사 후 30~60초 여운. 채팅 소강 대기 필드 없음."""
    wd = WindDown()
    assert wd.pre_notice_minutes_before_end == 20
    assert 30 <= wd.closing_wait_sec <= 60
    # v1 의 '채팅 조용해질 때까지 대기' 필드는 없어야 함
    assert not hasattr(wd, "natural_pause_lull_sec")


class _FakePipe:
    """말하는 중 여부/밀린 채팅 여부만 흉내낸다(채팅 소강과 무관)."""
    def __init__(self, speaking=False, pending=False):
        self.speaking = speaking
        self.pending = pending

    def is_speaking(self):
        return self.speaking

    def has_pending(self):
        return self.pending


def _orch():
    from aist.config import Config
    from aist.orchestrator import Orchestrator
    return Orchestrator(Config(), Persona())


def test_natural_break_returns_immediately_at_a_gap():
    """말 안 하고 밀린 채팅도 없으면 = 지금이 틈 → 바로 마무리로."""
    o = _orch()
    wd = WindDown(enabled=True, end_grace_minutes=5)
    asyncio.run(asyncio.wait_for(
        o._wait_for_natural_break(_FakePipe(speaking=False, pending=False), wd),
        timeout=1))


def test_natural_break_does_not_wait_for_chat_silence():
    """바쁜 채팅이어도(밀린 채팅 없고 말 안 하면) 틈으로 본다 — 소강 무관."""
    o = _orch()
    wd = WindDown(enabled=True, end_grace_minutes=5)
    # 채팅이 방금 왔든 말든(_FakePipe 는 채팅 시각을 안 봄) 발화·백로그만 본다
    asyncio.run(asyncio.wait_for(
        o._wait_for_natural_break(_FakePipe(speaking=False, pending=False), wd),
        timeout=1))


def test_natural_break_grace_cap_when_never_idle():
    """말/밀린채팅이 안 끝나도 grace 상한(0분)이면 마무리로 진행."""
    o = _orch()
    wd = WindDown(enabled=True, end_grace_minutes=0)
    asyncio.run(asyncio.wait_for(
        o._wait_for_natural_break(_FakePipe(speaking=True, pending=True), wd),
        timeout=1))


def test_closing_and_wind_down_cues_are_whispers():
    assert orch_mod._CUE_WIND_DOWN.startswith("(매니저 귓속말:")
    assert orch_mod._CUE_CLOSING.startswith("(매니저 귓속말:")
