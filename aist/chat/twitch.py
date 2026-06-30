"""트위치 채팅 리더 — IRC over WebSocket.

엔드포인트: wss://irc-ws.chat.twitch.tv:443
- 토큰이 있으면 그 계정으로, 없으면 익명(justinfan)으로 읽기 연결.
- 들어오는 PRIVMSG 를 ChatMessage 로 변환해 빠짐없이 yield 한다.
- bits(치어)는 IRCv3 tags 의 bits 값으로 감지(슈퍼챗 유사).

websockets 지연 import.
"""

import asyncio
import logging
import random
from typing import AsyncIterator, Dict, Optional

from .base import ChatMessage, ChatSource

log = logging.getLogger("aist.chat.twitch")

_IRC_WS_URL = "wss://irc-ws.chat.twitch.tv:443"


def _parse_tags(tag_str: str) -> Dict[str, str]:
    tags: Dict[str, str] = {}
    for part in tag_str.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k] = v
    return tags


def _parse_line(line: str):
    """IRC 한 줄 파싱 → (tags, prefix, command, params, trailing)."""
    tags: Dict[str, str] = {}
    if line.startswith("@"):
        tag_str, _, line = line.partition(" ")
        tags = _parse_tags(tag_str[1:])
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line.partition(" ")
        prefix = prefix[1:]
    command, _, rest = line.partition(" ")
    trailing = ""
    if " :" in rest:
        params_part, _, trailing = rest.partition(" :")
    elif rest.startswith(":"):
        trailing = rest[1:]
        params_part = ""
    else:
        params_part = rest
    return tags, prefix, command.strip(), params_part.strip(), trailing


class TwitchChat(ChatSource):
    platform = "twitch"

    def __init__(self, channel: str, oauth_token: str = "", nick: str = ""):
        if not channel:
            raise ValueError("트위치 channel 이 필요합니다 (.env TWITCH_CHANNEL).")
        self.channel = channel.lower().lstrip("#")
        self.oauth_token = oauth_token
        self.nick = (nick or "").lower()
        self._ws = None

    async def _connect(self):
        import websockets  # 지연 import
        self._ws = await websockets.connect(_IRC_WS_URL, max_size=None)
        # 능력 요청: tags(닉네임/bits) + membership
        await self._ws.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
        if self.oauth_token:
            token = self.oauth_token
            if not token.startswith("oauth:"):
                token = "oauth:" + token
            await self._ws.send(f"PASS {token}")
            await self._ws.send(f"NICK {self.nick or 'aist_bot'}")
        else:
            # 익명 읽기 연결
            await self._ws.send(f"NICK justinfan{random.randint(10000, 99999)}")
        await self._ws.send(f"JOIN #{self.channel}")
        log.info("트위치 채팅 연결됨 (#%s, %s)", self.channel,
                 "인증" if self.oauth_token else "익명")

    async def messages(self) -> AsyncIterator[ChatMessage]:
        await self._connect()
        assert self._ws is not None
        async for raw in self._ws:
            # 한 프레임에 여러 줄이 올 수 있음
            for line in raw.split("\r\n"):
                line = line.strip()
                if not line:
                    continue
                tags, prefix, command, params, trailing = _parse_line(line)
                if command == "PING":
                    await self._ws.send(f"PONG :{trailing or 'tmi.twitch.tv'}")
                    continue
                if command != "PRIVMSG":
                    continue
                author = tags.get("display-name") or prefix.split("!", 1)[0]
                bits = tags.get("bits", "")
                yield ChatMessage(
                    author=author,
                    text=trailing,
                    platform=self.platform,
                    is_superchat=bool(bits),
                    amount=(f"{bits} bits" if bits else ""),
                    raw=line,
                )

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            finally:
                self._ws = None
