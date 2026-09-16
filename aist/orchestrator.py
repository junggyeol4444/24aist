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
from datetime import datetime, timedelta
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
from .safety import StopFlag, check_output
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


_tz_warned = set()


def _now(tz_name: str) -> datetime:
    """설정한 타임존의 현재 시각. 실패하면 로컬 시간으로 떨어진다.

    조용히 떨어지면 안 된다 — 윈도우에는 시스템 타임존 DB 가 없어서
    tzdata 패키지가 없으면 항상 여기로 온다. 그러면 config 의 timezone
    설정이 통째로 무시된 채 PC 로컬 시간으로 방송 시각이 계산된다.
    PC 시간대가 다르면 방송이 몇 시간씩 어긋난다.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name))
    except Exception as e:  # noqa: BLE001 - tz 미지원/오타/DB 없음
        if tz_name not in _tz_warned:
            _tz_warned.add(tz_name)
            log.error("타임존 '%s' 을 쓸 수 없어 PC 로컬 시간으로 계산합니다 "
                      "— 방송 시각이 어긋날 수 있습니다: %s", tz_name, e)
        return datetime.now().astimezone()


class Orchestrator:
    def __init__(self, cfg: Config, persona: Persona):
        self.cfg = cfg
        self.persona = persona
        self.scheduler = Scheduler(cfg.scheduler)
        self.memory = Memory(cfg.memory)
        self.llm = LLMClient(cfg.llm, cfg.secrets)
        self._stop = asyncio.Event()
        self.stop_flag = StopFlag(cfg.safety.stop_flag_path)
        # 방송 한 사이클 안에서만 쓰는 상태
        self._core_lost = False
        self._chat_source_dead = False

    def request_stop(self):
        self._stop.set()

    def _check_stop_flag(self) -> bool:
        """`aist stop` 이 남긴 중단 스위치를 확인한다(무인 상태의 킬스위치)."""
        if not self.stop_flag.raised():
            return False
        log.warning("중단 스위치 감지(%s): %s — 방송을 내립니다.",
                    self.stop_flag.path, self.stop_flag.reason() or "사유 없음")
        self.request_stop()
        return True

    # ---------------------------------------------------------------- 자동
    async def run(self):
        """완전 자동 루프. 스케줄러가 켜고, 종료 판단이 끈다."""
        if not self.scheduler.enabled:
            log.warning("scheduler.enabled=false → 자동 시작 안 함. run_one_now() 를 쓰세요.")
            return
        log.info("오케스트레이터 시작 — 24시간 대기 모드")
        used_slot = None      # 이번 루프에서 이미 방송한 슬롯
        while not self._stop.is_set():
            now = _now(self.cfg.scheduler.timezone)
            if used_slot is not None and now <= used_slot:
                # 방금 끝낸 방송이 쓴 슬롯을 다시 집으면 같은 방송이 두 번
                # 나간다. 시작 변주(symmetric)로 슬롯보다 일찍 시작했거나,
                # 방송이 슬롯 시각 전에 끝난 경우(코어 유실 등)에 실제로
                # 일어난다. 그 슬롯은 지난 것으로 본다.
                now = used_slot + timedelta(seconds=1)
            slot = self.scheduler.next_slot(now)
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
            if lead_sec > 0 and self.cfg.announce.on_start and wait <= lead_sec:
                # 프로그램이 예고 시각을 지나 켜졌다(무인운영 재시작 등).
                # 사전 공지는 못 하고 시작 시점에 공지한다 — 조용히 넘어가면
                # 운영자는 "왜 미리 공지가 안 나갔지?" 만 남는다.
                log.info("사전 공지 시각(%d분 전)이 이미 지났습니다 "
                         "— 방송 시작 시점에 공지합니다.",
                         self.cfg.announce.pre_announce_minutes)
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
            # 절전/최대 절전에서 깨어났으면 지금이 예정 시각보다 한참 뒤일
            # 수 있다. 그대로 시작하면 새벽에 "저녁 방송" 이 나간다.
            grace = self.cfg.scheduler.late_start_grace_min
            late_min = (_now(self.cfg.scheduler.timezone)
                        - start_at).total_seconds() / 60.0
            if grace > 0 and late_min > grace:
                log.warning("예정 시각(%s)보다 %.0f분 늦었습니다 "
                            "(절전에서 깨어났을 수 있음) — 이번 방송은 건너뜁니다. "
                            "허용 지각은 scheduler.late_start_grace_min 으로 조정.",
                            start_at.isoformat(), late_min)
                used_slot = slot
                continue
            used_slot = slot
            try:
                await self._run_broadcast(skip_start_announce=pre_announced)
            except Exception:
                log.exception("방송 사이클 중 오류 — 루프는 계속 유지")

    async def run_one_now(self):
        """지금 한 방송만 진행(시작 수동). 끄는 건 종료 판단이 한다."""
        await self._run_broadcast()

    # ------------------------------------------------------------ 한 사이클
    async def _run_broadcast(self, skip_start_announce: bool = False):
        """방송 한 사이클. 어떤 경로로 빠져나가든 뒷정리는 반드시 돈다.

        뒷정리(_teardown)가 안 돌면 OBS 스트림이 켜진 채 남고 기록·기억이
        유실된다. 실제로 Ctrl+C 를 눌러보니 그 상태가 됐다. 그래서 OBS 를
        켜기 '전'부터 try/finally 로 감싼다 — 코어 연결을 기다리는 도중에
        멈춰도(연결 대기는 수십 초가 될 수 있다) 스트림이 남지 않게.
        """
        cfg = self.cfg
        start_dt = _now(cfg.scheduler.timezone)
        log.info("=== 방송 시작 (%s) ===", start_dt.isoformat())

        bridge = VTuberBridge(cfg.vtuber)
        obs = ObsController(cfg.obs)
        pipeline: Optional[ChatPipeline] = None
        chat_stop = asyncio.Event()
        pipeline_task: Optional[asyncio.Task] = None
        game_task: Optional[asyncio.Task] = None
        drain_task: Optional[asyncio.Task] = None
        aborted = False
        self._core_lost = False
        self._chat_source_dead = False
        # 이전 방송이 남긴 중단 스위치가 있으면 지우고 시작한다(안 지우면
        # 다음 방송이 켜지자마자 다시 꺼진다).
        self.stop_flag.clear()

        # 트랜스크립트(사고발언 점검·다시보기 학습용). 실패해도 방송은 진행.
        transcript = None
        if cfg.logging.transcript:
            try:
                transcript = Transcript(str(Path(cfg.logging.dir) / "transcripts"))
                transcript.open_session(start_dt)
            except Exception as e:
                log.warning("트랜스크립트 시작 실패(기록 없이 진행): %s", e)
                transcript = None

        try:
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
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("Open-LLM-VTuber 코어 연결 실패: %s — 이번 사이클 중단", e)
                aborted = True
                return

            def on_chat(msg):
                self.memory.note_chat(msg)
                if transcript is not None:
                    transcript.log_chat(msg)

            def on_send_error(_e):
                # 코어로 못 보냈다 = 연결이 끊겼을 가능성. 재연결 판단에 쓴다.
                self._core_lost = True

            def on_source_ended():
                # 채팅이 '안 오는 것'과 소스가 '죽은 것'은 다르다.
                # 전자는 정상(혼잣말로 끌고 감), 후자는 사고다.
                self._chat_source_dead = True

            pipeline = ChatPipeline(bridge, cfg.broadcast, on_message=on_chat,
                                    safety=cfg.safety, on_send_error=on_send_error,
                                    on_source_ended=on_source_ended)

            # 코어가 보내오는 메시지(자막·오디오·control 등)를 계속 읽는다.
            # 안 읽으면 websockets 수신 버퍼가 무한정 쌓여 장시간 방송에서
            # 메모리 누수/정지가 난다(24h 안정성의 핵심). 읽으면서:
            #  - AI 실제 발화는 트랜스크립트에 (사고발언 점검 + 금지어 감시)
            #  - 말 시작/끝 신호는 파이프라인에 ('입 하나' 모델의 눈)
            def on_core(data):
                if transcript is not None:
                    transcript.on_core_message(data)
                pipeline.on_core_message(data)
                self._watch_output(data, bridge, transcript)

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
            core_gone = False
            while not self._stop.is_set():
                # 운영자 킬스위치(`aist stop`) — 사람이 자리에 없어도 끌 수 있다.
                if self._check_stop_flag():
                    break
                # 코어가 죽었는지 확인하고, 살릴 수 있으면 살린다.
                # 못 살리면 이번 방송을 내린다(끊긴 채 무음으로 계속 송출되는
                # 것을 막는다. 프로세스가 끝나야 무인운영 재시작도 걸린다).
                if self._core_lost:
                    if await self._recover_core(bridge):
                        self._core_lost = False
                        # 끊기기 전 발화의 '말 끝' 신호는 옛 연결과 함께
                        # 사라졌다. 안 풀어주면 채팅이 계속 쌓이기만 한다.
                        if pipeline is not None:
                            pipeline.core_reconnected()
                        # 끊긴 수신 루프를 새로 띄운다(안 띄우면 재연결해도
                        # 말 시작/끝 신호를 못 받아 '입 하나' 모델이 멎는다).
                        if drain_task is not None:
                            drain_task.cancel()
                            await asyncio.gather(drain_task, return_exceptions=True)
                        drain_task = asyncio.create_task(self._drain_core(bridge, on_core))
                    else:
                        core_gone = True
                        break
                # 채팅 소스가 죽었으면 다시 붙인다. 채팅 없는 방송은 이 기획의
                # 핵심(1-2 "다 읽고 다 반응")이 통째로 빠진 상태다. 실패해도
                # 방송은 계속한다 — 혼잣말로는 굴러가고, 채팅은 언제든 살아날
                # 수 있다. 다만 조용히 두지 않고 로그로 알린다.
                if self._chat_source_dead:
                    self._chat_source_dead = False
                    pipeline_task = await self._restart_chat(
                        cfg, pipeline, pipeline_task, chat_stop)

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
            #
            # 인사보다 먼저 채팅 유입을 끊는다. 안 그러면 "오늘 고마웠어요~"
            # 하고 나서 새로 들어온 채팅에 계속 답하다가 뚝 끊긴다.
            # 기획안 4-3: "뚝 끄지 말고 예고 → 마무리 인사 → 종료".
            # 인사가 마지막이어야 한다.
            if not core_gone:
                chat_stop.set()
                if (cfg.end_judge.wind_down.enabled
                        and cfg.end_judge.wind_down.closing_greeting):
                    log.info("채팅 유입 차단 → 마무리 인사")
                    await self._safe(bridge.say_to_ai(_CUE_CLOSING))
                    # 인사가 끝나기도 전에 스트림을 내리면 말이 잘린다.
                    # 끝난 걸 확인한 뒤에 여운을 준다(기획안 4-3).
                    await self._wait_until_done_speaking(
                        pipeline, cfg.end_judge.wind_down.closing_max_wait_sec)
                    await self._sleep_or_stop(cfg.end_judge.wind_down.closing_wait_sec)
        finally:
            # Ctrl+C·예외·코어 유실 어느 경우에도 뒷정리는 반드시 돈다.
            # shield 로 감싸 취소 중에도 끝까지 돌게 한다.
            await asyncio.shield(self._teardown(
                obs, bridge, pipeline, pipeline_task, chat_stop,
                start_dt, drain_task=drain_task,
                transcript=transcript, game_task=game_task, aborted=aborted))

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

        # 트랜스크립트 마감 — 한 단계가 터져도 나머지 뒷정리는 계속해야 한다.
        # (여기서 예외가 올라가면 종료 공지까지 안 나간다. 디스크가 차면
        #  실제로 그랬다.)
        transcript_path = None
        if transcript is not None:
            try:
                transcript_path = transcript.path
                transcript.close()
            except Exception:
                log.exception("트랜스크립트 마감 실패(방송 종료는 계속)")

        # 세션 기억 저장
        try:
            self.memory.end_session()
        except Exception:
            log.exception("세션 기억 저장 실패(방송 종료는 계속)")

        # 방송 후 리포트(다시보기 학습) — 실패해도 조용히 넘어감
        if not aborted and self.cfg.logging.auto_report:
            try:
                generate_report(
                    self.memory, self.cfg.logging.reports_dir,
                    transcript_path=transcript_path,
                    next_stream=self._next_stream_hint(),
                    tz_name=self.cfg.scheduler.timezone,
                )
            except Exception:
                log.exception("리포트 생성 실패(방송에는 영향 없음)")

        # 종료 후 컨텐츠 제작(2-2⑦): 하이라이트 후보·제목 초안
        if not aborted and self.cfg.logging.auto_content:
            try:
                from .content import generate_content_pack
                await asyncio.to_thread(
                    generate_content_pack, self.persona, transcript_path,
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
            # 어느 공지가 안 나갔는지 남긴다. 시작 공지가 빠지면 시청자는
            # 방송이 켜진 걸 모른다 — 운영자가 알아야 설정을 판단한다.
            log.info("[공지/%s] 새벽 회피 시간대라 게시하지 않습니다 "
                     "(announce.avoid_late_night)", kind)
            return
        ctx = AnnounceContext(
            kind=kind,
            link=cfg.link,
            recent_note=self.memory.recent_summary() if kind == "start" else "",
            next_stream_hint=self._next_stream_hint() if kind == "end" else "",
        )
        # LLM 공지는 네트워크 호출이다. 그냥 await 없이 부르면 이벤트 루프가
        # 통째로 멈춰서 그동안 채팅도, 종료 판단도, 말 끝 신호도 안 돈다.
        text = await asyncio.to_thread(
            compose, self.persona, ctx, cfg, llm=self.llm, now=now,
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
        """종료 공지에 넣을 "다음엔 ~" 안내.

        요일만 말하면 틀린 정보가 된다. 주 1회 화요일 방송이면 화요일에
        끝내면서 "다음엔 화요일" 이라고 하는데, 시청자는 내일로 알아듣지만
        실제로는 일주일 뒤다. 그래서 며칠 뒤인지에 따라 말을 바꾼다.
        """
        now = _now(self.cfg.scheduler.timezone)
        nxt = self.scheduler.next_slot(now)
        if nxt is None:
            return ""
        days = ["월", "화", "수", "목", "금", "토", "일"]
        hhmm = nxt.strftime("%H:%M")
        gap = (nxt.date() - now.date()).days
        if gap <= 0:
            return f"다음엔 오늘 {hhmm}에"
        if gap == 1:
            return f"다음엔 내일 {hhmm}에"
        if gap < 7:
            return f"다음엔 {days[nxt.weekday()]}요일 {hhmm}에"
        if gap < 14:
            return f"다음엔 다음 주 {days[nxt.weekday()]}요일 {hhmm}에"
        return f"다음엔 {nxt.month}월 {nxt.day}일 {hhmm}에"

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

    async def _wait_until_done_speaking(self, pipeline, max_sec: float):
        """AI 가 지금 하는 말을 끝낼 때까지 기다린다(상한 있음).

        마무리 인사는 방송의 마지막 말이다. 고정 시간만 기다렸다가 스트림을
        내리면, 인사가 길어질 때 말이 중간에 잘린 채 화면이 꺼진다.
        끝 신호(chain-end)가 안 오는 경우(웹UI 미접속)를 대비해 상한을 둔다.
        """
        if pipeline is None or max_sec <= 0:
            return
        loop = asyncio.get_event_loop()
        deadline = loop.time() + max_sec
        started = False
        while not self._stop.is_set() and loop.time() < deadline:
            if pipeline.is_speaking():
                started = True
            elif started:
                log.info("마무리 인사 끝 — 여운 후 종료")
                return
            elif loop.time() > deadline - max_sec + 5:
                # 5초 안에 말이 시작도 안 했으면 더 기다릴 이유가 없다.
                return
            await self._sleep_or_stop(0.5)
        if started:
            log.info("마무리 인사가 %.0f초 안에 안 끝나 그대로 진행합니다.", max_sec)

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

        이 루프가 끝났다는 건 코어와의 연결이 끊겼다는 뜻이다. 예전에는
        debug 로그만 남기고 넘어갔는데, 그러면 방송인은 말을 못 하는데
        스트림만 계속 나가는 상태가 된다. 그래서 끊김을 표시한다.
        """
        try:
            await bridge.recv_loop(on_message=on_message)
            log.warning("코어 수신 루프가 끝났습니다 — 연결이 끊긴 것으로 봅니다.")
            self._core_lost = True
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 끊김 사유는 다양
            log.warning("코어 연결 끊김: %s", e)
            self._core_lost = True

    async def _recover_core(self, bridge) -> bool:
        """방송 중 끊긴 코어를 다시 붙인다. 살리면 True, 포기면 False.

        살아나면 수신 루프도 다시 띄워야 하는데, 그건 호출부가 아니라
        여기서 같이 처리하지 않는다 — 재연결 후에도 drain 이 필요하므로
        _run_broadcast 가 만든 drain_task 를 대신할 새 태스크를 만든다.
        """
        vt = self.cfg.vtuber
        if not vt.reconnect_during_broadcast:
            log.error("코어 연결이 끊겼고 방송 중 재연결이 꺼져 있습니다 → 방송 종료")
            return False
        for i in range(1, max(1, vt.reconnect_max_attempts) + 1):
            if self._stop.is_set():
                return False
            wait = vt.reconnect_backoff_sec * i
            log.info("코어 재연결 시도 %d/%d (%.0f초 후)",
                     i, vt.reconnect_max_attempts, wait)
            await self._sleep_or_stop(wait)
            if self._stop.is_set():
                return False
            if await bridge.reconnect_once():
                return True
        log.error("코어 재연결 %d회 모두 실패 → 이번 방송을 정상 종료합니다. "
                  "(끊긴 채로 계속 송출하지 않습니다)", vt.reconnect_max_attempts)
        return False

    async def _restart_chat(self, cfg, pipeline, pipeline_task, chat_stop):
        """끊긴 채팅 소스를 새로 만들어 파이프라인을 다시 돌린다.

        코어와 달리 채팅이 없어도 방송 자체는 굴러간다(혼잣말). 그래서
        실패해도 방송을 내리지 않는다. 대신 조용히 두지 않는다 —
        채팅 없는 방송은 이 기획의 핵심이 빠진 상태다.
        """
        log.error("채팅 연결이 끊겼습니다 — 다시 붙여봅니다.")
        if pipeline_task is not None:
            pipeline_task.cancel()
            await asyncio.gather(pipeline_task, return_exceptions=True)
        await self._sleep_or_stop(3)
        if self._stop.is_set():
            return None
        try:
            source = make_chat_source(cfg)
            task = asyncio.create_task(pipeline.run(source, chat_stop))
            log.info("채팅 연결 복구됨 (%s)", source.platform)
            return task
        except Exception as e:  # noqa: BLE001 - 플랫폼 사유 다양
            log.error("채팅 재연결 실패: %s — 채팅 없이 방송을 계속합니다"
                      "(혼잣말로 진행). 채팅이 필요하면 방송을 내리고 "
                      "플랫폼 설정을 확인하세요.", e)
            return None

    def _watch_output(self, data: dict, bridge, transcript) -> None:
        """AI 가 실제로 말한 문장을 운영자가 정한 금지어와 대조한다.

        기본값(빈 목록)에서는 아무 일도 하지 않는다 — 무엇이 문제인지는
        운영자가 방송을 보고 정한다(기획안 3-3/3-5).
        """
        banned = self.cfg.safety.banned_words
        if not banned or data.get("type") != "audio":
            return
        dt = data.get("display_text") or {}
        text = dt.get("text") if isinstance(dt, dict) else ""
        hit = check_output(text or "", banned)
        if not hit:
            return
        log.error("금지어 감지(%r) — 발화를 끊습니다: %s", hit, (text or "")[:120])
        if transcript is not None:
            try:
                transcript.log_event("banned_word", word=hit, text=text)
            except Exception:
                log.debug("금지어 기록 실패", exc_info=True)
        # 지금 나가는 말을 즉시 끊는다.
        try:
            asyncio.get_running_loop().create_task(self._safe(bridge.interrupt()))
        except RuntimeError:  # 루프 밖에서 불린 경우(테스트 등)
            log.debug("끼어들기 예약 실패(이벤트 루프 없음)")
        if self.cfg.safety.stop_broadcast_on_hit:
            log.error("safety.stop_broadcast_on_hit=true → 방송을 내립니다.")
            self.request_stop()
