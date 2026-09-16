"""치지직 채팅 리더를 실제 프로토콜 흐름으로 돌려본다.

이 플랫폼은 비공식 프로토콜이라 "코드가 도는 것" 과 "실제로 붙는 것" 의
간격이 크다. 최소한 우리가 보내는 접속 패킷 모양, ping→pong, 채팅/후원
파싱, 끊겼을 때 토큰을 다시 받아 재연결하는지는 확인할 수 있다.
"""

import asyncio
import json
import socket

import pytest

pytest.importorskip("websockets")

import aist.chat.chzzk as cz  # noqa: E402
from aist.chat.chzzk import ChzzkChat  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    def __init__(self, drop_first: bool = False):
        self.received = []
        self.connects = 0
        self.drop_first = drop_first

    async def handle(self, ws):
        async for raw in ws:
            msg = json.loads(raw)
            self.received.append(msg)
            if msg.get("cmd") != cz._CMD["connect"]:
                continue
            self.connects += 1
            if self.drop_first and self.connects == 1:
                await ws.close()
                return
            await ws.send(json.dumps({"ver": "2", "cmd": cz._CMD["ping"]}))
            await ws.send(json.dumps({
                "cmd": cz._CMD["chat"],
                "bdy": [{"profile": json.dumps({"nickname": "별하나"}),
                         "msg": "안녕하세요~"}]}, ensure_ascii=False))
            # 메시지 없는 후원(치즈) — 버리면 안 된다
            await ws.send(json.dumps({
                "cmd": cz._CMD["donation"],
                "bdy": [{"profile": json.dumps({"nickname": "후원자"}),
                         "msg": "",
                         "extras": json.dumps({"payAmount": 10000})}]}, ensure_ascii=False))


def _run(server, want, drop_first=False, timeout=15):
    import websockets

    async def main():
        port = _free_port()
        old = cz._WS_URL
        cz._WS_URL = f"ws://127.0.0.1:{port}"
        calls = {"tokens": 0}
        try:
            async with websockets.serve(server.handle, "127.0.0.1", port):
                chat = ChzzkChat("채널ID")

                def fake_tokens():
                    calls["tokens"] += 1
                    return ("chat-channel-id", f"token{calls['tokens']}")

                chat._fetch_tokens = fake_tokens
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
                return msgs, calls
        finally:
            cz._WS_URL = old

    return asyncio.run(main())


def test_connect_packet_and_chat_and_donation():
    server = _Server()
    msgs, _ = _run(server, want=2)
    assert [m.author for m in msgs] == ["별하나", "후원자"]
    assert msgs[0].text == "안녕하세요~"
    # 메시지 없는 후원도 그대로 흘러야 한다(금액은 사람이 읽는 표기로)
    assert msgs[1].is_superchat is True
    assert msgs[1].amount == "10,000원"
    assert msgs[1].text == ""

    connect = server.received[0]
    assert connect["cmd"] == cz._CMD["connect"]
    assert connect["bdy"]["accTkn"] == "token1"
    assert connect["bdy"]["auth"] == "READ"
    assert connect["cid"] == "chat-channel-id"


def test_answers_ping_with_pong():
    server = _Server()
    _run(server, want=2)
    assert any(m.get("cmd") == cz._CMD["pong"] for m in server.received), server.received


def test_reconnect_gets_a_fresh_token():
    """토큰은 만료된다 — 다시 붙을 때 새로 받아야 한다."""
    server = _Server(drop_first=True)
    msgs, calls = _run(server, want=1, drop_first=True)
    assert msgs, "끊긴 뒤 다시 붙지 못했습니다"
    assert calls["tokens"] >= 2, "재연결하면서 토큰을 다시 받지 않았습니다"
    connects = [m for m in server.received if m.get("cmd") == cz._CMD["connect"]]
    assert len(connects) >= 2, "재접속 패킷이 없습니다"
    assert connects[-1]["bdy"]["accTkn"] != connects[0]["bdy"]["accTkn"]
