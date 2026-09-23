"""방송 중 사고가 리포트에 남는지.

코어를 실제로 죽였다 살린 실행에서, 리포트에는 "tts_silent" 한 줄만
찍혀 있었다. 그 방송은 코어가 끊기고 5분 넘게 소리가 안 나가고 결국
스스로 내려간 방송이었는데, 운영자는 리포트만 보고 TTS 만 고치면 되는 줄
알게 된다. 로그에만 있고 리포트에 없는 사고는 없는 것과 같다.
"""

from aist.report import _EVENT_LABEL, _SERIOUS, _trouble_lines


def test_사고가_있으면_맨_위에_한_줄로_요약된다():
    events = [
        {"kind": "core_lost"},
        {"kind": "core_stuck"}, {"kind": "core_stuck"},
        {"kind": "core_mute"},
        {"kind": "ended_early"},
    ]
    out = _trouble_lines(events)
    assert out, "사고가 있는데 요약이 비었다"
    head = out[0]
    assert "정상적으로 굴러가지 않았습니다" in head
    assert "코어 연결이 끊김 1회" in head
    assert "발화가 걸림(말 끝 신호가 안 옴) 2회" in head
    # 스스로 내려간 방송이면 어디를 봐야 하는지까지 알려준다
    assert any("OPERATOR.md" in x for x in out[1:])


def test_사고가_없으면_아무_말도_안_한다():
    # TTS 무음은 따로 안내한다(일부러 자막만 쓰는 운영자도 있다).
    assert _trouble_lines([{"kind": "tts_silent"}, {"kind": "game"}]) == []
    assert _trouble_lines([]) == []


def test_모든_사고_이름에_한국어_설명이_있다():
    """영어 키가 그대로 리포트에 나가면 운영자는 뜻을 모른다."""
    missing = [k for k in _SERIOUS if k not in _EVENT_LABEL]
    assert missing == [], f"설명 없는 이벤트: {missing}"


def test_조용히_넘어가던_사고들도_리포트에_남는다():
    """로그에만 있고 리포트에 없으면 없는 것과 같다.

    아래 셋은 '방송이 통째로 헛돌았다' 는 뜻인데 리포트에 한 줄도 없었다:
      - 채팅 소스를 아예 못 만든 경우(객체가 없어서 '한 번도 못 붙었나'
        검사에도 안 걸린다 → 리포트에는 "시청자 0명" 만 남는다)
      - OBS 시작 실패(송출이 안 켜진 채로 방송이 돈다)
      - 공지 실패(시청자는 방송 켜진 걸 모른다)
    """
    for kind in ("chat_never_connected", "obs_start_failed", "announce_failed"):
        assert kind in _SERIOUS, kind
        assert kind in _EVENT_LABEL, kind
    out = _trouble_lines([{"kind": "obs_start_failed"},
                          {"kind": "announce_failed"}])
    assert out
    assert "송출" in out[0] and "공지" in out[0]


def test_이벤트_이름과_같은_키를_넘겨도_안_터진다(tmp_path):
    """_event(kind=...) 로 부딪혀 방송이 통째로 죽은 적이 있다."""
    import asyncio

    from aist.config import Config
    from aist.orchestrator import Orchestrator
    from aist.persona import Persona

    cfg = Config()
    cfg.memory.path = str(tmp_path / "mem")
    o = Orchestrator(cfg, Persona())
    o.memory.start_session()
    o._event("announce_failed", kind="start", where="디스코드", t="가짜시각")
    ev = o.memory._cur["events"][-1]
    # 사고 이름과 시각은 호출자 데이터가 덮어쓸 수 없어야 한다
    assert ev["kind"] == "announce_failed"
    assert ev["t"] != "가짜시각"
    assert ev["where"] == "디스코드"


def test_사고_이유가_리포트에_같이_적힌다():
    """이름만 적으면 운영자는 로그 파일을 열어야 원인을 안다 — 안 연다."""
    from aist.report import _event_detail

    d = _event_detail({"kind": "core_error",
                       "message": "Conversation error: [Errno 28] No space left on device"})
    assert "No space left on device" in d
    assert _event_detail({"kind": "tts_silent"}) == ""
    long = _event_detail({"kind": "obs_start_failed", "why": "가" * 500})
    assert len(long) < 200            # 리포트 한 줄이 폭발하지 않게
    assert "`" not in _event_detail({"kind": "banned_word", "word": "a`b",
                                     "text": "x"}).replace("`a'b`", "").replace("`x`", "")
