"""오케스트레이터 (심장박동) — 부품들을 묶어 지휘하는 메인 컨트롤러.

하루 동선(2-2)을 코드로 구현한다:
  24h 대기 → 스케줄러가 시작 판단 → 시작 공지 → OBS 시작 → 코어 연결
  → 채팅 루프(다 반응) → 종료 판단 → 마무리 → OBS 종료 → 종료 공지
  → 세션 기억 저장 → 다음 방송 계산 → 다시 대기

외부 동작(OBS/코어/채팅/공지)은 모두 best-effort 로 감싼다. 한 번의
실패가 24시간 운영 전체를 죽이지 않도록 한다.

수동 → 반자동 → 완전자동을 모두 지원:
  - run():            완전 자동(스케줄러가 켜고 끔) — 5단계
  - run_one_now():    지금 한 방송만(시작 수동, 끄는 건 자동) — 3·4단계
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .announce.base import Announcer
from .announce.composer import AnnounceContext, compose, should_post
from .announce.discord_bot import DiscordAnnouncer
from .announce.naver_cafe import NaverCafeAnnouncer
from .chat.factory import make_chat_source
from .chat_pipeline import ChatPipeline
from .config import Config
from .end_judge import EndJudge, Phase
from .llm import LLMClient
from .memory import Memory
from .obs_control import ObsController, ObsError
from .persona import Persona
from .report import generate_report
from .scheduler import Scheduler
from .transcript import Transcript
from .vtuber_bridge import VTuberBridge

log = logging.getLogger("aist.orchestrator")

# 마무리 단계의 '매니저 귓속말' — 페르소나 무대규칙에 따라 AI 는 이 내용을
# 입 밖에 내지 않고 행동으로만 반영한다. (운영자가 문구 수정 가능)
_CUE_WIND_DOWN = ("(매니저 귓속말: 슬슬 마무리 분위기로 가자. 새 주제나 새 판 "
                  "벌이지 말고 지금 하던 얘기·게임을 정리하면서, 곧 마무리한다고 "
                  "자연스럽게 흘려줘. 이 귓속말은 절대 언급하지 마.)")
_CUE_CLOSING = ("(매니저 귓속말: 이제 방송 끝낼 시간이야. 오늘 와준 시청자들한테 "
                "자연스럽게 마무리 인사해줘. 이 귓속말은 절대 언급하지 마.)")
# 방송 오프닝(4-1): 방송 켜지면 방송인이 하듯 인사로 문을 연다.
_CUE_OPENING = ("(매니저 귓속말: 방송 방금 시작했어. 방송 여는 인사로 시작해줘. "
                "\"안녕~ 오늘도 왔어요\" 같은 느낌으로 반갑게, 오늘 뭐 할지 살짝 "
                "얘기하면서 자연스럽게 문 열어줘. 이 귓속말은 절대 언급하지 마.)")
# 마무리 인사하고 실제 스트림을 내리기까지의 여유(초). 사람도 인사 후 바로
# 안 끄고 30초~1분 정도 여운을 둔다. config.end_judge.wind_down 에서 조정.


def _now(tz_name: str) -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception:  # tz 미지원/오타 → 로컬 시간
        return datetime.now().astimezone()


class Orchestrator:
    def __init__(self, cfg: Config, persona: Persona):
        self.cfg = cfg
        self.persona = persona
        self.scheduler = Scheduler(cfg.scheduler)
        self.memory = Memory(cfg.memory)
        self.llm = LLMClient(cfg.llm, cfg.secrets)
        self._stop = asyncio.Event()

    def request_stop(self):
        self._stop.set()

    # ---------------------------------------------------------------- 자동
    async def run(self):
        """완전 자동 루프. 스케줄러가 켜고, 종료 판단이 끈다."""
        if not self.scheduler.enabled:
            log.warning("scheduler.enabled=false → 자동 시작 안 함. run_one_now() 를 쓰세요.")
            return
        log.info("오케스트레이터 시작 — 24시간 대기 모드")
        while not self._stop.is_set():
            now = _now(self.cfg.scheduler.timezone)
            start_at = self.scheduler.next_start(now)
            if start_at is None:
                log.info("앞으로 예정된 방송이 없습니다(전부 휴방). 1시간 후 재확인.")
                await self._sleep_or_stop(3600)
                continue
            wait = self.scheduler.seconds_until(start_at, now)
            log.info("다음 방송: %s (%.0f분 후)", start_at.isoformat(), wait / 60)

            # 방송 시작 전 공지(2-2②): 시작 X분 전에 미리 게시(선택).
            pre_announced = False
            lead_sec = self.cfg.announce.pre_announce_minutes * 60
            if lead_sec > 0 and self.cfg.announce.on_start and wait > lead_sec:
                await self._sleep_or_stop(wait - lead_sec)
                if self._stop.is_set():
                    break
                await self._announce("start", _now(self.cfg.scheduler.timezone))
                pre_announced = True
                now = _now(self.cfg.scheduler.timezone)
                wait = self.scheduler.seconds_until(start_at, now)

            await self._sleep_or_stop(wait)
            if self._stop.is_set():
                break
            try:
                await self._run_broadcast(skip_start_announce=pre_announced)
            except Exception:
                log.exception("방송 사이클 중 오류 — 루프는 계속 유지")

    async def run_one_now(self):
        """지금 한 방송만 진행(시작 수동). 끄는 건 종료 판단이 한다."""
        await self._run_broadcast()

    # ------------------------------------------------------------ 한 사이클
    async def _run_broadcast(self, skip_start_announce: bool = False):
        cfg = self.cfg
        start_dt = _now(cfg.scheduler.timezone)
        log.info("=== 방송 시작 (%s) ===", start_dt.isoformat())

        bridge = VTuberBridge(cfg.vtuber)
        obs = ObsController(cfg.obs)
        pipeline: Optional[ChatPipeline] = None
        chat_stop = asyncio.Event()
        pipeline_task: Optional[asyncio.Task] = None
        game_task: Optional[asyncio.Task] = None

        # 트랜스크립트(사고발언 점검·다시보기 학습용). 실패해도 방송은 진행.
        transcript = None
        if cfg.logging.transcript:
            try:
                transcript = Transcript(str(Path(cfg.logging.dir) / "transcripts"))
                transcript.open_session(start_dt)
            except Exception as e:
                log.warning("트랜스크립트 시작 실패(기록 없이 진행): %s", e)
                transcript = None

        # 1) 시작 공지 (실패해도 방송은 진행). 사전 공지 했으면 중복 방지.
        if not skip_start_announce:
            await self._announce("start", start_dt)

        # 2) OBS 시작
        try:
            obs.connect()
            obs.start_stream()
        except ObsError as e:
            log.error("OBS 시작 실패: %s (start_stream=false 면 정상)", e)

        # 3) 코어 연결 + 채팅 파이프라인
        self.memory.start_session()
        try:
            await bridge.connect()
        except Exception as e:
            log.error("Open-LLM-VTuber 코어 연결 실패: %s — 이번 사이클 중단", e)
            await self._teardown(obs, bridge, None, None, None, start_dt,
                                 transcript=transcript, aborted=True)
            return

        def on_chat(msg):
            self.memory.note_chat(msg)
            if transcript is not None:
                transcript.log_chat(msg)

        pipeline = ChatPipeline(bridge, cfg.broadcast, on_message=on_chat)

        # 코어가 보내오는 메시지(자막·오디오·control 등)를 계속 읽는다.
        # 안 읽으면 websockets 수신 버퍼가 무한정 쌓여 장시간 방송에서
        # 메모리 누수/정지가 난다(24h 안정성의 핵심). 읽으면서:
        #  - AI 실제 발화는 트랜스크립트에 (사고발언 점검)
        #  - 말 시작/끝 신호는 파이프라인에 ('입 하나' 모델의 눈)
        def on_core(data):
            if transcript is not None:
                transcript.on_core_message(data)
            pipeline.on_core_message(data)

        drain_task = asyncio.create_task(self._drain_core(bridge, on_core))

        try:
            source = make_chat_source(cfg)
            pipeline_task = asyncio.create_task(pipeline.run(source, chat_stop))
        except Exception as e:
            log.error("채팅 소스 시작 실패: %s — 채팅 없이 진행", e)

        # 게임(8단계, 선택): 사이드카 이벤트 → AI 반응. 채팅 소통은 그대로.
        if cfg.game.enabled:
            from .game import MinecraftFeed
            def on_game_event(data):
                self.memory.record_event("game", **data)
                if transcript is not None:
                    transcript.log_event("game", **data)
            feed = MinecraftFeed(bridge, cfg.game, on_event=on_game_event)
            game_task = asyncio.create_task(feed.run(chat_stop))
            log.info("게임 연동 켜짐 (%s)", cfg.game.ws_url)

        # 방송 오프닝(4-1): 켜지면 여는 인사로 문을 연다
        if cfg.broadcast.opening_greeting:
            await self._safe(bridge.say_to_ai(_CUE_OPENING))

        # 4) 종료 판단 루프
        ej = EndJudge(cfg.end_judge, start_dt)
        log.info("예정 종료: %s (%s)", ej.planned_end.isoformat(), ej.planned_trigger)
        pre_notified = False
        while not self._stop.is_set():
            now = _now(cfg.scheduler.timezone)
            last_chat = pipeline.last_chat_time if pipeline else None
            decision = ej.evaluate(now, last_chat)
            if decision.phase is Phase.END:
                log.info("종료 판단: %s", decision.detail)
                # 눈치껏: 종료 시각이 와도 말 중간·밀린 채팅·방금 온 후원
                # 중엔 안 끊고, 지금 하던 걸 끝낸 자연스러운 틈에 마무리로
                # 넘어간다(채팅 소강을 기다리는 게 아님).
                await self._wait_for_natural_break(pipeline, cfg.end_judge.wind_down)
                break
            if decision.phase is Phase.PRE_NOTICE and not pre_notified:
                pre_notified = True
                if cfg.end_judge.wind_down.enabled:
                    log.info("마무리 예고 단계 진입")
                    await self._safe(bridge.say_to_ai(_CUE_WIND_DOWN))
            await self._sleep_or_stop(5)

        # 5) 마무리 인사 → (여운 두고) 종료
        if cfg.end_judge.wind_down.enabled and cfg.end_judge.wind_down.closing_greeting:
            await self._safe(bridge.say_to_ai(_CUE_CLOSING))
            await self._sleep_or_stop(cfg.end_judge.wind_down.closing_wait_sec)

        await self._teardown(obs, bridge, pipeline, pipeline_task, chat_stop,
                             start_dt, drain_task=drain_task,
                             transcript=transcript, game_task=game_task)

    async def _teardown(self, obs, bridge, pipeline, pipeline_task, chat_stop,
                        start_dt, drain_task=None, transcript=None,
                        game_task=None, aborted: bool = False):
        # 채팅 파이프라인 정지 (취소 후 반드시 회수해서 태스크 누수 방지)
        if chat_stop is not None:
            chat_stop.set()
        if pipeline_task is not None:
            try:
                # shield 로 감싸 타임아웃이 pipeline_task 를 대신 취소하지 않게 하고,
                # 우리가 명시적으로 취소한다.
                await asyncio.wait_for(asyncio.shield(pipeline_task), timeout=10)
            except asyncio.TimeoutError:
                pipeline_task.cancel()
            except Exception:  # pipeline_task 내부 예외는 무시(로그는 내부에서)
                pass
            await asyncio.gather(pipeline_task, return_exceptions=True)

        # 게임 피드 정지 (chat_stop 공유 — 취소 후 회수)
        if game_task is not None:
            game_task.cancel()
            await asyncio.gather(game_task, return_exceptions=True)

        # 코어 수신 드레인 정지
        if drain_task is not None:
            drain_task.cancel()
            await asyncio.gather(drain_task, return_exceptions=True)

        # OBS 종료
        try:
            obs.stop_stream()
        except ObsError as e:
            log.error("OBS 종료 실패: %s", e)
        obs.close()

        # 코어 연결 종료
        await bridge.close()

        # 트랜스크립트 마감
        transcript_path = None
        if transcript is not None:
            transcript_path = transcript.path
            transcript.close()

        # 세션 기억 저장
        self.memory.end_session()

        # 방송 후 리포트(다시보기 학습) — 실패해도 조용히 넘어감
        if not aborted and self.cfg.logging.auto_report:
            try:
                generate_report(
                    self.memory, self.cfg.logging.reports_dir,
                    transcript_path=transcript_path,
                    next_stream=self._next_stream_hint(),
                )
            except Exception:
                log.exception("리포트 생성 실패(방송에는 영향 없음)")

        # 종료 후 컨텐츠 제작(2-2⑦): 하이라이트 후보·제목 초안
        if not aborted and self.cfg.logging.auto_content:
            try:
                from .content import generate_content_pack
                generate_content_pack(
                    self.persona, transcript_path,
                    self.cfg.logging.content_dir, llm=self.llm,
                )
            except Exception:
                log.exception("컨텐츠 팩 생성 실패(방송에는 영향 없음)")

        if not aborted:
            end_dt = _now(self.cfg.scheduler.timezone)
            await self._announce("end", end_dt)
        log.info("=== 방송 종료 ===")

    # --------------------------------------------------------------- 공지
    async def _announce(self, kind: str, now: datetime):
        cfg = self.cfg.announce
        if kind == "start" and not cfg.on_start:
            return
        if kind == "end" and not cfg.on_end:
            return
        if not should_post(now, cfg):
            return
        ctx = AnnounceContext(
            kind=kind,
            link=cfg.link,
            recent_note=self.memory.recent_summary() if kind == "start" else "",
            next_stream_hint=self._next_stream_hint() if kind == "end" else "",
        )
        text = compose(self.persona, ctx, cfg, llm=self.llm, now=now,
                       history_path=Path(self.cfg.memory.path) / "announce_history.json")
        log.info("[공지/%s] %s", kind, text.replace("\n", " "))

        announcers = self._announcers()
        for a in announcers:
            try:
                await a.post(text, title=("방송 시작" if kind == "start" else "방송 종료"))
            except Exception as e:
                log.error("공지 게시 실패(%s): %s", a.name, e)
            finally:
                await a.close()

    def _announcers(self):
        cfg = self.cfg.announce
        out = []
        if cfg.discord.enabled:
            out.append(DiscordAnnouncer(cfg.discord, self.cfg.secrets.discord_bot_token))
        if cfg.naver_cafe.enabled:
            out.append(NaverCafeAnnouncer(cfg.naver_cafe, self.cfg.secrets))
        return out

    def _next_stream_hint(self) -> str:
        now = _now(self.cfg.scheduler.timezone)
        nxt = self.scheduler.next_slot(now)
        if nxt is None:
            return ""
        days = ["월", "화", "수", "목", "금", "토", "일"]
        return f"다음엔 {days[nxt.weekday()]}요일 {nxt.strftime('%H:%M')}에"

    async def _wait_for_natural_break(self, pipeline, wd):
        """눈치껏 종료: 지금 하던 말/반응이 끝난 '숨 고르는 틈'을 기다린다.

        - 말하는 중이거나(is_speaking) 밀린 채팅이 있으면(has_pending) 안 끊고
          그것부터 끝내게 둔다.
        - 그 틈은 채팅이 바빠도 계속 생긴다(발화가 끝나는 순간마다). 채팅이
          '조용해지길' 기다리는 게 아니다.
        - end_grace_minutes 는 안전 상한(그 안에 틈을 못 잡아도 마무리 진행).
        """
        if pipeline is None or not wd.enabled:
            return
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max(0, wd.end_grace_minutes) * 60
        while not self._stop.is_set():
            if not pipeline.is_speaking() and not pipeline.has_pending():
                log.info("자연스러운 틈 포착 → 마무리로 넘어감")
                return
            if loop.time() >= deadline:
                log.info("틈을 못 잡음(+%d분) → 마무리 진행", wd.end_grace_minutes)
                return
            await self._sleep_or_stop(1)

    # --------------------------------------------------------------- 유틸
    async def _sleep_or_stop(self, seconds: float):
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _safe(self, coro):
        try:
            await coro
        except Exception as e:
            log.debug("코어 신호 전송 실패(무시): %s", e)

    async def _drain_core(self, bridge, on_message=None):
        """코어가 보내는 메시지를 계속 읽는다(수신 버퍼 누적 방지).

        on_message 가 있으면 각 메시지를 넘긴다 — 트랜스크립트가 AI 실제
        발화(type=audio 의 display_text)를 여기서 잡아 기록한다.
        """
        try:
            await bridge.recv_loop(on_message=on_message)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # 연결 종료 등은 정상 흐름
            log.debug("코어 수신 루프 종료: %s", e)
