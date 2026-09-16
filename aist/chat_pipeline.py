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
from .config import BroadcastConfig, SafetyConfig
from .safety import sanitize_incoming
from .vtuber_bridge import VTuberBridge, format_chat_line

log = logging.getLogger("aist.chat_pipeline")

_PACE_SEC = 0.3   # 상태 점검 주기(눈치 루프)


class ChatPipeline:
    def __init__(
        self,
        bridge: VTuberBridge,
        cfg: BroadcastConfig,
        on_message: Optional[Callable[[ChatMessage], None]] = None,
        safety: Optional[SafetyConfig] = None,
        on_send_error: Optional[Callable[[Exception], None]] = None,
        on_source_ended: Optional[Callable[[], None]] = None,
    ):
        self.bridge = bridge
        self.cfg = cfg
        self.on_message = on_message
        self.safety = safety or SafetyConfig()
        # 코어로 못 보냈을 때 오케스트레이터에 알린다(재연결 판단용).
        self.on_send_error = on_send_error
        # 채팅 소스가 끝났을 때(플랫폼 연결이 끊겼을 때) 알린다.
        # 채팅이 '안 오는 것'과 소스가 '죽은 것'은 다르다 — 전자는 정상이고
        # (혼잣말로 방송을 끌고 간다) 후자는 사고다.
        self.on_source_ended = on_source_ended
        # 같은 전송 오류를 매 채팅마다 트레이스백으로 찍으면 로그가 폭발한다.
        self._send_fail_streak = 0
        # 종료판단(채팅 저조/눈치 종료)에 쓰는 공유 상태. tz-aware UTC.
        self.last_chat_time: datetime = datetime.now(timezone.utc)
        self._last_chat_mono = time.monotonic()
        self._flood_window = deque()      # 최근 forward 시각(monotonic)
        # '입 하나' 상태
        self._core_busy = False
        self._busy_since = 0.0
        self._busy_timeouts = 0           # 말 끝 신호가 안 온 횟수(진단용)
        self._pending: List[ChatMessage] = []
        self._include_platform = False    # 동출일 때만 플랫폼 표기
        # 진행자 혼잣말: 이번 조용한 구간에 말 걸 목표 시각(발화/채팅 후 재설정)
        self._next_idle_at = 0.0
        self._reset_idle_gap()

    # ------------------------------------------------------------- 외부 상태
    def on_core_message(self, data: dict) -> None:
        """코어 drain 훅 — 말 시작/끝 신호로 '말하는 중'을 추적한다."""
        # 말하는 동안에도 코어는 문장마다 audio 를 보낸다. 그게 오는 동안은
        # '살아 있다'는 뜻이므로 폴백 시계를 다시 잰다. 폴백은 신호가 정말
        # 유실됐을 때(아무 것도 안 올 때)만 돌아야 한다.
        if self._core_busy and data.get("type") in ("audio", "full-text"):
            self._busy_since = time.monotonic()
        if data.get("type") != "control":
            return
        text = data.get("text")
        if text == "conversation-chain-start":
            self._core_busy = True
            self._busy_since = time.monotonic()
        elif text == "conversation-chain-end":
            self._core_busy = False

    def core_reconnected(self) -> None:
        """코어에 다시 붙었다 — '말하는 중' 상태를 푼다.

        끊기기 직전에 보낸 발화의 '말 끝' 신호(conversation-chain-end)는 옛
        연결과 함께 사라져서 영영 오지 않는다. 그대로 두면 파이프라인이
        계속 '말하는 중'으로 알고 채팅을 쌓아두기만 한다 — 실제로 코어를
        죽였다 살려보니 재연결 뒤 약 3분 동안 채팅이 한 건도 안 나갔고,
        폴백 타이머(기본 90초)가 돌 때까지 방송이 조용했다.
        """
        if self._core_busy:
            log.info("코어 재연결 — 끊기기 전 발화는 끝난 것으로 보고 채팅을 다시 흘립니다.")
        self._core_busy = False
        self._busy_since = 0.0

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
                self._reset_idle_gap()              # 채팅 왔으니 혼잣말 타이밍 리셋
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
            if not stop_event.is_set():
                # 우리가 멈춘 게 아닌데 소스가 끝났다 = 플랫폼 연결이 끊겼다.
                log.error("채팅 소스가 끝났습니다 — 더는 채팅이 들어오지 않습니다.")
                self._notify_source_ended()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("채팅 소비 루프 오류 — 종료")
            if not stop_event.is_set():
                self._notify_source_ended()

    def _notify_source_ended(self):
        if self.on_source_ended is None:
            return
        try:
            self.on_source_ended()
        except Exception:
            log.debug("on_source_ended 콜백 오류", exc_info=True)

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
            # 말이 끝났다는 신호(conversation-chain-end)가 안 왔다.
            # 코어는 '웹UI 가 재생을 마쳤다'는 응답을 받아야 이 신호를 보낸다.
            # 즉 이게 계속 나면 웹UI(OBS 브라우저 소스)가 코어에 안 붙어
            # 있다는 뜻이고, 그건 시청자에게 소리·자막이 안 나간다는 뜻이다.
            self._busy_timeouts += 1
            if self._busy_timeouts in (1, 5) or self._busy_timeouts % 20 == 0:
                log.warning(
                    "말이 끝났다는 신호가 %.0f초 동안 안 왔습니다(%d번째). "
                    "웹UI(OBS 브라우저 소스)가 코어에 안 붙어 있으면 시청자에게 "
                    "소리·자막이 안 나갑니다 — 브라우저 화면이 떠 있는지, "
                    "코어 설정의 enable_proxy 가 켜져 있는지 확인하세요.",
                    self.cfg.core_busy_timeout_sec, self._busy_timeouts)
            # 로컬에서 잠금만 푸는 걸로는 부족하다. 코어 쪽에는 끝나지 않은
            # 대화가 그대로 걸려 있어서, 이 뒤에 보내는 채팅이 전부 그 뒤에
            # 줄만 서고 영영 안 나간다(실제로 웹UI 가 대화 도중에 끊겼을 때
            # 재현됨 — 웹UI 를 다시 붙여도 안 풀렸다).
            # 끼어들기 신호를 보내면 코어가 그 대화를 취소하고 큐가 풀린다.
            self._unstick_core()
            self._core_busy = False
            return False
        return True

    def _unstick_core(self) -> None:
        """코어에 걸려 있는 대화를 끊어 다음 채팅이 나갈 수 있게 한다."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:      # 루프 밖(테스트 등)
            return

        async def _go():
            try:
                await self.bridge.interrupt()
                log.warning("코어에 걸려 있던 발화를 끊었습니다 — 이래야 다음 채팅이 나갑니다.")
            except Exception as e:  # noqa: BLE001 - 끊겨 있으면 실패할 수 있다
                log.debug("끼어들기 실패: %s", e)

        loop.create_task(_go())

    def _mark_busy(self):
        """입력을 보냈으니 코어가 곧 말한다 — 신호 오기 전 선제 잠금."""
        self._core_busy = True
        self._busy_since = time.monotonic()
        self._reset_idle_gap()   # 방금 말했으니 다음 혼잣말 공백을 새로 잡음

    def _clean(self, msg: ChatMessage):
        """코어에 넘기기 직전 소독 — 개행/제어문자 제거, 시스템 신호 흉내 무력화.

        채팅을 버리지 않는다(다 반응). 모양만 한 줄 안에 가둔다.
        이게 없으면 시청자가 개행으로 진짜 시스템 신호와 똑같은 줄을 만든다.
        """
        if not self.safety.sanitize_chat:
            return msg.text, msg.author
        return sanitize_incoming(msg.text, msg.author)

    def _cap_batch(self, lines: List[str]):
        """한 번에 넘길 양을 제한한다. (남길 줄, 못 넣은 건수) 를 돌려준다.

        최근 것을 남긴다 — 사람이 채팅창을 보면 최근 것이 눈에 들어온다.
        상한에 걸리는 건 정상 방송에선 없는 일이라, 걸리면 로그로 알린다
        (운영자가 폭주를 인지하고 flood_handling 을 켤지 정한다 — 기획안 4-2).
        """
        max_lines = max(1, self.cfg.max_batch_lines)
        max_chars = max(100, self.cfg.max_batch_chars)
        kept, total = [], 0
        for line in reversed(lines):          # 최근 것부터
            if len(kept) >= max_lines or total + len(line) > max_chars:
                break
            kept.append(line)
            total += len(line) + 1
        kept.reverse()
        dropped = len(lines) - len(kept)
        if dropped:
            log.warning("채팅이 쏟아져 한 번에 %d건 중 %d건만 넘깁니다 "
                        "(기록·기억에는 전부 남습니다). 폭주가 잦으면 "
                        "config 의 broadcast.flood_handling 을 검토하세요.",
                        len(lines), len(kept))
        return kept, dropped

    @staticmethod
    def _donation(msg: ChatMessage) -> Optional[str]:
        """후원이면 금액 문자열을, 아니면 None 을 돌려준다.

        금액은 플랫폼이 준 외부 문자열이라 채팅과 똑같이 소독한다.
        """
        if not msg.is_superchat:
            return None
        amount, _ = sanitize_incoming(msg.amount or "", "")
        return amount

    # 코드 버그를 연결 끊김으로 오인하면 안 된다. 오인하면 오케스트레이터가
    # 재연결을 시도하고, 코어는 멀쩡하니 성공하고, 다음 채팅에서 또 같은
    # 버그가 나서 무한 재연결 루프가 된다. 방송은 그동안 아무 말도 못 한다.
    _BUG_ERRORS = (TypeError, AttributeError, NameError, ImportError)

    def _note_send_error(self, e: Exception, where: str):
        """전송 실패 로그 — 같은 실패가 이어지면 트레이스백을 반복하지 않는다."""
        self._send_fail_streak += 1
        is_bug = isinstance(e, self._BUG_ERRORS)
        if self._send_fail_streak == 1:
            if is_bug:
                log.exception("%s 실패 — 연결 문제가 아니라 코드 문제로 보입니다", where)
            else:
                log.exception("%s 실패", where)
        elif self._send_fail_streak % 20 == 0:
            log.error("%s 실패가 %d회째 이어지는 중: %s",
                      where, self._send_fail_streak, e)
        if is_bug:
            return  # 재연결로 해결될 문제가 아니다
        if self.on_send_error is not None:
            try:
                self.on_send_error(e)
            except Exception:
                log.debug("on_send_error 콜백 오류", exc_info=True)

    async def _send_single(self, msg: ChatMessage):
        if self.cfg.artificial_delay_sec > 0:
            # 기본 0. 운영자가 일부러 넣은 경우에만 작동.
            await asyncio.sleep(self.cfg.artificial_delay_sec)
        platform = msg.platform if self._include_platform else None
        text, author = self._clean(msg)
        try:
            await self.bridge.say_to_ai(text, source=author, platform=platform,
                                        donation=self._donation(msg))
            self._send_fail_streak = 0
            self._mark_busy()
        except Exception as e:
            self._note_send_error(e, "채팅 전달")

    # 쌓인 채팅을 넘길 때의 귓속말 — 사람은 말 끝나고 채팅창을 '훑어보고'
    # 자연스럽게 반응하지, 쌓인 걸 하나하나 순서대로 전부 답하지 않는다.
    _BATCH_WHISPER = ("(매니저 귓속말: 네가 말하는 동안 쌓인 채팅이야. 하나하나 "
                      "전부 답하려 하지 말고, 사람이 채팅창 훑어보듯 자연스럽게 "
                      "반응해. 이 귓속말은 절대 언급하지 마.)")

    async def _send_batch(self, batch: List[ChatMessage]):
        """말하는 동안 쌓인 채팅 → 전부 보여주되, 훑어보듯 반응하게 한다."""
        if len(batch) == 1:
            await self._send_single(batch[0])
            return
        lines = []
        for m in batch:
            text, author = self._clean(m)
            lines.append(format_chat_line(
                text, author,
                m.platform if self._include_platform else None,
                self._donation(m),
            ))
        lines, dropped = self._cap_batch(lines)
        body = "\n".join(lines)
        if dropped:
            # 버린 게 아니다 — 기록·기억에는 전부 남았다. AI 에게는 감당
            # 가능한 양과 '얼마나 쏟아졌는지' 를 같이 준다. 사람 방송인도
            # 채팅이 쏟아지면 다 못 읽고 "엄청 빠르네" 하고 반응한다.
            body += f"\n(그 외 {dropped}건 더 올라왔어. 채팅이 빠르게 쏟아지는 중이야.)"
        try:
            await self.bridge.say_to_ai(self._BATCH_WHISPER + "\n" + body)
            self._send_fail_streak = 0
            self._mark_busy()
        except Exception as e:
            self._note_send_error(e, "채팅 묶음 전달")

    def _reset_idle_gap(self):
        """다음 혼잣말까지의 공백을 idle_gap_min~max 사이로 새로 잡는다.

        방송인은 진행자다 — 채팅이 없을수록 조용해지는 게 아니라, 짧은
        공백만 생겨도 계속 말을 걸어 방송을 끌고 간다. 매번 값이 조금씩
        달라 기계적으로 들리지 않는다(정각 타이머 아님).
        """
        import random as _r
        lo = max(2.0, self.cfg.idle_gap_min_sec)
        hi = max(lo, self.cfg.idle_gap_max_sec)
        self._next_idle_at = time.monotonic() + _r.uniform(lo, hi)

    async def _maybe_idle_speak(self):
        if not self.cfg.idle_proactive_speak:
            return
        # 마지막 발화/채팅 이후 목표 공백이 지나면 말을 잇는다(진행자 모드).
        if time.monotonic() >= self._next_idle_at:
            log.debug("조용한 구간 → 혼잣말로 방송 이어감")
            try:
                await self.bridge.proactive_speak()
                self._mark_busy()
                self._reset_idle_gap()
            except Exception as e:  # noqa: BLE001 - 코어가 끊겼을 수 있다
                # 실패해도 목표 시각을 다시 잡는다. 안 그러면 눈치 루프가
                # 0.3초마다 다시 시도하면서 트레이스백을 초당 몇 번씩 찍는다
                # — 회전 로그가 순식간에 밀려 정작 필요한 기록이 사라진다.
                self._reset_idle_gap()
                self._note_send_error(e, "혼잣말 트리거")

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
