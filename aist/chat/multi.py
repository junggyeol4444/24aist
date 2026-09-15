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
        self._watcher = None
        self._closed = False

    async def _pump(self, src: ChatSource):
        try:
            async for m in src.messages():
                await self._queue.put(m)
            log.warning("[%s] 채팅 소스가 끝났습니다 — 이 플랫폼 채팅이 더는 안 옵니다",
                        src.platform)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 플랫폼별 사유 다양
            log.error("[%s] 채팅 소스 오류 — 이 플랫폼만 중단: %s", src.platform, e)

    async def _watch_all_done(self):
        """모든 플랫폼이 끝나면 messages() 를 깨워 끝낸다.

        이게 없으면 전 플랫폼이 죽어도 messages() 가 큐에서 영원히 기다린다.
        그러면 채팅이 영영 안 오는데 방송은 계속 돈다(최대 max_minutes).
        오케스트레이터가 '채팅 소스가 죽었다'를 알아채려면 여기서 끝나야 한다.
        """
        await asyncio.gather(*self._tasks, return_exceptions=True)
        if not self._closed:
            log.error("동출 채팅: 모든 플랫폼이 끊겼습니다.")
            await self._queue.put(_SENTINEL)

    async def messages(self) -> AsyncIterator[ChatMessage]:
        self._tasks = [asyncio.create_task(self._pump(s)) for s in self.sources]
        self._watcher = asyncio.create_task(self._watch_all_done())
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
        if self._watcher is not None:
            self._watcher.cancel()
        await asyncio.gather(*(s.close() for s in self.sources), return_exceptions=True)
        await self._queue.put(_SENTINEL)  # messages() 의 get() 을 깨운다
