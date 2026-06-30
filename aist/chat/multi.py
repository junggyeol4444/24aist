"""동출(동시 송출) — 여러 플랫폼 채팅을 하나의 스트림으로 합친다.

각 ChatSource 를 백그라운드 태스크로 돌려, 들어오는 메시지를 공용 큐에
모아 순서대로 yield 한다. 어느 플랫폼에서 왔는지는 ChatMessage.platform
으로 구분되므로, 코어/AI 가 "트위치에서 누가~", "치지직에서 누가~" 처럼
다룰 수 있다. 여기서도 메시지를 선별하지 않고 전부 흘려보낸다.
"""

import asyncio
import logging
from typing import AsyncIterator, List

from .base import ChatMessage, ChatSource

log = logging.getLogger("aist.chat.multi")

_SENTINEL = object()


class MultiChatSource(ChatSource):
    platform = "multi"

    def __init__(self, sources: List[ChatSource]):
        if not sources:
            raise ValueError("MultiChatSource 는 최소 1개의 소스가 필요합니다.")
        self.sources = sources
        self._queue: asyncio.Queue = asyncio.Queue()
        self._tasks: List[asyncio.Task] = []
        self._closed = False

    async def _pump(self, src: ChatSource):
        try:
            async for m in src.messages():
                await self._queue.put(m)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[%s] 채팅 소스 오류 — 이 플랫폼만 중단", src.platform)

    async def messages(self) -> AsyncIterator[ChatMessage]:
        self._tasks = [asyncio.create_task(self._pump(s)) for s in self.sources]
        log.info("동출 채팅 시작 — 플랫폼: %s", ", ".join(s.platform for s in self.sources))
        while not self._closed:
            item = await self._queue.get()
            if item is _SENTINEL:
                break
            yield item

    async def close(self) -> None:
        self._closed = True
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*(s.close() for s in self.sources), return_exceptions=True)
        await self._queue.put(_SENTINEL)  # messages() 의 get() 을 깨운다
