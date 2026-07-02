"""방송 진행 핵심 루프 (귀 → 두뇌) — 3단계. '입 하나' 모델.

운영자 지시로 사람이 실제 방송하는 방식을 그대로 구현한다:
- 입은 하나다. 말 안 하는 중이면 채팅에 즉답(딜레이 0).
- 말하는 중이면 채팅을 쌓아뒀다가, 말이 끝나는 순간 전부 이어받는다.
  (임의 타이머/랜덤 없음 — 말이 끝나는 시점이 자연스러운 단위)
- 채팅은 하나도 버리지 않는다(다 반응). '읽기(기록)'는 항상 전부.
- 혼잣말도 눈치껏: 말하는 중엔 안 하고, 채팅 없이 혼잣말이 이어지면
  간격이 점점 길어지며, 채팅이 살아나면 원래 간격으로 리셋.

'말하는 중' 판정: 코어가 보내는 control 신호(conversation-chain-start /
conversation-chain-end)를 추적한다(오케스트레이터의 drain 이 넘겨줌).
우리가 입력을 보낸 직후에는 신호 도착 전이라도 선제적으로 잠근다.
신호가 유실될 때를 대비해 core_busy_timeout_sec 폴백이 있다.

채팅 폭주 처리(flood)는 기본 off — 실제 폭주가 생긴 뒤 운영자가 켠다.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, List, Optional

from .chat.base import ChatMessage, ChatSource
from .config import BroadcastConfig
from .vtuber_bridge import VTuberBridge, format_chat_line

log = logging.getLogger("aist.chat_pipeline")

_PACE_SEC = 0.3   # 상태 점검 주기(눈치 루프)


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
        # 종료판단(채팅 저조/눈치 종료)에 쓰는 공유 상태. tz-aware UTC.
        self.last_chat_time: datetime = datetime.now(timezone.utc)
        self._last_chat_mono = time.monotonic()
        self._flood_window = deque()      # 최근 forward 시각(monotonic)
        # '입 하나' 상태
        self._core_busy = False
        self._busy_since = 0.0
        self._pending: List[ChatMessage] = []
        self._include_platform = False    # 동출일 때만 플랫폼 표기
        # 혼잣말 눈치
        self._consecutive_idle_speaks = 0

    # ------------------------------------------------------------- 외부 상태
    def on_core_message(self, data: dict) -> None:
        """코어 drain 훅 — 말 시작/끝 신호로 '말하는 중'을 추적한다."""
        if data.get("type") != "control":
            return
        text = data.get("text")
        if text == "conversation-chain-start":
            self._core_busy = True
            self._busy_since = time.monotonic()
        elif text == "conversation-chain-end":
            self._core_busy = False

    def is_speaking(self) -> bool:
        return self._core_busy

    def has_pending(self) -> bool:
        return bool(self._pending)

    def seconds_since_last_chat(self) -> float:
        return time.monotonic() - self._last_chat_mono

    # ------------------------------------------------------------------ 실행
    async def run(self, source: ChatSource, stop_event: asyncio.Event):
        self._include_platform = source.platform == "multi"
        consumer = asyncio.create_task(self._consume(source, stop_event))
        pacer = asyncio.create_task(self._pace_loop(stop_event))
        try:
            await stop_event.wait()
        finally:
            for t in (consumer, pacer):
                t.cancel()
            await asyncio.gather(consumer, pacer, return_exceptions=True)
            await source.close()

    async def _consume(self, source: ChatSource, stop_event: asyncio.Event):
        try:
            async for msg in source.messages():
                if stop_event.is_set():
                    break
                self.last_chat_time = datetime.now(timezone.utc)
                self._last_chat_mono = time.monotonic()
                self._consecutive_idle_speaks = 0   # 채팅 살아남 → 혼잣말 리셋
                # '읽기'는 항상 전부 한다(기록/기억용).
                if self.on_message is not None:
                    try:
                        self.on_message(msg)
                    except Exception:  # 기록 실패가 방송을 멈추면 안 됨
                        log.exception("on_message 콜백 오류")
                if not self._should_forward():
                    continue
                if self._busy_now():
                    self._pending.append(msg)       # 말 끝나면 이어받음
                else:
                    await self._send_single(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("채팅 소비 루프 오류 — 종료")

    # ------------------------------------------------------------- 눈치 루프
    async def _pace_loop(self, stop_event: asyncio.Event):
        """말 끝나는 순간 쌓인 채팅 이어받기 + 눈치 혼잣말."""
        try:
            while not stop_event.is_set():
                await asyncio.sleep(_PACE_SEC)
                if self._busy_now():
                    continue
                if self._pending:
                    batch, self._pending = self._pending, []
                    await self._send_batch(batch)
                    continue
                await self._maybe_idle_speak()
        except asyncio.CancelledError:
            raise

    def _busy_now(self) -> bool:
        if not self._core_busy:
            return False
        if time.monotonic() - self._busy_since > self.cfg.core_busy_timeout_sec:
            log.debug("말 끝 신호 유실 추정 → 잠금 해제(폴백)")
            self._core_busy = False
            return False
        return True

    def _mark_busy(self):
        """입력을 보냈으니 코어가 곧 말한다 — 신호 오기 전 선제 잠금."""
        self._core_busy = True
        self._busy_since = time.monotonic()

    async def _send_single(self, msg: ChatMessage):
        if self.cfg.artificial_delay_sec > 0:
            # 기본 0. 운영자가 일부러 넣은 경우에만 작동.
            await asyncio.sleep(self.cfg.artificial_delay_sec)
        platform = msg.platform if self._include_platform else None
        try:
            await self.bridge.say_to_ai(msg.text, source=msg.author, platform=platform)
            self._mark_busy()
        except Exception:
            log.exception("채팅 전달 실패")

    async def _send_batch(self, batch: List[ChatMessage]):
        """말하는 동안 쌓인 채팅을 한 호흡으로 이어받는다(전부, 순서대로)."""
        if len(batch) == 1:
            await self._send_single(batch[0])
            return
        lines = [
            format_chat_line(
                m.text, m.author,
                m.platform if self._include_platform else None,
            )
            for m in batch
        ]
        try:
            await self.bridge.say_to_ai("\n".join(lines))
            self._mark_busy()
        except Exception:
            log.exception("채팅 묶음 전달 실패")

    async def _maybe_idle_speak(self):
        if not self.cfg.idle_proactive_speak:
            return
        base = float(self.cfg.idle_seconds_before_proactive)
        mult = self.cfg.idle_backoff_multiplier ** self._consecutive_idle_speaks
        threshold = base * min(mult, self.cfg.idle_backoff_max_multiple)
        idle = time.monotonic() - self._last_chat_mono
        # 마지막 혼잣말 이후로도 threshold 만큼 지났는지 함께 본다
        if idle >= threshold and (time.monotonic() - self._busy_since) >= threshold:
            log.debug("채팅 %.0f초 조용 → 혼잣말(연속 %d회째)",
                      idle, self._consecutive_idle_speaks + 1)
            try:
                await self.bridge.proactive_speak()
                self._mark_busy()
                self._consecutive_idle_speaks += 1
            except Exception:
                log.exception("혼잣말 트리거 실패")

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
