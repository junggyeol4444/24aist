"""AI 가 금지어를 말했을 때 실제로 어떻게 되는지.

모의 LLM 이 금지어가 든 문장만 답하게 해놓고 진짜 코어로 방송을 돌려봤다.
발화 4개가 전부 금지어였는데:
  - 리포트에는 그 얘기가 한 줄도 없었다("발화가 걸림 1회" 만 있었다)
  - 방송은 예정 시간까지 그대로 돌았다

'사고 발언 점검' 리포트가 정작 사고를 빠뜨리고, 끼어들기는 이미 나간
말을 되돌리지 못하는데 몇 시간이든 그 상태로 계속할 수 있었다.
"""

import asyncio

from aist.config import Config
from aist.orchestrator import Orchestrator
from aist.persona import Persona
from aist.report import _EVENT_LABEL, _SERIOUS, _trouble_lines


class _Bridge:
    async def interrupt(self, heard_text=""):
        return None


def _orch(tmp_path, strikes=3, stop_on_hit=False):
    cfg = Config()
    cfg.memory.path = str(tmp_path / "mem")
    cfg.safety.banned_words = ["사고단어"]
    cfg.safety.banned_max_strikes = strikes
    cfg.safety.stop_broadcast_on_hit = stop_on_hit
    o = Orchestrator(cfg, Persona())
    o.memory.start_session()
    return o


def _say(o, text="이건 사고단어 입니다"):
    async def go():
        # 발화마다 새 대화가 시작된다 — 끼어들기는 발화당 한 번
        o._watch_output({"type": "control", "text": "conversation-chain-start"},
                        _Bridge(), None)
        o._watch_output({"type": "audio", "display_text": {"text": text}},
                        _Bridge(), None)
        await asyncio.sleep(0)
    asyncio.run(go())


def test_금지어_발화가_기억에_남아_리포트에_나온다(tmp_path):
    o = _orch(tmp_path)
    _say(o)
    kinds = [e["kind"] for e in o.memory._cur["events"]]
    assert "banned_word" in kinds, "리포트의 원천인 기억에 안 남았다"
    ev = [e for e in o.memory._cur["events"] if e["kind"] == "banned_word"][0]
    assert ev["word"] == "사고단어"
    assert "사고단어" in ev["text"]


def test_반복되면_방송을_내린다(tmp_path):
    o = _orch(tmp_path, strikes=3)
    for _ in range(2):
        _say(o)
    assert not o._stop.is_set(), "두 번은 오탐일 수 있다 — 아직 내리면 안 된다"
    _say(o)
    assert o._stop.is_set(), "세 번째인데도 계속 돈다"
    kinds = [e["kind"] for e in o.memory._cur["events"]]
    assert "banned_gave_up" in kinds


def test_0이면_안_내린다(tmp_path):
    o = _orch(tmp_path, strikes=0)
    for _ in range(10):
        _say(o)
    assert not o._stop.is_set()
    kinds = [e["kind"] for e in o.memory._cur["events"]]
    assert kinds.count("banned_word") == 10


def test_한_번에_내리는_설정은_그대로(tmp_path):
    o = _orch(tmp_path, stop_on_hit=True)
    _say(o)
    assert o._stop.is_set()


def test_멀쩡한_발화는_아무_일도_없다(tmp_path):
    o = _orch(tmp_path)
    for _ in range(10):
        _say(o, "오늘 방송 재밌었어요")
    assert not o._stop.is_set()
    assert o.memory._cur["events"] == []


def test_리포트가_사고로_취급한다():
    for k in ("banned_word", "banned_gave_up"):
        assert k in _SERIOUS and k in _EVENT_LABEL
    out = _trouble_lines([{"kind": "banned_word"}, {"kind": "banned_word"},
                          {"kind": "banned_gave_up"}])
    assert out and "금지어" in out[0]
