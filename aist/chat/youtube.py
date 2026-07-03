"""유튜브 라이브 채팅 리더 — pytchat 사용 + 라이브 영상 ID 자동발견.

video_id 는 매 방송 바뀐다. 완전 자동화(사람 손 없이)를 위해 channel
(핸들 @이름 또는 채널 ID UC…)을 주면, 방송 시작 시
https://www.youtube.com/<채널>/live 페이지에서 현재 라이브의 videoId 를
추출한다(비공식·best-effort — 페이지 구조가 바뀌면 보정 필요).

pytchat 는 동기 라이브러리라 블로킹 호출을 asyncio.to_thread 로 감싸
모든 메시지를 빠짐없이 흘려보낸다. pytchat/requests 지연 import.
"""

import asyncio
import logging
import re
from typing import AsyncIterator, Optional

from .base import ChatMessage, ChatSource

log = logging.getLogger("aist.chat.youtube")

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_VIDEO_ID_RE = re.compile(r'"videoId"\s*:\s*"([\w-]{11})"')


def resolve_live_video_id(channel: str) -> Optional[str]:
    """채널 핸들(@이름)/채널 ID(UC…) → 현재 라이브 videoId. 없으면 None."""
    import requests
    channel = channel.strip()
    if channel.startswith("UC"):
        url = f"https://www.youtube.com/channel/{channel}/live"
    else:
        handle = channel if channel.startswith("@") else "@" + channel
        url = f"https://www.youtube.com/{handle}/live"
    r = requests.get(url, headers=_UA, timeout=15)
    if r.status_code != 200:
        return None
    # 라이브가 아니면 /live 가 채널 홈으로 이동해 videoId 가 없거나
    # isLiveNow 가 없다. 둘 다 확인한다.
    if '"isLiveNow":true' not in r.text and '"isLive":true' not in r.text:
        return None
    m = _VIDEO_ID_RE.search(r.text)
    return m.group(1) if m else None


class YouTubeChat(ChatSource):
    platform = "youtube"

    def __init__(self, video_id: str = "", channel: str = "",
                 poll_interval: float = 1.0):
        if not video_id and not channel:
            raise ValueError(
                "유튜브 video_id(라이브 영상 ID) 또는 channel(핸들/채널ID)이 필요합니다."
            )
        self.video_id = video_id
        self.channel = channel
        self.poll_interval = poll_interval
        self._chat = None
        self._closed = False

    async def _ensure_video_id(self) -> Optional[str]:
        if self.video_id:
            return self.video_id
        vid = await asyncio.to_thread(resolve_live_video_id, self.channel)
        if vid:
            log.info("유튜브 라이브 자동발견: %s → video=%s", self.channel, vid)
        return vid

    async def messages(self) -> AsyncIterator[ChatMessage]:
        try:
            import pytchat  # 지연 import
        except ImportError as e:
            raise RuntimeError("pytchat 미설치: `pip install pytchat`") from e

        while not self._closed:
            vid = await self._ensure_video_id()
            if not vid:
                log.info("유튜브: 아직 라이브가 아님(%s) — 30초 후 재확인", self.channel)
                await asyncio.sleep(30)
                continue
            try:
                self._chat = pytchat.create(video_id=vid)
                log.info("유튜브 라이브 채팅 연결됨 (video=%s)", vid)
                while self._chat.is_alive() and not self._closed:
                    data = await asyncio.to_thread(self._chat.get)
                    for item in data.sync_items():
                        is_sc = getattr(item, "type", "") in ("superChat", "superSticker")
                        yield ChatMessage(
                            author=getattr(item.author, "name", "?"),
                            text=item.message,
                            platform=self.platform,
                            is_superchat=is_sc,
                            amount=getattr(item, "amountString", ""),
                            raw=item,
                        )
                    await asyncio.sleep(self.poll_interval)
            except Exception as e:
                if self._closed:
                    break
                log.warning("유튜브 채팅 오류: %s (재시도)", e)
                await asyncio.sleep(5)
            finally:
                if self._chat is not None:
                    try:
                        self._chat.terminate()
                    except Exception:
                        pass
                    self._chat = None
                # 자동발견 모드면 다음 루프에서 새 라이브를 다시 찾는다
                if self.channel and not self._closed:
                    self.video_id = ""

    async def probe(self) -> str:
        if self.video_id:
            return f"video_id 직접 지정됨({self.video_id})"
        try:
            vid = await asyncio.to_thread(resolve_live_video_id, self.channel)
            return f"라이브 발견(video {vid})" if vid else "라이브 아님(자동발견 대기)"
        except Exception as e:
            return f"자동발견 실패: {e}"

    async def close(self) -> None:
        self._closed = True
        if self._chat is not None:
            try:
                self._chat.terminate()
            finally:
                self._chat = None
