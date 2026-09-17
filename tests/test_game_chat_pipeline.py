"""게임 안 채팅이 시청자 채팅을 밀어내지 않는지.

게임 연동을 켜고 진짜로 3분 방송을 돌려봤다(2초에 한 줄 오는 한산한
마인크래프트 서버 흉내). 코어가 받은 134줄 중 80줄이 게임 채팅이었고,
게임 채팅은 채팅 파이프라인을 통째로 비켜가 코어로 직행하고 있었다:
  - '입 하나' 모델을 안 거쳐서 한 줄마다 대화를 새로 열었다
  - 폭주 처리(flood_handling)도 안 걸렸다
  - 리포트에는 한 줄도 안 잡혀서, 운영자는 방송인이 게임 채팅만
    상대하고 있었다는 걸 알 수 없었다
기획 1-2 "시청자 채팅 다 읽고 다 반응" 이 통째로 뒤집히는 상태였다.
"""

import asyncio
import time

import pytest

from aist.chat.base import ChatMessage
from aist.chat_pipeline import ChatPipeline
from aist.config import BroadcastConfig, GameConfig, SafetyConfig
from aist.game import MinecraftFeed


class _Bridge:
    def __init__(self):
        self.sent = []

    async def say_to_ai(self, text, source=None, platform=None, donation=None):
        self.sent.append((source, text))


def _pipe(bridge=None, seen=None):
    return ChatPipeline(bridge or _Bridge(), BroadcastConfig(),
                        safety=SafetyConfig(),
                        on_message=(seen.append if seen is not None else None))


def _game(text="게임채팅", who="Steve"):
    return ChatMessage(author=who, text=text, platform="minecraft",
                       from_game=True)


def test_말하는_중이면_게임_채팅도_기다린다():
    b = _Bridge()
    p = _pipe(b)
    p._core_busy = True
    p._busy_since = time.monotonic()
    asyncio.run(p.submit(_game()))
    assert b.sent == []               # 말 끊고 끼어들지 않는다
    assert len(p._pending) == 1       # 말 끝나면 같이 나간다


def test_게임_채팅은_시청자가_조용한지_판단을_흐리지_않는다():
    """종료 판단(채팅 저조)은 시청자를 본다.

    게임 서버 사람들이 떠든다고 시계가 되돌아가면, 시청자가 아무도 없는
    방송이 계속 켜져 있게 된다.
    """
    p = _pipe()
    before = p.last_chat_time
    asyncio.run(p.submit(_game()))
    assert p.last_chat_time == before
    asyncio.run(p.submit(ChatMessage(author="시청자", text="안녕",
                                     platform="twitch")))
    assert p.last_chat_time != before


def test_게임_채팅도_기록에는_남는다():
    seen = []
    p = _pipe(seen=seen)
    asyncio.run(p.submit(_game()))
    assert len(seen) == 1 and seen[0].from_game is True


def test_사이드카_채팅은_파이프라인으로_간다():
    got = []

    async def on_chat(msg):
        got.append(msg)

    feed = MinecraftFeed(_Bridge(), GameConfig(), on_chat=on_chat)
    asyncio.run(feed._handle({"event": "chat", "username": "Alex",
                              "message": "여기 와봐요"}))
    assert len(got) == 1
    assert got[0].from_game is True
    assert got[0].platform == "minecraft"
    assert got[0].author == "Alex"


def test_파이프라인이_없으면_예전처럼_코어로_보낸다():
    b = _Bridge()
    feed = MinecraftFeed(b, GameConfig())
    asyncio.run(feed._handle({"event": "chat", "username": "Alex",
                              "message": "안녕"}))
    assert b.sent == [("Alex", "안녕")]


def test_묶음이_넘칠_때_시청자_채팅부터_담는다():
    """붐비는 게임 서버는 방송인이 한 번 말하는 동안 수십 줄을 만든다.

    그냥 최근 순으로 자르면, 먼저 올라온 시청자 질문이 게임 채팅에
    밀려 통째로 잘린다(실측: 상한 5줄일 때 시청자 2줄이 전부 사라짐).
    """
    cfg = BroadcastConfig()
    cfg.max_batch_lines = 5
    b = _Bridge()
    p = ChatPipeline(b, cfg, safety=SafetyConfig())

    batch = [ChatMessage(author="시청자A", text="질문이요", platform="twitch"),
             ChatMessage(author="시청자B", text="저도요", platform="twitch")]
    batch += [_game(f"게임말{i}", f"게임{i}") for i in range(8)]

    asyncio.run(p._send_batch(batch))
    out = b.sent[0][1]
    assert "시청자A" in out and "시청자B" in out
    # 시간 순서는 그대로여야 자연스럽게 읽힌다
    assert out.index("시청자A") < out.index("게임")
    # 못 넣은 건수는 그대로 알려준다
    assert "그 외 5건" in out


def test_게임이_없으면_예전처럼_최근_것을_남긴다():
    cfg = BroadcastConfig()
    cfg.max_batch_lines = 3
    b = _Bridge()
    p = ChatPipeline(b, cfg, safety=SafetyConfig())
    batch = [ChatMessage(author=f"시청자{i}", text=f"말{i}", platform="twitch")
             for i in range(6)]
    asyncio.run(p._send_batch(batch))
    out = b.sent[0][1]
    assert "시청자5" in out and "시청자0" not in out
