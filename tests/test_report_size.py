"""3시간 방송 리포트가 읽을 수 있는 크기인지.

기획 2-2 의 목표는 "하루 5~10분 점검" 이다. 그런데 3시간 방송분을
만들어 재보니 리포트가 1367줄이었고, 그중 1352줄(99%)이 'AI 발화 전문'
한 칸이었다. 1350줄을 읽어서 이상한 발언을 찾으라는 건 그 칸의 목적과
반대로 간다.
"""

import json
from datetime import datetime, timedelta, timezone

from aist.chat.base import ChatMessage
from aist.config import MemoryConfig
from aist.memory import Memory
from aist.report import _SPEECH_INLINE_MAX, generate_report


def _transcript(tmp_path, n_ai: int):
    tr = tmp_path / "t.jsonl"
    t0 = datetime(2026, 9, 22, 20, 0, tzinfo=timezone.utc)
    with tr.open("w", encoding="utf-8") as f:
        for i in range(n_ai):
            ts = (t0 + timedelta(seconds=i * 8)).isoformat()
            f.write(json.dumps({"t": ts, "who": "viewer", "author": f"시청자{i}",
                                "text": "안녕", "platform": "chzzk"},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps({"t": ts, "who": "ai",
                                "text": f"{i}번째로 한 말이고 매번 다릅니다"},
                               ensure_ascii=False) + "\n")
    return tr


def _report(tmp_path, n_ai):
    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()
    m.note_chat(ChatMessage(author="시청자", text="안녕", platform="chzzk"))
    m.end_session()
    p = generate_report(m, str(tmp_path / "rep"),
                        transcript_path=_transcript(tmp_path, n_ai),
                        tz_name="Asia/Seoul")
    return p, p.read_text(encoding="utf-8")


def test_짧은_방송은_예전처럼_전부_리포트_안에(tmp_path):
    n = _SPEECH_INLINE_MAX - 5
    p, txt = _report(tmp_path, n)
    assert "0번째로 한 말" in txt and f"{n-1}번째로 한 말" in txt
    assert "줄임" not in txt
    assert not list(p.parent.glob("*발화전문*"))


def test_긴_방송은_따로_빼고_리포트는_짧게(tmp_path):
    p, txt = _report(tmp_path, 1350)
    assert len(txt.splitlines()) < 80, "리포트가 아직도 길다"
    # 앞뒤는 리포트에 남아 한눈에 보인다
    assert "0번째로 한 말" in txt and "1349번째로 한 말" in txt
    assert "줄임" in txt
    # 전문은 옆에 파일로
    side = list(p.parent.glob("*발화전문*.txt"))
    assert len(side) == 1
    body = side[0].read_text(encoding="utf-8")
    assert "700번째로 한 말" in body, "가운데가 통째로 사라지면 안 된다"
    assert len(body.splitlines()) >= 1350
    # 어디를 열면 되는지 리포트가 알려준다
    assert side[0].name in txt


def test_전문_파일을_못_써도_리포트는_나온다(tmp_path, monkeypatch):
    import aist.report as R
    monkeypatch.setattr(R, "_write_speech_file", lambda *a, **k: None)
    p, txt = _report(tmp_path, 1350)
    assert "트랜스크립트에 그대로 있습니다" in txt
