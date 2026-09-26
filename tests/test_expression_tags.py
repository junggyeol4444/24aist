"""AI 발화에 섞여 오는 표정 키워드가 기록을 덮지 않는지.

코어는 LLM 에게 이렇게 지시한다(코어가 실제로 보내는 시스템 프롬프트에서 확인):

    Here are all the expression keywords you can use. Use them regularly:
    - [neutral], [anger], [disgust], [fear], [joy], [smirk], [sadness], [surprise]
    Remember to include the brackets `[]`

시청자에게는 코어가 떼고 보내지만, 우리가 받는 display_text 에는 그대로
남는다. 그래서 리포트의 '사고 발언 점검' 칸이 이렇게 됐다:

    - [joy] 아 그거요?
    - ㅋㅋ [smirk] 저도 어제 그 생각 했어요.

매 문장 넣으라고 지시받은 키워드라, 3시간 방송 전문이 통째로 이 꼴이 된다.
"""

import logging

from aist.config import Config
from aist.orchestrator import Orchestrator
from aist.persona import Persona
from aist.safety import strip_expressions


def test_표정_키워드를_떼어낸다():
    assert strip_expressions("[joy] 아 그거요?") == "아 그거요?"
    assert strip_expressions("ㅋㅋ [smirk] 저도요.") == "ㅋㅋ 저도요."
    assert strip_expressions("[neutral]") == ""


def test_한글_대괄호는_진짜_말일_수_있다():
    assert strip_expressions("[공지] 오늘 방송") == "[공지] 오늘 방송"
    assert strip_expressions("대괄호 [123] 숫자만") == "대괄호 [123] 숫자만"


def test_빈_값에도_안_터진다():
    assert strip_expressions("") == ""
    assert strip_expressions(None) is None


def test_트랜스크립트에_키워드가_안_남는다(tmp_path):
    from datetime import datetime
    from aist.transcript import Transcript

    t = Transcript(str(tmp_path / "tr"))
    t.open_session(datetime.now())
    t.on_core_message({"type": "audio",
                       "display_text": {"text": "[joy] 안녕하세요 [smirk] 오늘도"}})
    t.close()
    body = t.path.read_text(encoding="utf-8")
    assert "[joy]" not in body and "[smirk]" not in body
    assert "안녕하세요" in body


def test_키워드만_있는_발화는_기록하지_않는다(tmp_path):
    from datetime import datetime
    from aist.transcript import Transcript

    t = Transcript(str(tmp_path / "tr"))
    t.open_session(datetime.now())
    t.on_core_message({"type": "audio", "display_text": {"text": "[neutral]"}})
    t.close()
    import json
    rows = [json.loads(l) for l in t.path.read_text(encoding="utf-8").splitlines()]
    assert [r for r in rows if r.get("who") == "ai"] == []


def test_금지어_검사도_떼어낸_말로_한다(tmp_path, caplog):
    """운영자가 영어 단어를 금지어로 넣었을 때 [fear] 같은 태그에 걸리면 안 된다."""
    cfg = Config()
    cfg.memory.path = str(tmp_path / "mem")
    cfg.safety.banned_words = ["fear"]
    o = Orchestrator(cfg, Persona())
    o.memory.start_session()
    with caplog.at_level(logging.ERROR):
        o._watch_output({"type": "audio",
                         "display_text": {"text": "[fear] 무서워요"}}, None, None)
    assert not [r for r in caplog.records if "금지어 감지" in r.getMessage()]
    # 진짜로 말하면 잡아야 한다
    with caplog.at_level(logging.ERROR):
        o._watch_output({"type": "audio",
                         "display_text": {"text": "나는 fear 가 있어"}}, None, None)
    assert [r for r in caplog.records if "금지어 감지" in r.getMessage()]
