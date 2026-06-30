"""Kick(kick.com) 채팅 리더 — Pusher WebSocket.

흐름:
  1) GET https://kick.com/api/v2/channels/{slug} → chatroom.id
  2) wss://ws-us2.pusher.com/app/{APP_KEY}?... 연결(익명 가능)
  3) chatrooms.{id}.v2 채널 구독
  4) App\\Events\\ChatMessageEvent 수신 → data(JSON 문자열) 파싱

Kick API 는 Cloudflare 뒤에 있어 채널 조회가 403 날 수 있다(브라우저 UA 로
완화 시도). 막히면 chatroom id 를 직접 넣어도 되게 했다.
requests/websockets 지연 import.
"""

import asyncio
import json
import logging
from typing import AsyncIterator, Optional

from .base import ChatMessage, ChatSource

log = logging.getLogger("aist.chat.kick")

_APP_KEY = "32cbd69e4b950bf97679"   # Kick 의 공개 Pusher app key
_WS_URL = (
    f"wss://ws-us2.pusher.com/app/{_APP_KEY}"
    "?protocol=7&client=js&version=8.4.0-rc2&flash=false"
)
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}


def _parse_chat_event(data_str: str):
    """ChatMessageEvent 의 data(JSON 문자열) → (author, text). 실패 시 None."""
    try:
        obj = json.loads(data_str)
    except (json.JSONDecodeError, TypeError):
        return None
    text = obj.get("content", "")
    sender = obj.get("sender") or {}
    author = sender.get("username") or sender.get("slug") or "?"
    return author, text


class KickChat(ChatSource):
    platform = "kick"

    def __init__(self, channel: str = "", chatroom_id: Optional[int] = None):
        if not channel and not chatroom_id:
            raise ValueError("kick channel(슬러그) 또는 chatroom_id 가 필요합니다.")
        self.channel = channel
        self.chatroom_id = chatroom_id
        self._ws = None
        self._closed = False

    def _fetch_chatroom_id(self) -> int:
        import requests
        r = requests.get(f"https://kick.com/api/v2/channels/{self.channel}",
                         headers=_UA, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"kick 채널 조회 실패({r.status_code}). "
                               f"Cloudflare 차단이면 chatroom_id 를 직접 지정하세요.")
        return r.json()["chatroom"]["id"]

    async def messages(self) -> AsyncIterator[ChatMessage]:
        import websockets
        while not self._closed:
            try:
                cid = self.chatroom_id or await asyncio.to_thread(self._fetch_chatroom_id)
            except Exception as e:
                log.error("kick chatroom id 획득 실패: %s (5초 후 재시도)", e)
                await asyncio.sleep(5)
                continue
            try:
                async with websockets.connect(_WS_URL, max_size=None) as ws:
                    self._ws = ws
                    await ws.send(json.dumps({
                        "event": "pusher:subscribe",
                        "data": {"auth": "", "channel": f"chatrooms.{cid}.v2"},
                    }))
                    log.info("kick 채팅 연결됨 (channel=%s, chatroom=%s)", self.channel, cid)
                    async for raw in ws:
                        evt = json.loads(raw)
                        name = evt.get("event", "")
                        if name == "pusher:ping":
                            await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
                            continue
                        if name.endswith("ChatMessageEvent"):
                            parsed = _parse_chat_event(evt.get("data", ""))
                            if parsed and parsed[1]:
                                yield ChatMessage(author=parsed[0], text=parsed[1],
                                                  platform=self.platform, raw=evt)
            except Exception as e:
                if self._closed:
                    break
                log.warning("kick 연결 끊김: %s (재연결)", e)
                await asyncio.sleep(3)

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.close()
            finally:
                self._ws = None
