"""SOOP(숲, 구 아프리카TV) 채팅 리더 — 비공식 채팅 WebSocket.

흐름:
  1) player_live_api 로 CHDOMAIN/CHPT/CHATNO/FTK 획득
  2) wss://{CHDOMAIN}:{CHPT+1}/Websocket/{bid} (subprotocol 'chat') 연결
  3) 로그인(svc 1) → 채널 입장(svc 2)
  4) 수신 패킷을 ESC 로 분리, svc 5(채팅) 파싱

[중요] SOOP 채팅 프로토콜은 비공식이고 리브랜딩 이후 세부가 바뀔 수 있다.
패킷 프레이밍/필드 인덱스는 표준 형식을 따랐으나, 실제 방송으로 한 번
검증한 뒤 _parse_packet 의 인덱스를 조정해야 할 수 있다(운영자 테스트 → 보정).
requests/websockets 지연 import.
"""

import asyncio
import logging
from typing import AsyncIterator, List, Optional, Tuple

from .base import ChatMessage, ChatSource

log = logging.getLogger("aist.chat.soop")

ESC = "\x1b\t"          # 패킷 헤더 태그
F = "\x0c"              # 필드 구분자 (chr 12)
_SVC_CHAT = 5
_LIVE_API = "https://live.afreecatv.com/afreeca/player_live_api.php"
_UA = {"User-Agent": "Mozilla/5.0", "Referer": "https://play.sooplive.co.kr/"}


def _packet(svc: int, body: str) -> str:
    """ESC + svc(4) + bodylen(6) + '00' + body 형식의 송신 패킷."""
    blen = len(body.encode("utf-8"))
    return f"{ESC}{svc:04d}{blen:06d}00{body}"


def _login_packet() -> str:
    return _packet(1, f"{F}{F}")


def _join_packet(chatno: str) -> str:
    # 채널 입장: CHATNO + 여러 빈 필드(표준 형식)
    body = f"{F}{chatno}{F*5}"
    return _packet(2, body)


def _parse_packet(frame: str) -> Optional[Tuple[str, str]]:
    """ESC 제거된 한 프레임 → 채팅이면 (author, text). 아니면 None.

    프레임: svc(4) + bodylen(6) + '00' + body(F 로 구분된 필드들).
    svc 5(채팅)에서 보통 fields[1]=메시지. 닉네임은 뒤쪽 필드에 온다(버전마다
    인덱스 상이) → 비어있지 않은 후보를 고른다.
    """
    if len(frame) < 12:
        return None
    try:
        svc = int(frame[0:4])
    except ValueError:
        return None
    if svc != _SVC_CHAT:
        return None
    body = frame[12:]
    fields = body.split(F)
    if len(fields) < 2:
        return None
    text = fields[1]
    if not text:
        return None
    # 닉네임 후보: 메시지 이후 필드 중 사람 이름처럼 보이는 첫 비어있지 않은 값
    author = "?"
    for f in fields[2:]:
        if f and not f.isdigit():
            author = f
            break
    return author, text


class SoopChat(ChatSource):
    platform = "soop"

    def __init__(self, bj_id: str):
        if not bj_id:
            raise ValueError("SOOP bj_id(스트리머 ID)가 필요합니다 (config chat.soop.bj_id).")
        self.bj_id = bj_id
        self._ws = None
        self._closed = False

    def _fetch_live_info(self) -> dict:
        import requests
        r = requests.post(_LIVE_API, headers=_UA, timeout=10, data={
            "bid": self.bj_id, "type": "live",
            "player_type": "html5", "mode": "landing",
        })
        ch = (r.json() or {}).get("CHANNEL") or {}
        if str(ch.get("RESULT")) != "1":
            raise RuntimeError("SOOP: 방송 중이 아니거나 채널 정보를 못 받음")
        return ch

    async def messages(self) -> AsyncIterator[ChatMessage]:
        import websockets
        while not self._closed:
            try:
                ch = await asyncio.to_thread(self._fetch_live_info)
                domain = ch["CHDOMAIN"].lower()
                port = int(ch["CHPT"]) + 1            # wss 는 보통 +1
                chatno = str(ch["CHATNO"])
                url = f"wss://{domain}:{port}/Websocket/{self.bj_id}"
            except Exception as e:
                log.error("SOOP 라이브 정보 획득 실패: %s (5초 후 재시도)", e)
                await asyncio.sleep(5)
                continue
            try:
                async with websockets.connect(url, subprotocols=["chat"],
                                              max_size=None) as ws:
                    self._ws = ws
                    await ws.send(_login_packet())
                    await asyncio.sleep(0.3)
                    await ws.send(_join_packet(chatno))
                    log.info("SOOP 채팅 연결됨 (bj=%s, %s)", self.bj_id, url)
                    async for raw in ws:
                        text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
                        for frame in text.split(ESC):
                            if not frame:
                                continue
                            parsed = _parse_packet(frame)
                            if parsed:
                                yield ChatMessage(author=parsed[0], text=parsed[1],
                                                  platform=self.platform, raw=frame)
            except Exception as e:
                if self._closed:
                    break
                log.warning("SOOP 연결 끊김: %s (재연결)", e)
                await asyncio.sleep(3)

    async def probe(self) -> str:
        try:
            ch = await asyncio.to_thread(self._fetch_live_info)
            return f"온에어(CHATNO {ch.get('CHATNO')})"
        except Exception as e:
            return f"방송중 아님/실패: {e}"

    async def close(self) -> None:
        self._closed = True
        if self._ws is not None:
            try:
                await self._ws.close()
            finally:
                self._ws = None
