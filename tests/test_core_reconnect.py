"""코어가 죽었다 살아난 뒤 채팅이 다시 흘러야 한다.

끊기기 직전에 보낸 발화의 '말 끝' 신호(conversation-chain-end)는 옛 연결과
함께 사라진다. 그 상태를 안 풀어주면 파이프라인이 계속 '말하는 중'으로 알고
채팅을 쌓아두기만 한다. 실제로 코어를 죽였다 살려보니 재연결 뒤 약 3분 동안
채팅이 한 건도 안 나갔다(폴백 타이머가 돌 때까지).
"""

import asyncio

import pytest

from aist.chat_pipeline import ChatPipeline
from aist.config import BroadcastConfig


class _Bridge:
    def __init__(self):
        self.sent = []

    async def say_to_ai(self, text, source=None, platform=None, donation=None):
        self.sent.append((source, text))

    async def proactive_speak(self):
        pass


def _pipeline():
    return ChatPipeline(_Bridge(), BroadcastConfig(core_busy_timeout_sec=90))


def test_reconnect_clears_speaking_state():
    p = _pipeline()
    p.on_core_message({"type": "control", "text": "conversation-chain-start"})
    assert p.is_speaking() is True
    p.core_reconnected()
    assert p.is_speaking() is False


def test_pending_chat_flows_again_after_reconnect():
    from aist.chat.base import ChatMessage

    p = _pipeline()
    p.on_core_message({"type": "control", "text": "conversation-chain-start"})
    # 말하는 중 → 채팅은 쌓인다
    asyncio.run(_feed(p, ChatMessage("별하나", "안녕", "rehearsal")))
    assert p.has_pending() is True
    assert p.bridge.sent == []

    p.core_reconnected()
    asyncio.run(_flush(p))
    assert p.bridge.sent, "재연결 뒤에도 채팅이 안 나갔습니다"


async def _feed(p, msg):
    if p._busy_now():
        p._pending.append(msg)
    else:
        await p._send_single(msg)


async def _flush(p):
    if not p._busy_now() and p._pending:
        batch, p._pending = p._pending, []
        await p._send_batch(batch)


def test_reconnect_is_safe_when_not_speaking():
    p = _pipeline()
    p.core_reconnected()
    assert p.is_speaking() is False
