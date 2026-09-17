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
