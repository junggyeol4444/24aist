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
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

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
from .safety import StopFlag, check_output, strip_expressions
from .scheduler import Scheduler
from .transcript import Transcript
from .vtuber_bridge import VTuberBridge

log = logging.getLogger("aist.orchestrator")

# 송출 시작 직후 첫 확인까지 두는 여유(초).
_OBS_FIRST_CHECK_SEC = 15.0

# 공지 하나에 방송을 붙잡아 두지 않는다. 재시도(최대 3회)와
# 셀레늄 브라우저 기동까지 감안한 넉넉한 상한이다.
_ANNOUNCE_TIMEOUT_SEC = 120.0

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
        self._core_mute = False
        self._web_refreshes = 0
        self._bg: set = set()
        self._core_brain_dead = ""
        self._next_obs_check = 0.0
        self._obs_restarts = 0
        self._obs_unreachable = 0
        self._chat_source = None
        self._chat_restarts = 0
        self._chat_gave_up = False
        self._banned_interrupted = False
        self._banned_hits = 0
        self._banned_gave_up = False
        self._obs_start_failed = ""

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
            # 사고로 일찍 끝나면 같은 슬롯을 다시 해본다. 예전에는 한 번
            # 죽으면 그 날 방송이 통째로 날아갔다 — 19시에 켜서 19시 2분에
            # 인터넷이 잠깐 끊기면, 운영자가 자는 사이 2분짜리 방송만 남고
            # 다음 방송은 내일이었다. 무인 운영에서는 그게 정상일 수 없다.
            left = max(0, self.cfg.scheduler.retry_max)
            skip_announce = pre_announced
            resuming = False
            while not self._stop.is_set():
                try:
                    result = await self._run_broadcast(
                        skip_start_announce=skip_announce, retries_left=left,
                        resuming=resuming)
                except Exception:
                    log.exception("방송 사이클 중 오류 — 루프는 계속 유지")
                    break
                if result != "retry" or left <= 0:
                    break
                left -= 1
                skip_announce = True      # 시작 공지는 이미 나갔다
                resuming = True           # 같은 방송을 이어서 켜는 것이다
                log.warning("방송이 사고로 일찍 끝났습니다 — %.0f초 뒤 같은 슬롯을 "
                            "다시 켭니다(남은 재시도 %d회).",
                            self.cfg.scheduler.retry_backoff_sec, left)
                await self._sleep_or_stop(self.cfg.scheduler.retry_backoff_sec)

    async def run_one_now(self):
        """지금 한 방송만 진행(시작 수동). 끄는 건 종료 판단이 한다."""
        await self._run_broadcast()

    # ------------------------------------------------------------ 한 사이클
    async def _run_broadcast(self, skip_start_announce: bool = False,
                            retries_left: int = 0,
                            resuming: bool = False) -> str:
        """방송 한 사이클. 어떤 경로로 빠져나가든 뒷정리는 반드시 돈다.

        돌려주는 값: "normal"(정상 종료) | "aborted"(시작도 못 함) |
        "retry"(사고로 일찍 끝났고 같은 슬롯을 다시 해볼 만함).

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
        ej = None
        core_gone = False
        self._core_lost = False
        self._chat_source_dead = False
        self._core_mute = False
        self._web_refreshes = 0
        self._core_brain_dead = ""
        self._next_obs_check = 0.0
        self._obs_restarts = 0
        self._obs_unreachable = 0
        self._chat_source = None
        self._chat_restarts = 0
        self._chat_gave_up = False
        # 금지어 누적도 방송마다 새로 센다 — 어제 걸린 게
        # 오늘 방송을 내리면 안 된다.
        self._banned_hits = 0
        self._banned_gave_up = False
        self._obs_start_failed = ""
        self._banned_interrupted = False
        # 이전 방송이 남긴 중단 스위치가 있으면 지우고 시작한다(안 지우면
        # 다음 방송이 켜지자마자 다시 꺼진다).
        self.stop_flag.clear()

        # 트랜스크립트(사고발언 점검·다시보기 학습용). 실패해도 방송은 진행.
        transcript = None
        self._transcript = None
        if cfg.logging.transcript:
            try:
                transcript = Transcript(str(Path(cfg.logging.dir) / "transcripts"))
                transcript.open_session(start_dt)
                self._transcript = transcript
            except Exception as e:
                log.warning("트랜스크립트 시작 실패(기록 없이 진행): %s", e)
                transcript = None

        try:
            # 1) 시작 공지 (실패해도 방송은 진행). 사전 공지 했으면 중복 방지.
            if not skip_start_announce:
                await self._announce("start", start_dt)

            # 2) OBS 시작
            #
            # 송출도 안 하고 OBS 를 켜지도 않는 설정(리허설·테스트 단계)이면
            # 애초에 붙지 않는다. 예전에는 무조건 붙어보고 실패해서, "OBS 를
            # 건드리지 않는다"고 적힌 리허설 첫 화면에 빨간 ERROR 가 떴다 —
            # 처음 켜보는 운영자는 뭐가 크게 망가진 줄 안다.
            if not cfg.obs.start_stream and not cfg.obs.launch_if_not_running:
                log.info("obs.start_stream=false → OBS 에 붙지 않습니다"
                         "(송출은 운영자 수동).")
            else:
                try:
                    obs.connect()
                    obs.start_stream()
                except ObsError as e:
                    log.error("OBS 시작 실패: %s", e)
                    self._obs_start_failed = str(e)[:200]
            # 송출 감시의 첫 확인은 조금 뒤에 한다. StartStream 이 돌아와도
            # OBS 가 실제로 '송출 중'으로 바뀌는 데는 몇 초가 걸린다 —
            # 곧바로 물어보면 멀쩡한 방송을 '내려갔다'고 오해한다.
            self._next_obs_check = time.monotonic() + max(
                cfg.obs.stream_check_sec, _OBS_FIRST_CHECK_SEC)

            # 3) 코어 연결 + 채팅 파이프라인
            # 같은 슬롯을 다시 켜는 중이면 회차를 새로 열지 않는다
            # (한 방송이 회차 여러 개로 쪼개지면 단골 집계·"저번에~"·
            #  리포트가 전부 어긋난다).
            self.memory.start_session(resume=resuming)
            if self._obs_start_failed:
                # 송출이 안 켜진 채로 도는 방송이다. 감시가 몇 분 뒤
                # 내리긴 하지만, 근본 원인은 이 한 줄이다.
                self._event("obs_start_failed", why=self._obs_start_failed)
            try:
                await bridge.connect()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("Open-LLM-VTuber 코어 연결 실패: %s — 이번 사이클 중단", e)
                aborted = True
                return

            def on_chat(msg):
                # 채팅이 실제로 들어왔다 = 정말로 복구된 것이다.
                # (소스를 만든 것만으로 '복구됨' 이라고 하면 안 된다)
                self._chat_restarts = 0
                # 게임 서버에서 떠든 사람은 방송 시청자가 아니다.
                # 시청자 수·단골 집계에 섞으면 리포트가 거짓말이 된다.
                if not getattr(msg, "from_game", False):
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
                self._event("chat_lost")

            def on_core_mute():
                self._event("core_mute")
                # 코어는 붙어 있는데 말이 시청자에게 안 나가는 상태
                # (웹UI/OBS 브라우저 소스 미접속). 재연결로는 안 고쳐진다.
                self._core_mute = True

            def on_core_stuck(streak):
                # 말 끝 신호가 안 온다 = 웹UI(OBS 브라우저 소스)가 코어에서
                # 떨어져 있을 가능성이 크다. 코어를 껐다 켜면(업데이트·크래시)
                # 우리는 다시 붙지만 브라우저 소스는 끊긴 채 남을 수 있다.
                # 로그로 "새로고침하세요" 라고 부탁만 하는 건 무인 운영에서
                # 아무 소용이 없다 — 볼 사람이 없다. 직접 누른다.
                self._event("core_stuck", streak=streak)
                if streak == 1 or streak % 3 == 0:
                    # 태스크 참조를 안 들고 있으면 도중에 수거될 수 있다.
                    t = asyncio.create_task(self._refresh_web_ui(obs))
                    self._bg.add(t)
                    t.add_done_callback(self._bg.discard)

            def on_core_brain_dead(text):
                # 방송인이 LLM 오류 문구(영어)를 계속 읽고 있는 상태.
                self._core_brain_dead = text
                self._event("core_brain_dead", text=str(text)[:200])

            def on_tts_silent():
                # 자막만 나가고 목소리가 없는 상태. 방송을 내리지는 않는다
                # (일부러 자막만 쓰는 운영자도 있다). 대신 리포트에 남겨
                # 운영자가 방송 뒤에 반드시 보게 한다.
                self._event("tts_silent")

            pipeline = ChatPipeline(bridge, cfg.broadcast, on_message=on_chat,
                                    safety=cfg.safety, on_send_error=on_send_error,
                                    on_source_ended=on_source_ended,
                                    on_core_mute=on_core_mute,
                                    on_core_stuck=on_core_stuck,
                                    on_core_brain_dead=on_core_brain_dead,
                                    on_tts_silent=on_tts_silent)

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
                self._chat_source = source
                pipeline_task = asyncio.create_task(pipeline.run(source, chat_stop))
            except Exception as e:
                # 여기로 오면 소스 객체조차 없다. 그래서 방송이 끝날 때
                # 하는 '한 번도 못 붙었나' 검사(소스를 보고 판단한다)에
                # 안 걸린다 — 리포트에는 "시청자 0명" 만 남고, 운영자는
                # 아무도 안 온 줄 안다. 여기서 직접 남긴다.
                log.error("채팅 소스 시작 실패: %s — 채팅 없이 진행", e)
                self._event("chat_never_connected", why=str(e)[:200])

            # 게임(8단계, 선택): 사이드카 이벤트 → AI 반응. 채팅 소통은 그대로.
            if cfg.game.enabled:
                from .game import MinecraftFeed
                def on_game_event(data):
                    self.memory.record_event("game", **data)
                    if transcript is not None:
                        transcript.log_event("game", **data)
                # 게임 안 채팅은 파이프라인을 통해 넣는다 — 안 그러면
                # 시청자 채팅과 경쟁하며 코어로 직행해서, 방송인이 게임
                # 채팅만 상대하고 시청자는 묻힌다(기획 1-2 위반).
                feed = MinecraftFeed(bridge, cfg.game, on_event=on_game_event,
                                     on_chat=pipeline.submit)
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
                # 코어는 살아 있는데 말이 밖으로 안 나가는 상태 —
                # 재연결로는 안 고쳐진다. 조용한 화면만 몇 시간 내보내느니
                # 내리고, 무인운영 재시작이 운영자에게 보이게 한다.
                # 방송인의 '두뇌'(LLM)가 죽어서 영어 오류 문구만 읽고 있다.
                # 시청자에게는 AI 가 갑자기 영어 에러를 읊는 사고로 보인다.
                if self._core_brain_dead:
                    log.error(
                        "방송인이 LLM 오류 문구만 반복해서 읽고 있습니다 — "
                        "LLM API 키·요금제·네트워크를 확인하세요 (코어가 읽은 문구: %s) "
                        "→ 이번 방송 종료", self._core_brain_dead)
                    core_gone = True
                    break
                # 송출(OBS)이 혼자 내려가 있지 않은지 본다. 스트림 키 오류나
                # 네트워크 문제로 OBS 는 실제로 송출을 혼자 끊는다 — 그러면
                # 방송인은 아무도 안 보는 데서 몇 시간을 떠든다.
                if not await self._check_stream_alive(obs):
                    core_gone = True
                    break
                if self._core_mute:
                    log.error(
                        "코어가 말을 해도 시청자에게 나가지 않는 상태입니다. "
                        "웹UI(OBS 브라우저 소스)가 코어에 붙어 있는지, 코어 설정의 "
                        "enable_proxy 가 켜져 있는지 확인하세요 → 이번 방송 종료")
                    core_gone = True
                    break
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
            if core_gone:
                # 마무리 인사도 못 하고 끝났다 = 시청자에게는 방송이 뚝
                # 끊긴 것으로 보인다. 리포트에 반드시 남는다.
                self._event("ended_early", why="코어/웹UI 문제로 방송을 내림")
            if not core_gone:
                chat_stop.set()
                if self._stop.is_set():
                    # 킬스위치(중단.bat)나 Ctrl+C 로 내려오는 길이다.
                    # 여기서 마무리 인사를 '시키기만' 하면 거짓말이 된다 —
                    # 기다리는 쪽(_wait_until_done_speaking)이 _stop 을 보고
                    # 곧장 돌아오므로, 인사 신호를 보낸 6밀리초 뒤에 스트림이
                    # 꺼진다(실측). 시청자에게는 한 마디도 안 나가고, 로그와
                    # 중단.bat 만 "마무리 인사" 라고 적혀 있었다.
                    # 킬스위치는 빠른 게 맞다(AI 가 사고 친 걸 내리는 용도).
                    # 그러니 인사는 건너뛰고, 건너뛴다고 말한다.
                    log.warning("중단 요청 → 마무리 인사 없이 바로 내립니다. "
                                "인사까지 하고 내리려면 방송이 예정 시간에 "
                                "스스로 끝나게 두세요.")
                    self._event("stopped_by_operator")
                elif (cfg.end_judge.wind_down.enabled
                        and cfg.end_judge.wind_down.closing_greeting):
                    log.info("채팅 유입 차단 → 마무리 인사")
                    await self._safe(bridge.say_to_ai(_CUE_CLOSING))
                    # 인사가 끝나기도 전에 스트림을 내리면 말이 잘린다.
                    # 끝난 걸 확인한 뒤에 여운을 준다(기획안 4-3).
                    await self._wait_until_done_speaking(
                        pipeline, cfg.end_judge.wind_down.closing_max_wait_sec)
                    await self._sleep_or_stop(cfg.end_judge.wind_down.closing_wait_sec)
        finally:
            # 사고로 일찍 끝났는데 아직 오늘 방송 시간이 한참 남았으면,
            # 같은 슬롯을 다시 해본다. 그때는 "오늘 방송 끝!" 공지를 내면
            # 안 된다 — 시청자는 끝난 줄 알고 나가고, 몇 분 뒤 다시 켜진다.
            will_retry = (core_gone and retries_left > 0 and not self._stop.is_set()
                          and ej is not None
                          and self._enough_time_left(ej))
            # Ctrl+C·예외·코어 유실 어느 경우에도 뒷정리는 반드시 돈다.
            # shield 로 감싸 취소 중에도 끝까지 돌게 한다.
            await asyncio.shield(self._teardown(
                obs, bridge, pipeline, pipeline_task, chat_stop,
                start_dt, drain_task=drain_task,
                transcript=transcript, game_task=game_task,
                aborted=aborted, will_retry=will_retry))
        if aborted:
            return "aborted"
        return "retry" if will_retry else "normal"

    def _enough_time_left(self, ej) -> bool:
        """다시 켜서 방송이라고 할 만한 시간이 남았는지.

        1분짜리 방송을 다시 켜는 건 시청자에게 더 이상하다.
        """
        left = (ej.planned_end - _now(self.cfg.scheduler.timezone)).total_seconds()
        return left >= max(600, self.cfg.scheduler.retry_min_left_min * 60)

    async def _teardown(self, obs, bridge, pipeline, pipeline_task, chat_stop,
                        start_dt, drain_task=None, transcript=None,
                        game_task=None, aborted: bool = False,
                        will_retry: bool = False):
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
                if getattr(transcript, "write_failed", False):
                    # 기록이 중간에 끊겼는데 리포트는 그 파일로 만들어진다.
                    # 그대로 두면 "AI 발화 수: 12" 같은 숫자가 방송 전체인
                    # 것처럼 보이고, '사고 발언 점검' 이 5%만 덮은 채
                    # 끝난다. 운영자는 그 사실을 알 방법이 없다.
                    self._event("transcript_lost")
                transcript.close()
            except Exception:
                log.exception("트랜스크립트 마감 실패(방송 종료는 계속)")

        # 채팅이 한 줄도 안 왔을 때, 그게 "아무도 안 왔다" 인지 "아예 못
        # 붙었다" 인지 구분해 준다. 운영자에게는 완전히 다른 얘기다 —
        # 전자는 기다리면 되고, 후자는 채널 ID·토큰을 고쳐야 한다.
        # (실제 실행에서 채널 ID 가 틀린 채 3분을 돌렸더니, 리포트에는
        #  "시청자 0명" 만 적혀 "아무도 안 왔네" 로 읽혔다)
        src = self._chat_source
        if src is not None and not getattr(src, "connected_once", True):
            why = getattr(src, "last_error", "") or "사유 미상"
            log.error("이번 방송 내내 채팅 플랫폼에 한 번도 못 붙었습니다 "
                      "— 시청자가 없었던 게 아니라 채팅이 아예 안 들어왔습니다. "
                      "채널 ID·토큰을 확인하세요. (마지막 사유: %s)", why[:300])
            self._event("chat_never_connected", why=why[:300])

        # 세션 기억 저장. 다시 켤 회차면 아직 닫지 않는다 — 같은 슬롯의
        # 재시도는 '같은 방송'이라, 여기서 닫으면 회차가 쪼개진다.
        if not will_retry:
            try:
                self.memory.end_session()
            except Exception:
                log.exception("세션 기억 저장 실패(방송 종료는 계속)")

        # 방송 후 리포트(다시보기 학습) — 실패해도 조용히 넘어감.
        # 다시 켤 회차면 만들지 않는다. 15초 만에 끝난 시도마다 리포트와
        # 컨텐츠 팩이 쌓이면, "하루 점검이 파일 하나로 끝나게" 한다는
        # 목적이 그대로 깨진다(실제로 한 슬롯에 리포트 3개가 생겼다).
        if not aborted and not will_retry and self.cfg.logging.auto_report:
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
        if not aborted and not will_retry and self.cfg.logging.auto_content:
            try:
                from .content import generate_content_pack
                await asyncio.to_thread(
                    generate_content_pack, self.persona, transcript_path,
                    self.cfg.logging.content_dir, llm=self.llm,
                )
            except Exception:
                log.exception("컨텐츠 팩 생성 실패(방송에는 영향 없음)")

        if not aborted and not will_retry:
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
            history_path=Path(self.cfg.memory.path) / "announce_history.json",
            banned=self.cfg.safety.banned_words)
        log.info("[공지/%s] %s", kind, text.replace("\n", " "))

        announcers = self._announcers()
        for a in announcers:
            try:
                # 공지 하나가 방송을 붙잡지 못하게 한다. 셀레늄으로 카페에
                # 올리는 경로는 브라우저를 띄우는데, 페이지가 안 열리면
                # 거기서 멎는다 — 시작 공지에서 멎으면 방송이 아예 안 켜진다.
                await asyncio.wait_for(
                    a.post(text,
                           title=("방송 시작" if kind == "start" else "방송 종료")),
                    timeout=_ANNOUNCE_TIMEOUT_SEC)
            except asyncio.TimeoutError:
                log.error("공지 게시가 %.0f초 안에 안 끝나 넘어갑니다(%s) — "
                          "이번 공지는 안 나갔습니다. 방송은 그대로 진행합니다.",
                          _ANNOUNCE_TIMEOUT_SEC, a.name)
                self._event("announce_failed", where=a.name, phase=kind,
                            why="시간 초과")
            except Exception as e:
                log.error("공지 게시 실패(%s): %s", a.name, e)
                self._event("announce_failed", where=a.name, phase=kind,
                            why=str(e)[:200])
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
            self._event("core_lost", why="수신 루프 종료")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 - 끊김 사유는 다양
            log.warning("코어 연결 끊김: %s", e)
            self._core_lost = True
            self._event("core_lost", why=str(e)[:200])

    async def _check_stream_alive(self, obs) -> bool:
        """송출이 살아 있는지 가끔 확인하고, 내려가 있으면 다시 켠다.

        방송을 계속해도 되면 True, 이번 방송을 내려야 하면 False.
        obs.start_stream=false(운영자가 손으로 켜는 단계)면 확인하지 않는다 —
        송출 관리가 우리 몫이 아니다.
        """
        oc = self.cfg.obs
        if not oc.start_stream or oc.stream_check_sec <= 0:
            return True
        now = time.monotonic()
        if now < self._next_obs_check:
            return True
        self._next_obs_check = now + oc.stream_check_sec
        try:
            state = await asyncio.to_thread(obs.stream_state)
        except Exception as e:  # noqa: BLE001 - 조회 실패는 치명적이지 않다
            log.debug("송출 상태 조회 실패(무시): %s", e)
            return True
        if state == "live":
            self._obs_restarts = 0
            self._obs_unreachable = 0
            return True
        if state == "unreachable":
            # OBS 가 아예 대답을 안 한다 = 프로그램이 죽었거나 꺼졌다.
            # 인코더가 없으니 송출도 확실히 끊겼다. 다시 붙어보고,
            # 계속 안 되면 내린다.
            self._obs_unreachable += 1
            if await asyncio.to_thread(obs.reconnect):
                log.warning("OBS 가 대답이 없어 다시 붙었습니다(%d번째).",
                            self._obs_unreachable)
                self._event("obs_reconnected", tries=self._obs_unreachable)
                self._obs_unreachable = 0
                return True
            if self._obs_unreachable >= max(1, oc.unreachable_max):
                self._event("obs_unreachable", tries=self._obs_unreachable)
                log.error("OBS 가 %d번 연속으로 대답이 없습니다 — 꺼졌거나 죽은 "
                          "것으로 봅니다. OBS 가 없으면 송출도 없습니다 "
                          "→ 이번 방송 종료", self._obs_unreachable)
                return False
            log.warning("OBS 가 대답이 없습니다(%d/%d) — 다시 붙는 중.",
                        self._obs_unreachable, oc.unreachable_max)
            return True
        if self._obs_restarts >= oc.stream_restart_max:
            self._event("obs_gave_up", restarts=self._obs_restarts)
            log.error("OBS 송출이 또 내려갔습니다(%d번 다시 켜봤습니다) — 스트림 키와 "
                      "인터넷 연결을 확인하세요. 아무도 안 보는 방송을 계속하지 "
                      "않습니다 → 이번 방송 종료", self._obs_restarts)
            return False
        self._obs_restarts += 1
        self._event("obs_down", restarts=self._obs_restarts)
        log.error("OBS 송출이 내려가 있습니다 — 다시 켭니다(%d/%d).",
                  self._obs_restarts, oc.stream_restart_max)
        try:
            await asyncio.to_thread(obs.start_stream)
        except ObsError as e:
            self._event("obs_restart_failed", why=str(e)[:200])
            log.error("송출 재시작 실패: %s → 이번 방송 종료", e)
            return False
        return True

    # 브라우저 소스를 무한정 새로고침하지 않는다. 몇 번 눌러도 안 붙으면
    # 원인이 다른 데(코어 설정 enable_proxy, 주소 오타) 있다는 뜻이고,
    # 그때는 화면만 계속 깜빡이게 된다.
    _WEB_REFRESH_MAX = 3

    def _event(self, kind: str, /, **data) -> None:
        """이번 방송에 일어난 일을 기억·트랜스크립트에 남긴다.

        로그 파일에만 적으면 아무도 안 본다. 운영자가 다음 날 실제로 펴보는
        건 리포트다(기획안 2-2 "하루 5~10분 점검"). 실제 실행에서 코어가
        죽었다 살아나고 5분 넘게 소리가 안 나간 방송인데, 리포트에는 그 말이
        한 줄도 없었다 — 운영자는 멀쩡히 끝난 줄 알게 된다.
        """
        try:
            self.memory.record_event(kind, **data)
        except Exception:  # noqa: BLE001 - 기록 실패가 방송을 깨면 안 된다
            log.debug("사고 기록 실패(%s)", kind, exc_info=True)
        tr = getattr(self, "_transcript", None)
        if tr is not None:
            try:
                tr.log_event(kind, **data)
            except Exception:  # noqa: BLE001
                log.debug("트랜스크립트 기록 실패(%s)", kind, exc_info=True)

    async def _refresh_web_ui(self, obs) -> None:
        """웹UI 가 코어에서 떨어진 것 같을 때 OBS 브라우저 소스를 새로고침한다."""
        if not obs.connected():
            # OBS 에 안 붙은 설정(운영자 수동 단계)이다. 파이프라인이 이미
            # "브라우저 화면이 떠 있는지 확인하세요" 라고 남겼다.
            return
        if self._web_refreshes >= self._WEB_REFRESH_MAX:
            return
        self._web_refreshes += 1
        where = urlsplit(self.cfg.vtuber.ws_url).netloc
        try:
            n = await asyncio.to_thread(obs.refresh_browser_sources, where)
        except Exception as e:  # noqa: BLE001 - OBS 가 그 사이 죽었을 수도 있다
            log.warning("브라우저 소스 새로고침을 못 했습니다: %s", e)
            return
        if n:
            log.warning("웹UI 가 코어에서 떨어진 것으로 보여 OBS 브라우저 소스 "
                        "%d개를 새로고침했습니다(%d/%d번째).",
                        n, self._web_refreshes, self._WEB_REFRESH_MAX)
            self._event("web_ui_refresh", sources=n)
        else:
            log.warning("웹UI 가 코어에서 떨어진 것 같은데, 주소에 %s 가 들어간 "
                        "OBS 브라우저 소스를 못 찾았습니다 — 브라우저 소스가 코어 "
                        "웹UI 를 가리키는지 확인하세요.", where)

    async def _recover_core(self, bridge) -> bool:
        """방송 중 끊긴 코어를 다시 붙인다. 살리면 True, 포기면 False.

        살아나면 수신 루프도 다시 띄워야 하는데, 그건 호출부가 아니라
        여기서 같이 처리하지 않는다 — 재연결 후에도 drain 이 필요하므로
        _run_broadcast 가 만든 drain_task 를 대신할 새 태스크를 만든다.
        """
        vt = self.cfg.vtuber
        if not vt.reconnect_during_broadcast:
            log.error("코어 연결이 끊겼고 방송 중 재연결이 꺼져 있습니다 → 방송 종료")
            self._event("core_gone", why="reconnect_during_broadcast=false")
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
                self._event("core_recovered", tries=i)
                return True
        log.error("코어 재연결 %d회 모두 실패 → 이번 방송을 정상 종료합니다. "
                  "(끊긴 채로 계속 송출하지 않습니다)", vt.reconnect_max_attempts)
        self._event("core_gone", tries=vt.reconnect_max_attempts)
        return False

    async def _restart_chat(self, cfg, pipeline, pipeline_task, chat_stop):
        """끊긴 채팅 소스를 새로 만들어 파이프라인을 다시 돌린다.

        코어와 달리 채팅이 없어도 방송 자체는 굴러간다(혼잣말). 그래서
        실패해도 방송을 내리지 않는다. 대신 조용히 두지 않는다 —
        채팅 없는 방송은 이 기획의 핵심이 빠진 상태다.

        다만 '다시 붙여본다'를 몇 초마다 영원히 하면 안 된다. 플랫폼이
        점검 중이거나 채널 ID 가 틀리면 소스는 만들어지자마자 죽고, 그
        자리가 8초마다 도는 무한 루프가 된다(실제 실행에서 90초에 로그
        49줄이 쌓였다). 간격을 늘리고 로그는 줄인다.
        """
        if pipeline_task is not None:
            pipeline_task.cancel()
            await asyncio.gather(pipeline_task, return_exceptions=True)

        # 재시도해도 안 고쳐지는 이유(패키지 미설치 등)로 죽었으면 그만둔다.
        dead = getattr(self._chat_source, "fatal", "")
        if dead:
            if not self._chat_gave_up:
                self._chat_gave_up = True
                self._event("chat_gave_up", why=str(dead)[:200])
                log.error("채팅을 살릴 수 없습니다: %s 방송은 혼잣말로 "
                          "계속합니다.", dead)
            return None

        self._chat_restarts += 1
        wait = min(60.0, 3.0 * (2 ** (self._chat_restarts - 1)))
        if self._chat_restarts in (1, 3, 10) or self._chat_restarts % 20 == 0:
            log.error("채팅 연결이 끊겼습니다 — %.0f초 뒤 다시 붙여봅니다"
                      "(%d번째).", wait, self._chat_restarts)
        await self._sleep_or_stop(wait)
        if self._stop.is_set():
            return None
        try:
            source = make_chat_source(cfg)
            self._chat_source = source
            # 여기서 "복구됨" 이라고 쓰면 안 된다 — 소스를 만들었을 뿐,
            # 채팅이 실제로 들어오는지는 아직 모른다. 실제로 못 붙는
            # 상태에서도 "복구됨" 이 8초마다 찍혔다.
            return asyncio.create_task(pipeline.run(source, chat_stop))
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
        if not banned:
            return
        if data.get("type") == "control":
            if data.get("text") == "conversation-chain-start":
                # 새 발화가 시작됐다 — 끼어들기는 이 발화에 대해 다시 한 번만.
                self._banned_interrupted = False
            return
        if data.get("type") != "audio":
            return
        dt = data.get("display_text") or {}
        text = strip_expressions((dt.get("text") if isinstance(dt, dict) else "") or "")
        hit = check_output(text, banned)
        if not hit:
            return
        log.error("금지어 감지(%r) — 발화를 끊습니다: %s", hit, (text or "")[:120])
        # 트랜스크립트에만 적으면 리포트에는 한 줄도 안 남는다. 실제로
        # 돌려보니 발화 4개가 전부 금지어였는데, 다음 날 리포트에는 그
        # 얘기가 없었다 — '사고 발언 점검' 리포트가 정작 사고를 빠뜨린다.
        self._banned_hits += 1
        try:
            self.memory.record_event("banned_word", word=hit,
                                     text=(text or "")[:200])
        except Exception:  # noqa: BLE001 - 기록 실패가 방송을 깨면 안 된다
            log.debug("금지어 기억 기록 실패", exc_info=True)
        if transcript is not None:
            try:
                transcript.log_event("banned_word", word=hit, text=text)
            except Exception:
                log.debug("금지어 기록 실패", exc_info=True)
        # 지금 나가는 말을 즉시 끊는다 — 한 발화에 한 번만.
        #
        # 발화 하나는 문장 단위로 쪼개져서 여러 번 온다. 문장마다 끼어들기를
        # 보내면 코어에는 신호가 세 번 가는데, 첫 번째가 그 대화를 끊는
        # 순간 큐가 풀려 '다음 채팅'이 시작된다. 그러면 남은 두 번이 그
        # 멀쩡한 다음 채팅을 취소한다 — 시청자 채팅 하나가 아무 이유 없이
        # 사라진다(실제 코어 로그에서 그렇게 취소되는 것을 확인했다).
        if self._banned_interrupted:
            return
        self._banned_interrupted = True
        try:
            asyncio.get_running_loop().create_task(self._safe(bridge.interrupt()))
        except RuntimeError:  # 루프 밖에서 불린 경우(테스트 등)
            log.debug("끼어들기 예약 실패(이벤트 루프 없음)")
        if self.cfg.safety.stop_broadcast_on_hit:
            log.error("safety.stop_broadcast_on_hit=true → 방송을 내립니다.")
            self.request_stop()
            return
        # 한 번은 오탐일 수 있다. 하지만 계속 걸리는 건 방송인이 그 상태가
        # 된 것이고, 끼어들기는 이미 나간 말을 되돌리지 못한다.
        limit = self.cfg.safety.banned_max_strikes
        if limit > 0 and self._banned_hits >= limit and not self._banned_gave_up:
            self._banned_gave_up = True
            log.error("금지어가 %d번 걸렸습니다 — 발화만 끊으며 계속하는 건 "
                      "여기까지입니다. 이번 방송을 내립니다. "
                      "(계속 진행하려면 safety.banned_max_strikes 를 0 으로)",
                      self._banned_hits)
            self._event("banned_gave_up", hits=self._banned_hits)
            self.request_stop()
