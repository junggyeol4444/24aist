"""aist CLI — 운영자/Claude Code 가 쓰는 진입점.

서브커맨드:
  check            설정·페르소나·키 상태를 점검(네트워크 불필요)
  plan             다음 방송 일정 N개 + 한 방송 종료 타임라인 미리보기
  persona          페르소나 시스템 프롬프트(코어에 들어갈 텍스트) 출력
  announce-preview 시작/종료 공지 문구 미리보기
  build-persona    Open-LLM-VTuber 의 conf.yaml 에 페르소나/TTS/Live2D 주입(개조)
  broadcast-now    지금 한 방송만 진행(시작 수동, 종료 자동) — 3·4단계
  run              완전 자동 루프(스케줄러가 켜고 끔) — 5·7단계
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__


def _load_dotenv(path: str = ".env") -> None:
    """python-dotenv 없이 .env 를 os.environ 에 로드(있으면)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _find_default(candidates):
    for c in candidates:
        if Path(c).exists():
            return c
    return candidates[0]


def _setup_file_logging(log_cfg) -> None:
    """LoggingConfig 를 실제로 사용 — 회전 파일 로그(dir/aist.log)."""
    if not log_cfg.file_log:
        return
    from logging.handlers import RotatingFileHandler
    try:
        Path(log_cfg.dir).mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            Path(log_cfg.dir) / "aist.log",
            maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        # 중복 부착 방지(명령 여러 번 호출 시)
        if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            root.addHandler(handler)
    except OSError as e:
        logging.getLogger("aist").warning("파일 로그 설정 실패: %s", e)


def _load(args):
    from .config import load_config
    from .persona import Persona
    cfg = load_config(args.config)
    _setup_file_logging(cfg.logging)
    persona = Persona.load(args.persona) if Path(args.persona).exists() else Persona()
    return cfg, persona


# --------------------------------------------------------------- 커맨드들
def cmd_check(args) -> int:
    from .config import ConfigError
    try:
        cfg, persona = _load(args)
    except (ConfigError, FileNotFoundError) as e:
        print(f"[오류] {e}")
        return 1
    s = cfg.secrets
    actives = cfg.active_platforms()
    is_simulcast = len(actives) > 1
    print(f"aist {__version__} — 설정 점검\n")
    print(f"  플랫폼          : {', '.join(actives)}" + ("  (동출)" if is_simulcast else ""))
    print(f"  코어(VTuber)    : {cfg.vtuber.ws_url}")
    print(f"  OBS             : {cfg.obs.host}:{cfg.obs.port}  start_stream={cfg.obs.start_stream}")
    print(f"  스케줄러        : enabled={cfg.scheduler.enabled}  tz={cfg.scheduler.timezone}")
    print(f"  종료 판단       : max={cfg.end_judge.max_minutes}분 min={cfg.end_judge.min_minutes}분 "
          f"chat_low={cfg.end_judge.chat_low.enabled} jitter={cfg.end_judge.end_jitter_min}분")
    print(f"  채팅 방침       : 다반응={cfg.broadcast.respond_to_all_chat} "
          f"인위적딜레이={cfg.broadcast.artificial_delay_sec}s flood={cfg.broadcast.flood_handling.enabled}")
    print(f"  공지            : discord={cfg.announce.discord.enabled} "
          f"naver={cfg.announce.naver_cafe.enabled} style={cfg.announce.style} "
          f"새벽회피={cfg.announce.avoid_late_night}")
    print(f"  LLM(공지)       : {cfg.llm.provider} ({cfg.llm.model})")
    print(f"  페르소나        : {persona.name} / {persona.concept}")

    print("\n  키/토큰(.env) 상태:")
    def mark(v): return "OK" if v else "비어있음"
    print(f"    LLM            : openai={mark(s.openai_api_key)} anthropic={mark(s.anthropic_api_key)} gemini={mark(s.gemini_api_key)}")
    print(f"    OBS_PASSWORD   : {mark(cfg.obs.password)}")
    print(f"    DISCORD_TOKEN  : {mark(s.discord_bot_token)}")
    # 활성 플랫폼별 식별자 상태
    c = cfg.chat
    ids = {
        "twitch": ("channel", c.twitch.channel or s.twitch_channel),
        "youtube": ("video_id", c.youtube.video_id or s.youtube_video_id),
        "chzzk": ("channel_id", c.chzzk.channel_id or s.chzzk_channel_id),
        "soop": ("bj_id", c.soop.bj_id or s.soop_bj_id),
        "kick": ("channel", c.kick.channel or s.kick_channel),
        "twitcasting": ("user_id", c.twitcasting.user_id or s.twitcasting_user_id),
    }
    for p in actives:
        key, val = ids[p]
        extra = ""
        if p == "twitcasting":
            extra = f" token={mark(s.twitcasting_access_token)}"
        elif p == "twitch":
            extra = f" token={mark(s.twitch_oauth_token)}(없으면 익명)"
        print(f"    {p:<11}: {key}={mark(val)}{extra}")
    if cfg.announce.naver_cafe.enabled:
        print(f"    NAVER          : token={mark(s.naver_access_token)} refresh={mark(s.naver_refresh_token)}")
    # --- 실행 준비 상태 -------------------------------------------------
    # 설정이 맞아도 패키지가 없으면 방송은 시작하자마자 중단된다.
    # 여기서 걸러야 "점검 완료"가 거짓말이 되지 않는다.
    from . import preflight
    miss = preflight.missing(cfg)
    fe_ok, fe_msg = preflight.core_frontend_ready()
    conf_ok, conf_msg = preflight.core_conf_ready()
    deps_ok, deps_msg = preflight.core_deps_ready()
    blockers = [n for n in miss if n.blocking]

    print("\n  실행 준비 상태:")
    if not miss:
        print("    패키지         : 켜진 기능에 필요한 것 모두 설치됨")
    else:
        for n in miss:
            tag = "[X]" if n.blocking else "[!]"
            print(f"    {tag} {n.package:<22} 없음 → {n.feature}")
    print(f"    코어 웹UI      : {'OK' if fe_ok else '[X] ' + fe_msg}")
    print(f"    코어 conf.yaml : {'OK' if conf_ok else '[X] ' + conf_msg}")
    print(f"    코어 의존성    : {'OK (' + deps_msg + ')' if deps_ok else '[X] ' + deps_msg}")

    print()
    if blockers or not fe_ok or not conf_ok or not deps_ok:
        print("지금 상태로는 방송이 안 됩니다. 아래를 먼저 해결하세요:")
        if blockers:
            print(f"  - 패키지 설치: {preflight.install_hint(miss)}")
        if not fe_ok:
            print("  - 코어 웹UI 받기: ./scripts/fetch_frontend.sh"
                  "  (윈도우: windows\\프론트엔드받기.bat)")
        if not conf_ok:
            print("  - 코어 설정 만들기: bash scripts/setup_openllm_vtuber.sh")
        if not deps_ok:
            print("  - 코어 의존성 설치: cd Open-LLM-VTuber && uv sync"
                  "  (uv 없으면 pip install -r requirements.txt)")
        print("  ( 한 번에: ./run.sh setup  /  윈도우: windows\\설치.bat )")
        return 1
    if miss:
        print("방송은 가능하지만 일부 기능이 꺼진 채 돕니다([!] 항목).")
    print("점검 완료. (실제 연결 테스트는 doctor / broadcast-now 로)")
    return 0


def cmd_plan(args) -> int:
    from .scheduler import Scheduler
    from .end_judge import EndJudge, Phase
    cfg, _ = _load(args)
    tz = cfg.scheduler.timezone
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(tz))
    except Exception:
        now = datetime.now().astimezone()

    sc = Scheduler(cfg.scheduler)
    print(f"현재({tz}): {now.isoformat(timespec='minutes')}\n다음 방송 예정 {args.count}개:")
    cursor = now
    first_start = None
    for i in range(args.count):
        slot = sc.next_slot(cursor)
        if slot is None:
            print("  (앞으로 예정된 방송 없음)")
            break
        if first_start is None:
            first_start = slot
        print(f"  {i+1}. {slot.strftime('%Y-%m-%d (%a) %H:%M')}")
        cursor = slot + timedelta(minutes=1)

    if first_start is not None:
        print("\n해당 방송 종료 타임라인(설정 기준):")
        ej = EndJudge(cfg.end_judge, first_start)
        print(f"  시작        : {first_start.strftime('%H:%M')}")
        print(f"  최소 보장   : {ej.min_end.strftime('%H:%M')} (min={cfg.end_judge.min_minutes}분)")
        wd = cfg.end_judge.wind_down
        if wd.enabled and wd.pre_notice_minutes_before_end > 0:
            pre = ej.planned_end - timedelta(minutes=wd.pre_notice_minutes_before_end)
            print(f"  마무리 예고 : {pre.strftime('%H:%M')}")
        print(f"  예정 종료   : {ej.planned_end.strftime('%H:%M')} (사유: {ej.planned_trigger})")
    return 0


def cmd_persona(args) -> int:
    _, persona = _load(args)
    print(persona.render_system_prompt())
    return 0


def cmd_doctor(args) -> int:
    """실제 연결 점검 — 코어(Open-LLM-VTuber) WS / OBS 가 닿는지 확인.

    3단계에서 방송을 켜기 전에 배선을 점검하는 용도. 코어/OBS 가 안 떠
    있으면 그대로 알려준다(이것도 '되는 걸 확인'의 일부).
    """
    import asyncio as _asyncio
    cfg, _ = _load(args)
    print("연결 점검 (코어 WS / OBS)\n")
    ok = True

    # 연결을 시도하기 전에, 애초에 시도할 수 있는 상태인지부터 본다.
    from . import preflight
    miss = preflight.missing(cfg)
    if miss:
        for n in miss:
            print(f"  [{'X' if n.blocking else '!'}] {n.package} 미설치 → {n.feature}")
        print(f"      → {preflight.install_hint(miss)}\n")
        ok = ok and not any(n.blocking for n in miss)
    fe_ok, fe_msg = preflight.core_frontend_ready()
    if not fe_ok:
        ok = False
        print(f"  [X] 코어 웹UI: {fe_msg}\n")
    conf_ok, conf_msg = preflight.core_conf_ready()
    if not conf_ok:
        ok = False
        print(f"  [X] 코어 설정: {conf_msg}\n")
    deps_ok, deps_msg = preflight.core_deps_ready()
    if not deps_ok:
        ok = False
        print(f"  [X] 코어 의존성: {deps_msg}\n")

    # 1) 코어 WebSocket (점검은 빠르게 1회만 시도)
    cfg.vtuber.connect_timeout_sec = min(cfg.vtuber.connect_timeout_sec, 3)
    cfg.vtuber.reconnect = False

    async def _check_core():
        from .vtuber_bridge import VTuberBridge
        b = VTuberBridge(cfg.vtuber)
        await b.connect()
        await b._send({"type": "heartbeat"})
        await b.close()

    try:
        _asyncio.run(_check_core())
        print(f"  [OK] 코어 WS 연결됨 — {cfg.vtuber.ws_url}")
    except RuntimeError as e:
        ok = False
        print(f"  [!] 코어 점검 불가: {e}")
    except Exception as e:  # 연결 실패(코어 미실행 등)
        ok = False
        print(f"  [X] 코어 WS 연결 실패 ({cfg.vtuber.ws_url}): {e}")
        print("       → Open-LLM-VTuber 가 실행 중인지 확인 (uv run run_server.py)")

    # 2) OBS
    # obsws-python 이 연결 실패 시 자체 ERROR+traceback 를 찍어 시끄러우니 죽인다
    logging.getLogger("obsws_python").setLevel(logging.CRITICAL)
    try:
        from .obs_control import ObsController, ObsError
        obs = ObsController(cfg.obs)
        try:
            obs.connect()
            print(f"  [OK] OBS 연결됨 — {cfg.obs.host}:{cfg.obs.port}")
            obs.close()
        except ObsError as e:
            ok = False
            print(f"  [X] OBS 연결 실패: {e}")
            print("       → OBS 실행 + obs-websocket 켜짐 + 포트/비밀번호 확인")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"  [!] OBS 점검 불가: {e}")

    # 3) 채팅 플랫폼 (활성 플랫폼별 구성/도달 점검)
    from .chat.factory import make_single_source
    print("\n  채팅 플랫폼:")
    for p in cfg.active_platforms():
        try:
            src = make_single_source(p, cfg)
        except Exception as e:  # 식별자 미설정 등
            ok = False
            print(f"    [X] {p:<11}: 구성 실패 — {e}")
            continue

        async def _probe(s):
            return await asyncio.wait_for(s.probe(), timeout=8)

        try:
            status = _asyncio.run(_probe(src))
            print(f"    [OK] {p:<11}: {status}")
        except Exception as e:  # noqa: BLE001
            print(f"    [?] {p:<11}: 점검 불가(라이브 아님/네트워크?) — {e}")

    print("\n점검 끝.", "모두 OK." if ok else "위 항목을 확인하세요.")
    return 0 if ok else 1


def cmd_announce_preview(args) -> int:
    from .announce.composer import AnnounceContext, compose
    from .llm import LLMClient
    cfg, persona = _load(args)
    llm = LLMClient(cfg.llm, cfg.secrets)
    print(f"공지 미리보기 (style={cfg.announce.style}, llm={cfg.llm.provider}, 사용가능={llm.available()})\n")
    for kind in (("start", "end") if args.kind == "both" else (args.kind,)):
        for i in range(args.count):
            ctx = AnnounceContext(kind=kind, link=cfg.announce.link)
            text = compose(persona, ctx, cfg.announce, llm=llm)
            print(f"[{kind} #{i+1}] {text}")
        print()
    return 0


def cmd_build_persona(args) -> int:
    """Open-LLM-VTuber 의 conf.yaml 에 페르소나/TTS/Live2D 를 주입(개조)."""
    import yaml
    cfg, persona = _load(args)
    prompt = persona.render_system_prompt()

    target = Path(args.conf) if args.conf else None
    if target and target.exists():
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        cc = data.setdefault("character_config", {})
        cc["persona_prompt"] = prompt
        if args.live2d:
            cc["live2d_model_name"] = args.live2d
        # GPT-SoVITS 를 TTS 로 지정(한국어). 세부 ref_audio 는 운영자가 채움.
        tts = cc.setdefault("tts_config", {})
        tts["tts_model"] = "gpt_sovits_tts"
        # 시스템 host/port 를 우리 ws_url 과 일치시키지는 않음(운영자 환경 우선).
        backup = target.with_suffix(target.suffix + ".bak")
        backup.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
        target.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        print(f"개조 완료: {target}\n  - character_config.persona_prompt 주입")
        print(f"  - tts_config.tts_model = gpt_sovits_tts")
        if args.live2d:
            print(f"  - live2d_model_name = {args.live2d}")
        print(f"  (원본 백업: {backup})")
        print("  ※ GPT-SoVITS 의 ref_audio_path/api_url 은 conf.yaml 에서 직접 채우세요.")
    else:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(prompt, encoding="utf-8")
        print("conf.yaml 경로(--conf)가 없어 페르소나 프롬프트만 저장했습니다:")
        print(f"  {out}")
        print("\n아래 내용을 Open-LLM-VTuber conf.yaml 의 "
              "character_config.persona_prompt 에 넣으세요:\n")
        print("-" * 60)
        print(prompt)
        print("-" * 60)
    return 0


def cmd_report(args) -> int:
    """직전 방송 리포트 생성/재생성 — 다시보기 학습(운영자 점검용)."""
    from .memory import Memory
    from .report import generate_report
    cfg, _ = _load(args)
    memory = Memory(cfg.memory)
    # 가장 최근 트랜스크립트 파일을 자동으로 찾는다(있으면)
    tdir = Path(cfg.logging.dir) / "transcripts"
    latest = None
    if tdir.exists():
        files = sorted(tdir.glob("*.jsonl"))
        latest = files[-1] if files else None
    path = generate_report(memory, cfg.logging.reports_dir, transcript_path=latest)
    if path is None:
        print("기록된 방송 세션이 없습니다. (방송 후 다시 실행)")
        return 1
    print(f"리포트 생성됨: {path}")
    print(path.read_text(encoding='utf-8'))
    return 0


def cmd_content(args) -> int:
    """직전 방송의 컨텐츠 팩(하이라이트 후보·제목 초안) 생성/재생성."""
    from .content import generate_content_pack
    from .llm import LLMClient
    cfg, persona = _load(args)
    tdir = Path(cfg.logging.dir) / "transcripts"
    latest = None
    if tdir.exists():
        files = sorted(tdir.glob("*.jsonl"))
        latest = files[-1] if files else None
    path = generate_content_pack(persona, latest, cfg.logging.content_dir,
                                 llm=LLMClient(cfg.llm, cfg.secrets))
    if path is None:
        print("트랜스크립트가 없습니다. (방송 후 다시 실행)")
        return 1
    print(f"컨텐츠 팩 생성됨: {path}\n")
    print(path.read_text(encoding="utf-8"))
    return 0


def _gate(cfg, force: bool) -> bool:
    """방송을 시작하기 전에, 애초에 될 수 있는 상태인지 막아선다.

    없으면 orchestrator 가 사이클을 돌다가 조용히 중단되는데, 로그만 보면
    "돌긴 돌았다"로 보인다. 시작 전에 크게 말하고 세운다.
    """
    from . import preflight
    blockers = [n for n in preflight.missing(cfg) if n.blocking]
    if not blockers:
        return True
    print("방송을 시작할 수 없습니다 — 필요한 패키지가 없습니다:")
    for n in blockers:
        print(f"  [X] {n.package} → {n.feature}")
    print(f"\n  {preflight.install_hint(blockers)}")
    print("  ( 한 번에: ./run.sh setup  /  윈도우: windows\\설치.bat )")
    if force:
        print("\n--force 라서 그대로 진행합니다. 중간에 멈출 수 있습니다.")
        return True
    print("\n그래도 강행하려면 --force 를 붙이세요. 자세한 점검은 aist check.")
    return False


def cmd_broadcast_now(args) -> int:
    from .orchestrator import Orchestrator
    cfg, persona = _load(args)
    if not _gate(cfg, getattr(args, "force", False)):
        return 1
    orch = Orchestrator(cfg, persona)
    try:
        asyncio.run(orch.run_one_now())
    except KeyboardInterrupt:
        print("\n중단됨")
    return 0


def cmd_wait_core(args) -> int:
    """코어(Open-LLM-VTuber)가 뜰 때까지 기다린다.

    코어는 모델 로딩 때문에 뜨는 데 몇 분 걸리기도 한다. 고정 시간만
    기다렸다가 방송을 시작하면 연결에 실패하고 그 사이클을 통째로
    날린다(스케줄러면 다음 방송까지 대기). 그래서 실제로 붙을 때까지 본다.
    """
    import asyncio as _asyncio
    cfg, _ = _load(args)
    cfg.vtuber.connect_timeout_sec = min(cfg.vtuber.connect_timeout_sec, 3)
    cfg.vtuber.reconnect = False

    async def _try_once() -> bool:
        from .vtuber_bridge import VTuberBridge
        b = VTuberBridge(cfg.vtuber)
        try:
            await b.connect()
            await b.close()
            return True
        except Exception:
            return False

    import time
    deadline = time.monotonic() + args.timeout
    print(f"코어 대기 중 — {cfg.vtuber.ws_url} (최대 {args.timeout}초)")
    while True:
        if _asyncio.run(_try_once()):
            print("코어 떴습니다.")
            return 0
        if time.monotonic() >= deadline:
            print(f"[오류] {args.timeout}초 안에 코어가 뜨지 않았습니다.")
            print("       코어실행.bat / run.sh core 가 떠 있는지, 포트가 맞는지 확인하세요.")
            return 1
        time.sleep(2)


def cmd_rehearse(args) -> int:
    """플랫폼·키·OBS 없이 방송 흐름만 돌려본다.

    코어(Open-LLM-VTuber)만 떠 있으면 된다. 가짜 채팅을 흘려보내면서
    여는 인사 → 채팅 반응 → 혼잣말 → 마무리 인사가 실제로 도는지 본다.
    송출은 하지 않는다(OBS 를 건드리지 않고 공지도 보내지 않는다).
    """
    from .orchestrator import Orchestrator
    cfg, persona = _load(args)

    # 리허설은 '진짜로 나가는 것'을 전부 끈다. 실수로 송출/공지가 나가면 안 된다.
    cfg.platform = "rehearsal"
    cfg.platforms = []
    cfg.obs.start_stream = False
    cfg.obs.launch_if_not_running = False
    cfg.announce.discord.enabled = False
    cfg.announce.naver_cafe.enabled = False
    cfg.end_judge.min_minutes = 0
    cfg.end_judge.max_minutes = max(1, args.minutes)
    # 마무리 단계도 리허설 길이에 맞춰 줄인다. 실제 방송의 기본값(유예 5분,
    # 여운 45초)을 그대로 쓰면 1분 리허설이 7분 걸린다.
    cfg.end_judge.end_jitter_min = 0
    cfg.end_judge.wind_down.end_grace_minutes = 1
    cfg.end_judge.wind_down.closing_wait_sec = 10

    # 코어 연결만은 진짜여야 의미가 있다.
    from . import preflight
    if not preflight.Need("", "websockets", "websockets", "vtuber", True).installed:
        print("리허설도 코어 연결은 진짜로 합니다 — websockets 가 필요합니다.")
        print('  pip install -e ".[vtuber]"')
        return 1

    print(f"리허설 시작 — 약 {args.minutes}분 + 마무리 약 1분. 송출/공지 없음, 가짜 채팅.")
    print(f"  코어: {cfg.vtuber.ws_url} (먼저 띄워두세요)\n")
    orch = Orchestrator(cfg, persona)
    try:
        asyncio.run(orch.run_one_now())
    except KeyboardInterrupt:
        print("\n중단됨")
    print("\n리허설 끝. 위 흐름이 어색하면 persona.yaml / config.yaml 을 다듬으세요.")
    return 0


def cmd_run(args) -> int:
    from .orchestrator import Orchestrator
    cfg, persona = _load(args)
    if not _gate(cfg, getattr(args, "force", False)):
        return 1
    orch = Orchestrator(cfg, persona)
    try:
        asyncio.run(orch.run())
    except KeyboardInterrupt:
        print("\n중단됨")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aist", description="AI 방송인 자동화 레이어")
    p.add_argument("--config", default=_find_default(["config.yaml", "config/config.yaml"]),
                   help="설정 파일 경로 (기본: config.yaml)")
    p.add_argument("--persona", default=_find_default(["persona.yaml", "config/persona.yaml"]),
                   help="페르소나 파일 경로 (기본: persona.yaml)")
    p.add_argument("--log", default="INFO", help="로그 레벨")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="설정·키 상태 점검").set_defaults(func=cmd_check)

    sp = sub.add_parser("plan", help="다음 방송 일정 + 종료 타임라인 미리보기")
    sp.add_argument("--count", type=int, default=5)
    sp.set_defaults(func=cmd_plan)

    sub.add_parser("persona", help="페르소나 프롬프트 출력").set_defaults(func=cmd_persona)

    sub.add_parser("doctor", help="실제 연결 점검(코어 WS / OBS)").set_defaults(func=cmd_doctor)

    sp = sub.add_parser("announce-preview", help="공지 문구 미리보기")
    sp.add_argument("--kind", choices=["start", "end", "both"], default="both")
    sp.add_argument("--count", type=int, default=3)
    sp.set_defaults(func=cmd_announce_preview)

    sp = sub.add_parser("build-persona", help="conf.yaml 에 페르소나/TTS/Live2D 주입(개조)")
    sp.add_argument("--conf", default="", help="Open-LLM-VTuber conf.yaml 경로(주면 그 파일을 패치)")
    sp.add_argument("--out", default="data/persona_prompt.txt", help="conf 없을 때 프롬프트 저장 경로")
    sp.add_argument("--live2d", default="", help="live2d_model_name 으로 설정할 값")
    sp.set_defaults(func=cmd_build_persona)

    sub.add_parser("report", help="직전 방송 리포트 생성(다시보기 학습)").set_defaults(func=cmd_report)

    sub.add_parser("content", help="컨텐츠 팩 생성(하이라이트 후보·제목 초안)").set_defaults(func=cmd_content)

    p_bn = sub.add_parser("broadcast-now", help="지금 한 방송만(시작 수동, 종료 자동)")
    p_bn.add_argument("--force", action="store_true",
                      help="패키지가 빠져 있어도 강행(중간에 멈출 수 있음)")
    p_bn.set_defaults(func=cmd_broadcast_now)
    p_wc = sub.add_parser("wait-core", help="코어가 뜰 때까지 대기(고정 대기 대신)")
    p_wc.add_argument("--timeout", type=int, default=300, help="최대 대기 초(기본 300)")
    p_wc.set_defaults(func=cmd_wait_core)
    p_reh = sub.add_parser("rehearse",
                           help="플랫폼·키·OBS 없이 방송 흐름만 돌려보기(가짜 채팅)")
    p_reh.add_argument("--minutes", type=int, default=3, help="리허설 길이(기본 3분)")
    p_reh.set_defaults(func=cmd_rehearse)
    p_run = sub.add_parser("run", help="완전 자동 루프(스케줄러)")
    p_run.add_argument("--force", action="store_true",
                       help="패키지가 빠져 있어도 강행(중간에 멈출 수 있음)")
    p_run.set_defaults(func=cmd_run)
    return p


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    _load_dotenv()
    _setup_logging(args.log)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
