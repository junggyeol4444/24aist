"""유튜브 라이브 채팅 리더 — pytchat 사용.

pytchat 는 영상 ID 로 라이브 채팅을 폴링한다. 슈퍼챗(superchat)도
타입으로 구분된다. pytchat 는 동기 라이브러리라, 블로킹 호출을
asyncio.to_thread 로 감싸 모든 메시지를 빠짐없이 흘려보낸다.

pytchat 지연 import.
"""

import asyncio
import logging
from typing import AsyncIterator

from .base import ChatMessage, ChatSource

log = logging.getLogger("aist.chat.youtube")


class YouTubeChat(ChatSource):
    platform = "youtube"

    def __init__(self, video_id: str, poll_interval: float = 1.0):
        if not video_id:
            raise ValueError("유튜브 video_id(라이브 영상 ID)가 필요합니다.")
        self.video_id = video_id
        self.poll_interval = poll_interval
        self._chat = None

    async def messages(self) -> AsyncIterator[ChatMessage]:
        try:
            import pytchat  # 지연 import
        except ImportError as e:
            raise RuntimeError("pytchat 미설치: `pip install pytchat`") from e
        self._chat = pytchat.create(video_id=self.video_id)
        log.info("유튜브 라이브 채팅 연결됨 (video=%s)", self.video_id)
        while self._chat.is_alive():
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

    async def close(self) -> None:
        if self._chat is not None:
            try:
                self._chat.terminate()
            finally:
                self._chat = None
