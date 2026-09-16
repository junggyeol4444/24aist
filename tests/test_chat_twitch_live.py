"""진짜 IRC 흐름으로 트위치 채팅 리더를 돌려본다.

파서 단위 테스트만으로는 "서버와 실제로 주고받는 순서"가 맞는지 모른다.
특히 PING 에 PONG 을 안 보내면 트위치가 몇 분 만에 연결을 끊는다 —
재연결 루프에 가려서 증상은 "가끔 채팅이 비는 것" 으로만 보인다.
(websockets 가 없는 환경에서는 건너뛴다)
"""

import asyncio
import socket

import pytest

pytest.importorskip("websockets")

import aist.chat.twitch as tw  # noqa: E402
from aist.chat.twitch import TwitchChat  # noqa: E402


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Server:
    """트위치 IRC-over-WebSocket 흉내."""

    def __init__(self, drop_after_join: int = 0):
        self.received = []
        self.joins = 0
        self.drop_after_join = drop_after_join

    async def handle(self, ws):
        async for raw in ws:
            for line in raw.split("\r\n"):
                if not line.strip():
                    continue
                self.received.append(line)
                if not line.startswith("JOIN"):
                    continue
                self.joins += 1
                if self.drop_after_join and self.joins <= self.drop_after_join:
                    await ws.close()          # 연결을 끊어 재연결을 유도
                    return
                await ws.send("PING :tmi.twitch.tv\r\n")
                await ws.send("@display-name=별하나;bits= "
                              ":byeol!byeol@byeol.tmi.twitch.tv "
                              "PRIVMSG #test :안녕하세요~\r\n")
                await ws.send("@display-name=라면조아;bits=100 "
                              ":ramen!ramen@ramen.tmi.twitch.tv "
                              "PRIVMSG #test :치어 드림\r\n")
                # 한 프레임에 두 줄이 붙어 오는 경우
                await ws.send("@display-name=A :a!a@a.tmi.twitch.tv PRIVMSG #test :첫줄\r\n"
                              "@display-name=B :b!b@b.tmi.twitch.tv PRIVMSG #test :둘째줄\r\n")


async def _collect(chat, want, timeout=15):
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


def _run(server: _Server, chat_factory, want: int):
    import websockets

    async def main():
        port = _free_port()
        old = tw._IRC_WS_URL
        tw._IRC_WS_URL = f"ws://127.0.0.1:{port}"
        try:
            async with websockets.serve(server.handle, "127.0.0.1", port):
                return await _collect(chat_factory(), want)
        finally:
            tw._IRC_WS_URL = old

    return asyncio.run(main())


def test_reads_chat_and_cheers():
    server = _Server()
    msgs = _run(server, lambda: TwitchChat("Test"), want=4)
    assert [m.author for m in msgs] == ["별하나", "라면조아", "A", "B"]
    assert msgs[0].text == "안녕하세요~"
    assert msgs[1].is_superchat is True and msgs[1].amount == "100 bits"
    # 채널명은 소문자로(트위치 규칙), 익명 접속은 justinfan
    assert any(line == "JOIN #test" for line in server.received)
    assert any(line.startswith("NICK justinfan") for line in server.received)


def test_answers_ping_with_pong():
    """PONG 을 안 보내면 트위치가 연결을 끊는다 — 방송 중 채팅이 비게 된다."""
    server = _Server()
    _run(server, lambda: TwitchChat("test"), want=4)
    assert any(line.startswith("PONG") for line in server.received), server.received


def test_reconnects_after_server_drops():
    """장시간 방송에서 연결은 끊긴다. 끊기면 다시 붙어야 한다."""
    server = _Server(drop_after_join=1)
    msgs = _run(server, lambda: TwitchChat("test"), want=1)
    assert msgs, "끊긴 뒤 다시 붙지 못했습니다"
    assert server.joins >= 2


def test_token_login_sends_pass_and_nick():
    server = _Server()
    _run(server, lambda: TwitchChat("test", oauth_token="abc123", nick="별이봇"), want=1)
    assert "PASS oauth:abc123" in server.received
    assert "NICK 별이봇" in server.received
