"""치지직(chzzk) 채팅 리더 — 비공식 채팅 WebSocket.

흐름(레퍼런스: kimcore/chzzk, Buddha7771/ChzzkChat):
  1) live-status 로 chatChannelId 획득
  2) access-token 발급
  3) wss://kr-ss1.chat.naver.com/chat 연결 → connect(cmd 100)
  4) 수신: ping(0)→pong(10000), chat(93101)/donation(93102) 파싱

공개 방송은 토큰 없이 읽힌다(성인/제한 방송은 NID 쿠키 필요 — 여기선 미지원).
"다 읽고 다 반응" 원칙대로 들어오는 메시지를 빠짐없이 yield 한다.
requests/websockets 지연 import.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from .base import ChatMessage, ChatSource

log = logging.getLogger("aist.chat.chzzk")

_CMD = {"ping": 0, "pong": 10000, "connect": 100, "chat": 93101, "donation": 93102}
_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def _parse_chat_bdy(raw: dict):
    """cmd 93101/93102 의 bdy(list) → (nickname, text) 들을 만든다."""
    out = []
    body = raw.get("bdy")
    if not isinstance(body, list):
        return out
    for c in body:
        nickname = "익명"
        prof = c.get("profile")
        if prof:
            try:
                nickname = json.loads(prof).get("nickname", nickname)
            except (json.JSONDecodeError, TypeError):
                pass
        msg = c.get("msg") or c.get("content") or ""
        is_dono = raw.get("cmd") == _CMD["donation"]
        amount = ""
        if is_dono:
            extra = c.get("extras")
            try:
                amount = str(json.loads(extra).get("payAmount", "")) if extra else ""
            except (json.JSONDecodeError, TypeError):
                amount = ""
        out.append((nickname, msg, is_dono, amount))
    return out


class ChzzkChat(ChatSource):
    platform = "chzzk"

    def __init__(self, channel_id: str):
        if not channel_id:
            raise ValueError("치지직 channel_id 가 필요합니다 (config chat.chzzk.channel_id).")
        self.channel_id = channel_id
        self._ws = None
        self._closed = False

    def _fetch_tokens(self):
        """(chatChannelId, accessToken) 획득 — 블로킹(requests)."""
        import requests
        ls = requests.get(
            f"https://api.chzzk.naver.com/polling/v1/channels/{self.channel_id}/live-status",
            headers=_UA, timeout=10,
        ).json()
        chat_channel_id = (ls.get("content") or {}).get("chatChannelId")
        if not chat_channel_id:
            raise RuntimeError("치지직: 방송 중이 아니거나 chatChannelId 를 못 받음")
        tok = requests.get(
            "https://comm-api.game.naver.com/nng_main/v1/chats/access-token",
            params={"channelId": chat_channel_id, "chatType": "STREAMING"},
            headers=_UA, timeout=10,
        ).json()
        access_token = (tok.get("content") or {}).get("accessToken")
        if not access_token:
            raise RuntimeError("치지직: accessToken 발급 실패")
        return chat_channel_id, access_token

    async def messages(self) -> AsyncIterator[ChatMessage]:
        import websockets
        while not self._closed:
            try:
                cid, token = await asyncio.to_thread(self._fetch_tokens)
            except Exception as e:
                log.error("치지직 토큰 획득 실패: %s (5초 후 재시도)", e)
                await asyncio.sleep(5)
                continue
            try:
                async with websockets.connect("wss://kr-ss1.chat.naver.com/chat",
                                              max_size=None) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({
                        "ver": "2", "cmd": _CMD["connect"], "svcid": "game",
                        "cid": cid, "tid": 1,
                        "bdy": {"uid": None, "devType": 2001,
                                "accTkn": token, "auth": "READ"},
                    }))
                    log.info("치지직 채팅 연결됨 (channel=%s)", self.channel_id)
                    async for raw in ws:
                        data = json.loads(raw)
                        cmd = data.get("cmd")
                        if cmd == _CMD["ping"]:
                            await ws.send(json.dumps({"ver": "2", "cmd": _CMD["pong"]}))
                            continue
                        if cmd in (_CMD["chat"], _CMD["donation"]):
                            for nick, text, is_dono, amount in _parse_chat_bdy(data):
                                if not text:
                                    continue
                                yield ChatMessage(
                                    author=nick, text=text, platform=self.platform,
                                    is_superchat=is_dono, amount=amount, raw=data,
                                )
            except Exception as e:
                if self._closed:
                    break
                log.warning("치지직 연결 끊김: %s (재연결)", e)
                await asyncio.sleep(3)

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.close()
            finally:
                self._ws = None
