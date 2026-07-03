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


# ------------------------- 눈치 종료 -------------------------
class _FakePipe:
    def __init__(self, speaking=False, pending=False, quiet_sec=999.0):
        self.speaking = speaking
        self.pending = pending
        self.quiet = quiet_sec

    def is_speaking(self):
        return self.speaking

    def has_pending(self):
        return self.pending

    def seconds_since_last_chat(self):
        return self.quiet


def _orch():
    from aist.config import Config
    from aist.orchestrator import Orchestrator
    return Orchestrator(Config(), Persona())


def test_natural_pause_immediate_when_quiet():
    o = _orch()
    wd = WindDown(enabled=True, natural_pause_lull_sec=8, max_overtime_minutes=10)
    # 조용 + 말 안 함 → 바로 리턴 (2초 이내)
    asyncio.run(asyncio.wait_for(
        o._wait_natural_pause(_FakePipe(quiet_sec=100), wd), timeout=1))


def test_natural_pause_respects_overtime_cap():
    o = _orch()
    # 계속 말하는 중이어도 상한(0분)이면 기다리지 않고 진행
    wd = WindDown(enabled=True, natural_pause_lull_sec=8, max_overtime_minutes=0)
    asyncio.run(asyncio.wait_for(
        o._wait_natural_pause(_FakePipe(speaking=True), wd), timeout=1))


def test_natural_pause_skipped_when_wind_down_off():
    o = _orch()
    wd = WindDown(enabled=False)
    asyncio.run(asyncio.wait_for(
        o._wait_natural_pause(_FakePipe(speaking=True), wd), timeout=1))
