"""트랜스크립트/리포트/게임 피드/유튜브 자동발견 테스트."""

import asyncio
import json
from datetime import datetime
from pathlib import Path

from aist.chat.base import ChatMessage
from aist.config import GameConfig, MemoryConfig
from aist.memory import Memory
from aist.report import generate_report
from aist.transcript import Transcript, read_transcript


# ------------------------------ 트랜스크립트 ------------------------------
def test_transcript_records_chat_ai_and_events(tmp_path):
    t = Transcript(str(tmp_path))
    path = t.open_session(datetime(2026, 7, 1, 20, 0))
    t.log_chat(ChatMessage("neo", "안녕", "twitch"))
    # 코어 drain 훅: audio payload 의 display_text 만 AI 발화로 기록
    t.on_core_message({"type": "audio", "display_text": {"text": "어서와~", "name": "별이"}})
    t.on_core_message({"type": "full-text", "text": "Thinking..."})  # 기록 안 함
    t.close()

    records = read_transcript(path)
    whos = [r["who"] for r in records]
    assert whos[0] == "system" and records[0]["event"] == "broadcast_start"
    assert ("viewer", "안녕") in [(r["who"], r.get("text")) for r in records]
    ai = [r for r in records if r["who"] == "ai"]
    assert len(ai) == 1 and ai[0]["text"] == "어서와~"
    assert records[-1]["event"] == "broadcast_end"


def test_transcript_close_without_open_is_noop(tmp_path):
    t = Transcript(str(tmp_path))
    t.log_chat(ChatMessage("a", "b", "twitch"))  # open 전 — 조용히 무시
    t.close()


# ------------------------------ 리포트 ------------------------------
def test_report_from_memory_and_transcript(tmp_path):
    mem = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    mem.start_session()
    mem.note_chat(ChatMessage("neo", "hi", "twitch"))
    mem.note_chat(ChatMessage("trin", "후원!", "chzzk", is_superchat=True, amount="1000"))
    mem.end_session()

    t = Transcript(str(tmp_path / "tr"))
    p = t.open_session(datetime(2026, 7, 1, 20, 0))
    t.log_chat(ChatMessage("neo", "hi", "twitch"))
    t.on_core_message({"type": "audio", "display_text": {"text": "왔구나~"}})
    t.close()

    out = generate_report(mem, str(tmp_path / "reports"),
                          transcript_path=p, next_stream="다음엔 금요일에")
    text = out.read_text(encoding="utf-8")
    assert "시청자(채팅 기준): 2명" in text
    assert "trin" in text and "1000" in text        # 슈퍼챗
    assert "AI 발화 전문" in text and "왔구나~" in text  # 사고발언 점검
    assert "다음엔 금요일에" in text


def test_report_none_when_no_sessions(tmp_path):
    mem = Memory(MemoryConfig(path=str(tmp_path)))
    assert generate_report(mem, str(tmp_path / "r")) is None


# ------------------------------ 게임 피드 ------------------------------
class _Bridge:
    def __init__(self):
        self.said = []

    async def say_to_ai(self, text, source=None, platform=None, **kw):
        self.said.append((text, source, platform))


def test_game_feed_event_and_chat_handling():
    from aist.game.minecraft import MinecraftFeed

    async def run():
        b = _Bridge()
        events = []
        feed = MinecraftFeed(b, GameConfig(enabled=True), on_event=events.append)
        await feed._handle({"event": "death"})
        await feed._handle({"event": "chat", "username": "Steve", "message": "gg"})
        await feed._handle({"event": "spawn"})   # react_events 에 없음 → 무반응
        return b.said, events

    said, events = asyncio.run(run())
    assert any("죽었" in t for (t, s, p) in said)                 # death 큐
    assert ("gg", "Steve", "minecraft") in said                   # 게임 채팅 전달
    assert len([s for s in said]) == 2                            # spawn 은 반응 안 함
    assert len(events) == 3                                       # 기록은 전부


def test_game_feed_chat_forward_can_be_disabled():
    from aist.game.minecraft import MinecraftFeed

    async def run():
        b = _Bridge()
        feed = MinecraftFeed(b, GameConfig(enabled=True, forward_game_chat=False))
        await feed._handle({"event": "chat", "username": "Steve", "message": "gg"})
        return b.said

    assert asyncio.run(run()) == []


# ------------------------------ 유튜브 자동발견 ------------------------------
def test_youtube_video_id_regex():
    from aist.chat.youtube import _VIDEO_ID_RE
    html = 'foo "videoId":"dQw4w9WgXcQ" bar'
    assert _VIDEO_ID_RE.search(html).group(1) == "dQw4w9WgXcQ"


def test_youtube_requires_id_or_channel():
    from aist.chat.youtube import YouTubeChat
    import pytest
    with pytest.raises(ValueError):
        YouTubeChat()
    YouTubeChat(channel="@somebody")   # channel 만으로 생성 가능


# ---- 진짜 방송 분량에서 리포트가 읽을 수 있는 물건인지 ----
def test_report_stays_readable_with_real_volume(tmp_path):
    """10분 방송 기록으로 만든 리포트가 193줄이었다. 3시간이면 수천 줄이다.

    운영자가 사고 발언을 찾으려고 읽는 문서인데, 같은 줄 수천 개를 그대로
    쏟으면 정작 이상한 발언이 묻힌다.
    """
    import json

    from aist.config import MemoryConfig
    from aist.memory import Memory
    from aist.report import generate_report

    mem = Memory(MemoryConfig(path=str(tmp_path / "mem"), backend="json"))
    mem.start_session()
    for i in range(35):
        mem._cur["superchats"].append(
            {"author": f"시청자{i}", "amount": "5,000원", "text": "감사합니다"})
    mem.end_session(summary="테스트")

    tr = tmp_path / "t.jsonl"
    with tr.open("w", encoding="utf-8") as fh:
        for _ in range(500):
            fh.write(json.dumps({"who": "ai", "text": "네 알겠어요."},
                                ensure_ascii=False) + "\n")
        fh.write(json.dumps({"who": "ai", "text": "이건 다른 말"},
                            ensure_ascii=False) + "\n")

    path = generate_report(mem, str(tmp_path / "out"), transcript_path=tr)
    text = path.read_text(encoding="utf-8")

    assert "합계 약 175,000원" in text, "후원 합계를 알려줘야 한다"
    assert "그 외 15건" in text, "수십 건을 전부 나열하면 못 읽는다"
    assert "(×500)" in text, "같은 말이 이어지면 묶어야 한다"
    assert "이건 다른 말" in text, "다른 발언은 그대로 남아야 한다"
    assert len(text.splitlines()) < 80, f"리포트가 너무 깁니다: {len(text.splitlines())}줄"


def test_same_phrase_far_apart_is_not_hidden(tmp_path):
    """떨어져서 반복된 말은 묶지 않는다 — 사고 발언은 시점이 중요하다."""
    import json

    from aist.config import MemoryConfig
    from aist.memory import Memory
    from aist.report import generate_report

    mem = Memory(MemoryConfig(path=str(tmp_path / "mem"), backend="json"))
    mem.start_session()
    mem.end_session()
    tr = tmp_path / "t.jsonl"
    with tr.open("w", encoding="utf-8") as fh:
        for text in ("문제 발언", "보통 말", "문제 발언"):
            fh.write(json.dumps({"who": "ai", "text": text}, ensure_ascii=False) + "\n")

    text = generate_report(mem, str(tmp_path / "out"),
                           transcript_path=tr).read_text(encoding="utf-8")
    assert text.count("- 문제 발언") == 2


def test_bits_amounts_do_not_break_the_total(tmp_path):
    """트위치 치어는 '100 bits' 라서 원 단위가 아니다 — 합계에 섞이면 안 된다."""
    from aist.report import _won_total

    assert _won_total([{"amount": "5,000원"}, {"amount": "100 bits"},
                       {"amount": ""}]) == 5000


def test_report_flags_silent_broadcast(tmp_path):
    """목소리가 안 나간 방송은 리포트 맨 위에 경고로 보여야 한다.

    이벤트 목록 속에 묻히면 운영자가 못 본다 — 방송 하나를 통째로
    자막만 내보낸 사고다.
    """
    from aist.config import MemoryConfig
    from aist.memory import Memory
    from aist.report import generate_report

    m = Memory(MemoryConfig(path=str(tmp_path / "mem")))
    m.start_session()
    m.record_event("tts_silent")
    m.end_session()
    path = generate_report(m, str(tmp_path / "reports"))
    body = path.read_text(encoding="utf-8")
    assert "목소리가 나가지 않았습니다" in body
    # 통계 앞(머리말)에 있어야 한다
    assert body.index("목소리가 나가지 않았습니다") < body.index("## 점검 메모")


# --------- 기록이 중간에 끊겼는데 리포트는 그 파일로 만들어진다 ---------
def test_기록이_끊기면_리포트가_그걸_알린다():
    """디스크가 차면 트랜스크립트 쓰기가 죽는다(24시간 운영에서 실제로 난다).

    리포트의 "AI 발화 수"와 "발화 전문" 은 그 파일로 만들어지므로,
    끊긴 걸 안 알리면 5%만 담긴 기록이 방송 전체인 것처럼 보인다.
    '사고 발언 점검' 이라는 그 칸의 존재 이유가 통째로 무너진다.
    """
    from aist.report import _EVENT_LABEL, _SERIOUS, _trouble_lines
    assert "transcript_lost" in _SERIOUS
    out = _trouble_lines([{"kind": "transcript_lost"}])
    assert out and "방송 전체가 아님" in out[0]
    assert "transcript_lost" in _EVENT_LABEL


def test_쓰기가_죽으면_표시가_남는다(tmp_path):
    from datetime import datetime
    from aist.transcript import Transcript

    t = Transcript(str(tmp_path / "tr"))
    t.open_session(datetime.now())
    t.log_ai("정상 발화")
    assert t.write_failed is False

    class _Full:
        def write(self, *a):
            raise OSError(28, "No space left on device")

        def flush(self):
            pass

        def close(self):
            pass

    t._fh = _Full()
    t.log_ai("이건 못 쓴다")
    assert t.write_failed is True
    # 방송은 계속 돌아야 한다 — 예외가 밖으로 나가면 안 된다
    t.log_ai("그 뒤에도 안 터진다")
