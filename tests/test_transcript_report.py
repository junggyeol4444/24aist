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

    async def say_to_ai(self, text, source=None, platform=None):
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
