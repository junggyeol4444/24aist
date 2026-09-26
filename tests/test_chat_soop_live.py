"""SOOP 채팅 리더를 실제 접속 흐름으로 돌려본다.

주의: 이 테스트가 증명하는 것은 "우리가 만드는 패킷과 파싱이 우리가 가정한
형식과 맞는다" 까지다. 실제 SOOP 서버가 같은 필드 순서를 쓰는지는 실제
방송으로 한 번 확인해야 한다(soop.py 머리말 참고).
그래도 접속 순서(로그인 → 입장), 한 프레임에 여러 패킷, 이상한 패킷에
안 죽는지, 끊겼을 때 다시 붙는지는 여기서 잡을 수 있다.
"""

import asyncio
import socket

import pytest

pytest.importorskip("websockets")

import aist.chat.soop as sp  # noqa: E402
from aist.chat.soop import ESC, F, SoopChat, _packet  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    def __init__(self, drop_first: bool = False):
        self.svcs = []
        self.sessions = 0
        self.drop_first = drop_first

    async def handle(self, ws):
        self.sessions += 1
        mine = self.sessions
        async for raw in ws:
            text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
            for frame in text.split(ESC):
                if frame:
                    self.svcs.append(frame[:4])
            if len([s for s in self.svcs if s == "0002"]) < mine:
                continue
            if self.drop_first and mine == 1:
                await ws.close()
                return
            # 한 프레임에 두 패킷이 붙어 오는 경우
            await ws.send(_packet(5, f"{F}안녕하세요{F}0{F}시청자A{F}")
                          + _packet(5, f"{F}ㅋㅋㅋㅋ{F}0{F}시청자B{F}"))
            await ws.send(_packet(1, f"{F}{F}"))       # 채팅이 아닌 패킷
            await ws.send(ESC + "깨진패킷")              # 이상한 패킷
            await ws.send(_packet(5, f"{F}마지막{F}0{F}시청자C{F}"))


def _run(server, want, timeout=15):
    import websockets

    async def main():
        port = _free_port()
        old = sp._WS_SCHEME
        sp._WS_SCHEME = "ws"
        try:
            async with websockets.serve(server.handle, "127.0.0.1", port,
                                        subprotocols=["chat"]):
                chat = SoopChat("테스트BJ")
                chat._fetch_live_info = lambda: {
                    "CHDOMAIN": "127.0.0.1", "CHPT": str(port - 1), "CHATNO": "12345"}
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
            sp._WS_SCHEME = old

    return asyncio.run(main())


def test_login_then_join_then_chat():
    server = _Server()
    msgs = _run(server, want=3)
    assert [m.author for m in msgs] == ["시청자A", "시청자B", "시청자C"]
    assert msgs[0].text == "안녕하세요"
    # 로그인(svc 1) 다음에 입장(svc 2) — 순서가 바뀌면 실제 서버가 끊는다
    assert server.svcs[:2] == ["0001", "0002"]


def test_survives_non_chat_and_broken_packets():
    """이상한 패킷 하나에 채팅 수신이 멈추면 방송 내내 채팅이 없다."""
    server = _Server()
    msgs = _run(server, want=3)
    assert len(msgs) == 3


def test_reconnects_after_drop():
    server = _Server(drop_first=True)
    msgs = _run(server, want=1)
    assert msgs, "끊긴 뒤 다시 붙지 못했습니다"
    assert server.sessions >= 2
