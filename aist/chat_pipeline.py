"""방송 진행 핵심 루프 (귀 → 두뇌) — 3단계.

기획안의 절대 원칙을 코드로 박는다:
- 채팅은 기본적으로 다 읽고 다 반응. 일부러 일부만 답하거나 빼먹지 않음.
- 응답 속도는 자연스럽게. 인위적 딜레이를 기본으로 넣지 않음(기본 0).
- 채팅이 정말 없을 때만 혼잣말(능동 발화). 과하면 운영자가 줄인다.
- 채팅 폭주 처리(일부만 AI로 넘기기)는 기본 off. 실제 폭주가 생긴 뒤
  운영자가 config 로 켠다. 그때도 '읽기(기록)'는 다 하고, AI 발화로
  넘기는 양만 조절한다.

코드/AI 가 "이러면 사람 같겠지"라고 추측해서 선별·딜레이를 박지 않는다.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

from .chat.base import ChatMessage, ChatSource
from .config import BroadcastConfig
from .vtuber_bridge import VTuberBridge

log = logging.getLogger("aist.chat_pipeline")


class ChatPipeline:
    def __init__(
        self,
        bridge: VTuberBridge,
        cfg: BroadcastConfig,
        on_message: Optional[Callable[[ChatMessage], None]] = None,
    ):
        self.bridge = bridge
        self.cfg = cfg
        self.on_message = on_message
        # 종료판단(채팅 저조)·혼잣말 타이밍에 쓰는 공유 상태. tz-aware UTC.
        self.last_chat_time: datetime = datetime.now(timezone.utc)
        self._last_activity_mono = time.monotonic()
        self._flood_window = deque()  # 최근 forward 시각(monotonic)

    async def run(self, source: ChatSource, stop_event: asyncio.Event):
        consumer = asyncio.create_task(self._consume(source, stop_event))
        idler = asyncio.create_task(self._idle_loop(stop_event))
        try:
            await stop_event.wait()
        finally:
            for t in (consumer, idler):
                t.cancel()
            await asyncio.gather(consumer, idler, return_exceptions=True)
            await source.close()

    async def _consume(self, source: ChatSource, stop_event: asyncio.Event):
        try:
            async for msg in source.messages():
                if stop_event.is_set():
                    break
                self.last_chat_time = datetime.now(timezone.utc)
                self._last_activity_mono = time.monotonic()
                # '읽기'는 항상 전부 한다(기록/기억용).
                if self.on_message is not None:
                    try:
                        self.on_message(msg)
                    except Exception:  # 기록 실패가 방송을 멈추면 안 됨
                        log.exception("on_message 콜백 오류")
                # AI 발화로 넘길지: 기본은 전부. flood off 면 무조건 전달.
                if self._should_forward():
                    if self.cfg.artificial_delay_sec > 0:
                        # 기본 0. 운영자가 일부러 넣은 경우에만 작동.
                        await asyncio.sleep(self.cfg.artificial_delay_sec)
                    await self.bridge.say_to_ai(msg.text, source=msg.author)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("채팅 소비 루프 오류 — 종료")

    def _should_forward(self) -> bool:
        fh = self.cfg.flood_handling
        if not fh.enabled or fh.max_per_window <= 0:
            return True  # 기본: 다 반응
        now = time.monotonic()
        while self._flood_window and now - self._flood_window[0] > fh.window_sec:
            self._flood_window.popleft()
        if len(self._flood_window) >= fh.max_per_window:
            return False  # 폭주 구간: 이번 건은 AI 발화로 넘기지 않음(읽기는 됨)
        self._flood_window.append(now)
        return True

    async def _idle_loop(self, stop_event: asyncio.Event):
        if not self.cfg.idle_proactive_speak:
            return
        threshold = max(5, self.cfg.idle_seconds_before_proactive)
        try:
            while not stop_event.is_set():
                await asyncio.sleep(2)
                idle = time.monotonic() - self._last_activity_mono
                if idle >= threshold:
                    log.debug("채팅 %.0f초 조용 → 혼잣말 트리거", idle)
                    try:
                        await self.bridge.proactive_speak()
                    except Exception:
                        log.exception("혼잣말 트리거 실패")
                    self._last_activity_mono = time.monotonic()
        except asyncio.CancelledError:
            raise
