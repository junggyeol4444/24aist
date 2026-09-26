"""소독하고 나니 내용이 안 남은 채팅.

시청자가 공백만 치거나, 플랫폼이 스티커·이모지 ID 만 보내거나, 제어문자만
들어오면 소독 뒤에 빈 문자열이 된다. 그대로 코어에 넘기면 이런 줄이 간다:

    별하나 (치지직)

방송인은 아무 말도 없는 것에 대답하느라 엉뚱한 소리를 한다.
"""

import asyncio

from aist.chat.base import ChatMessage
from aist.chat_pipeline import ChatPipeline
from aist.config import BroadcastConfig, SafetyConfig


class _Bridge:
    def __init__(self):
        self.sent = []

    async def say_to_ai(self, text, source=None, platform=None, donation=None):
        self.sent.append((source, text))


def _run(msg):
    b = _Bridge()
    seen = []
    p = ChatPipeline(b, BroadcastConfig(), safety=SafetyConfig(),
                     on_message=seen.append)
    asyncio.run(p.submit(msg))
    return b.sent, seen


def test_공백만_친_채팅은_안_넘긴다():
    sent, seen = _run(ChatMessage(author="별하나", text="   ", platform="chzzk"))
    assert sent == []
    # 그래도 '왔다'는 기록은 남는다 — 시청자 수에는 들어가야 한다
    assert len(seen) == 1


def test_제어문자만_있는_채팅도_안_넘긴다():
    sent, _ = _run(ChatMessage(author="별하나", text="\x00\x07\x1b",
                               platform="chzzk"))
    assert sent == []


def test_글_없는_후원은_반드시_넘긴다():
    """돈은 들어왔다. 방송인이 모르고 지나가면 안 된다."""
    sent, _ = _run(ChatMessage(author="큰손", text="", platform="chzzk",
                               is_superchat=True, amount="10,000원"))
    assert len(sent) == 1


def test_평범한_채팅은_그대로():
    sent, _ = _run(ChatMessage(author="별하나", text="안녕", platform="chzzk"))
    assert sent == [("별하나", "안녕")]


def test_소독을_끄면_공백도_그대로_간다():
    """sanitize_chat=false 는 운영자가 일부러 끈 것이다."""
    b = _Bridge()
    p = ChatPipeline(b, BroadcastConfig(), safety=SafetyConfig(sanitize_chat=False))
    asyncio.run(p.submit(ChatMessage(author="별하나", text="안녕", platform="chzzk")))
    assert len(b.sent) == 1
