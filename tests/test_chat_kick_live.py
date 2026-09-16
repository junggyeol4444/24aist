"""Kick(Pusher) 채팅 리더를 실제 흐름으로 돌려본다.

Pusher 는 연결되면 먼저 pusher:connection_established 를 보낸다. 그 전에
구독을 보내면 서버가 무시할 수 있고, 그러면 연결은 멀쩡한데 채팅이 한 건도
안 들어온다 — 로그만 보면 "연결됨" 이라 문제를 알아채기 어렵다.
"""

import asyncio
import json
import socket

import pytest

pytest.importorskip("websockets")

import aist.chat.kick as kk  # noqa: E402
from aist.chat.kick import KickChat  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Pusher:
    """구독을 '인사 뒤에 온 것' 만 받아주는 엄격한 서버."""

    def __init__(self, strict: bool = True, drop_first: bool = False):
        self.strict = strict
        self.drop_first = drop_first
        self.sessions = 0
        self.subscribed = []
        self.pongs = 0
        self.greeted = False
        self.ignored_early = []

    async def handle(self, ws):
        self.sessions += 1
        mine = self.sessions
        # 진짜 Pusher 처럼 인사가 조금 늦게 간다. 인사 전에 온 구독은 버린다.
        self.greeted = False

        async def greet():
            await asyncio.sleep(0.4)
            await ws.send(json.dumps({
                "event": "pusher:connection_established",
                "data": json.dumps({"socket_id": "1.1", "activity_timeout": 120})}))
            self.greeted = True

        asyncio.create_task(greet())
        if self.drop_first and mine == 1:
            await asyncio.sleep(0.6)
            await ws.close()
            return
        async for raw in ws:
            evt = json.loads(raw)
            if self.strict and not self.greeted:
                self.ignored_early.append(evt.get("event"))
                continue
            if evt.get("event") == "pusher:pong":
                self.pongs += 1
                continue
            if evt.get("event") != "pusher:subscribe":
                continue
            channel = (evt.get("data") or {}).get("channel")
            self.subscribed.append(channel)
            await ws.send(json.dumps({"event": "pusher:ping", "data": {}}))
            await ws.send(json.dumps({
                "event": "App\\\\Events\\\\ChatMessageEvent",
                "channel": channel,
                "data": json.dumps({"content": "안녕 킥!",
                                    "sender": {"username": "킥시청자"}},
                                   ensure_ascii=False)}))


def _run(server, want, timeout=15):
    import websockets

    async def main():
        port = _free_port()
        old = kk._WS_URL
        kk._WS_URL = f"ws://127.0.0.1:{port}"
        try:
            async with websockets.serve(server.handle, "127.0.0.1", port):
                chat = KickChat(chatroom_id=98765)
                msgs = []

                async def read():
                    async for m in chat.messages():
                        msgs.append(m)
                        if len(msgs) >= want:
                            return

                try:
                    await asyncio.wait_for(read(), timeout=timeout)
                finally:
                    await chat.close()
                return msgs
        finally:
            kk._WS_URL = old

    return asyncio.run(main())


def test_subscribes_after_the_handshake_and_reads_chat():
    """인사(pusher:connection_established) 전에 구독을 보내면 버려진다.

    그러면 연결은 '됨' 인데 채팅이 한 건도 안 들어온다 — 로그만 보면
    정상이라 알아채기 가장 어려운 고장이다.
    """
    server = _Pusher()
    msgs = _run(server, want=1)
    assert [(m.author, m.text) for m in msgs] == [("킥시청자", "안녕 킥!")]
    assert server.subscribed == ["chatrooms.98765.v2"]
    assert server.ignored_early == [], f"인사 전에 보낸 게 있습니다: {server.ignored_early}"


def test_answers_pusher_ping():
    server = _Pusher()
    _run(server, want=1)
    assert server.pongs >= 1, "pusher:ping 에 응답하지 않으면 서버가 끊는다"


def test_reconnects_after_drop():
    server = _Pusher(drop_first=True)
    msgs = _run(server, want=1)
    assert msgs and server.sessions >= 2
