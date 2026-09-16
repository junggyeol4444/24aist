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
    # 메모장으로 편집하는 파일이라 인코딩이 제각각이다. BOM 이 붙으면 첫 줄의
    # 키 이름이 '\ufeffOPENAI_API_KEY' 가 되어 그 키만 조용히 사라진다 —
    # "키를 넣었는데 비어있음으로 나온다"는 추적 불가능한 증상이 된다.
    from .config import ConfigError, read_text_lenient
    try:
        text = read_text_lenient(p)
    except ConfigError as e:
        print(f"[경고] {e}")
        return
    for line in text.splitlines():
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
    _quiet_third_party()


def _quiet_third_party() -> None:
    """서드파티 라이브러리의 트레이스백을 화면에서 지운다.

    OBS 가 안 켜져 있으면 obsws_python 이 자기 로거로 파이썬 트레이스백
    14줄을 먼저 뿜는다. 바로 아래에 우리 한글 안내가 있는데도 그렇다.
    이 프로그램의 대상 사용자는 코딩을 안 하는 운영자다 — 저 출력을 보면
    크게 망가진 줄 안다. 사유는 우리 메시지로 이미 전달하므로 눌러둔다.
    (원인 추적이 필요하면 --log DEBUG 로 다시 볼 수 있다.)
    """
    root_level = logging.getLogger().getEffectiveLevel()
    if root_level <= logging.DEBUG:
        return
    for name in ("obsws_python", "obsws_python.baseclient",
                 "websockets", "websockets.client", "websockets.server",
                 "discord", "discord.client", "discord.gateway",
                 "urllib3", "httpx", "httpcore", "openai", "anthropic"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


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
    if Path(args.persona).exists():
        persona = Persona.load(args.persona)
    else:
        # 파일이 없으면 기본 캐릭터로 돈다 — 조용히 그러면 안 된다.
        # 방송인의 성격이 통째로 비는 것이고, 운영자는 자기가 적은 설정이
        # 왜 반영이 안 되는지 알 수 없다.
        persona = Persona()
        persona.problems = [
            f"페르소나 파일이 없습니다: {args.persona} — 기본 캐릭터로 돕니다. "
            f"config/persona.example.yaml 을 복사해서 만드세요."
        ]
        logging.getLogger("aist").warning("%s", persona.problems[0])
    return cfg, persona


# --------------------------------------------------------------- 커맨드들
def cmd_check(args) -> int:
    from .config import REHEARSAL_PLATFORM, ConfigError
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
        if p not in ids:
            # rehearsal 처럼 플랫폼 식별자가 없는 경우. 예전에는 여기서
            # KeyError 트레이스백이 그대로 떴다 — 점검이 프로그램 오류로
            # 끝나면 운영자는 뭘 고쳐야 할지 알 수 없다.
            note = ("리허설용 가짜 채팅 — 실제 방송에는 쓰지 않습니다"
                    if p == REHEARSAL_PLATFORM else "식별자 없음")
            print(f"    {p:<11}: {note}")
            continue
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
    py_ok, py_msg = preflight.core_python_ok()
    # 소리가 시청자에게 가는 경로(프록시)가 뚫려 있는지 — 이게 막히면
    # 방송은 '도는 것처럼' 보이면서 화면에는 아무것도 안 나온다.
    proxy_ok, proxy_msg = preflight.core_proxy_ready()
    files_ok, files_msg = preflight.core_startup_files_ready()
    persona_missing = any("페르소나 파일이 없습니다" in n
                          for n in getattr(persona, "problems", []))
    if persona_missing:
        persona_ok, persona_msg = False, "persona.yaml 이 없습니다(위 참고)"
    else:
        persona_ok, persona_msg = preflight.persona_applied_to_core(
            persona.render_system_prompt())
    fe_proxy_ok, fe_proxy_msg = preflight.frontend_proxy_ready()
    blockers = [n for n in miss if n.blocking]

    if getattr(persona, "problems", None):
        # 페르소나가 조용히 망가지면 캐릭터 자체가 달라진다.
        print("\n  페르소나 파일 문제 (그대로 두면 캐릭터가 달라집니다):")
        for note in persona.problems:
            print(f"    [!] {note}")

    if cfg.unknown_keys:
        # 오타 난 키는 조용히 무시된다 — "설정을 바꿨는데 아무 일도 안 일어난다".
        print("\n  설정 파일에서 무시된 키 (이름이 틀렸습니다):")
        for note in cfg.unknown_keys:
            print(f"    [!] {note}")

    problems = preflight.config_problems(cfg)
    hard_problems = [m for m in problems if getattr(m, "blocking", True)]
    if problems:
        print("\n  설정값 문제 (패키지가 다 깔려 있어도 방송이 이상하게 돕니다):")
        for msg in problems:
            print(f"    {'[X]' if getattr(msg, 'blocking', True) else '[!]'} {msg}")

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
    print(f"    파이썬 버전    : {'OK ' + py_msg if py_ok else '[X] ' + py_msg}")
    print(f"    코어 시작 파일 : {'OK' if files_ok else '[X] ' + files_msg}")
    print(f"    코어 프록시    : {'OK (enable_proxy 켜짐)' if proxy_ok else '[X] ' + proxy_msg}")
    print(f"    페르소나 반영  : {'OK' if persona_ok else '[X] ' + persona_msg}")
    print(f"    웹UI 접속경로  : {'OK (/proxy-ws)' if fe_proxy_ok else '[X] ' + fe_proxy_msg}")

    print()
    if (blockers or not fe_ok or not conf_ok or not deps_ok or not py_ok
            or not proxy_ok or not fe_proxy_ok or not files_ok or not persona_ok
            or hard_problems):
        print("지금 상태로는 방송이 안 됩니다. 아래를 먼저 해결하세요:")
        if hard_problems:
            print("  - 위 '설정값 문제' 부터 고치세요 (config.yaml)")
        if blockers:
            print(f"  - 패키지 설치: {preflight.install_hint(miss)}")
        if not fe_ok:
            print(f"  - 코어 웹UI 받기: {preflight.hint(*preflight.CMD_FRONTEND)}")
        if not conf_ok or not deps_ok:
            what = "설정" if conf_ok else "설정·의존성"
            print(f"  - 코어 {what} 준비: {preflight.hint(*preflight.CMD_CORE_SETUP)}")
        if not py_ok:
            print("  - 파이썬 버전 맞추기: 위 안내대로 다시 설치 후 .venv 를 지우고"
                  f" {preflight.hint(*preflight.CMD_SETUP_ALL)}")
        if not files_ok:
            print(f"  - 코어 시작 파일 채우기: {preflight.hint(*preflight.CMD_CORE_SETUP)}")
        if not persona_ok:
            print(f"  - 페르소나 코어에 반영: {preflight.hint(*preflight.CMD_PERSONA)}")
        if not proxy_ok:
            print("  - 코어 설정에 enable_proxy: true 넣기 (안 넣으면 시청자에게 "
                  "소리·자막이 안 갑니다)")
        if not fe_proxy_ok:
            print(f"  - 웹UI 접속 경로 고치기: {preflight.hint(*preflight.CMD_FRONTEND)}")
        print(f"  ( 한 번에: {preflight.hint(*preflight.CMD_SETUP_ALL)} )")
        return 1
    if miss or len(problems) > len(hard_problems):
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
            # 실제 방송이 쓰는 계산을 그대로 쓴다. 단순히 "종료 N분 전" 으로
            # 적으면 방송이 짧을 때 시작보다 이른 시각이 찍힌다(min 0/max 2분
            # 이면 19:00 시작인데 예고 18:42 로 나왔다).
            pre = ej.pre_notice_at()
            note = ""
            if pre <= first_start:
                note = "  ← 방송이 짧아 시작하자마자 마무리 예고 단계입니다"
            print(f"  마무리 예고 : {pre.strftime('%H:%M')}{note}")
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
    py_ok, py_msg = preflight.core_python_ok()
    if not py_ok:
        ok = False
        print(f"  [X] 파이썬 버전: {py_msg}\n")

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
        if cfg.vtuber.ws_url.rstrip("/").endswith("/proxy-ws"):
            ok2, msg2 = preflight.core_proxy_ready()
            if not ok2:
                print(f"       → {msg2}")

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
            # 예전에는 무조건 [OK] 로 찍었다. 그런데 각 플랫폼 probe 는
            # 실패해도 예외 대신 설명 문자열을 돌려주기 때문에, 토큰이
            # 틀려도 "[OK] ... 조회 실패" 라고 나오고 doctor 는 "모두 OK"
            # 로 끝났다. 운영자가 방송 전 점검을 믿을 수 없게 된다.
            level = getattr(status, "level", "ok")
            tag = {"ok": "[OK]", "warn": "[!]"}.get(level, "[X]")
            if level == "fail":
                ok = False
            print(f"    {tag} {p:<11}: {status}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"    [X] {p:<11}: 점검 실패 — {e}")

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
        from .config import read_text_lenient
        from .paths import unique_path
        original = read_text_lenient(target)   # 메모장이 저장한 인코딩도 읽는다

        wanted = [(["character_config", "persona_prompt"], prompt),
                  # GPT-SoVITS 를 TTS 로 지정(한국어). 세부 ref_audio 는 운영자가 채움.
                  (["character_config", "tts_config", "tts_model"], "gpt_sovits_tts")]
        if args.live2d:
            wanted.append((["character_config", "live2d_model_name"], args.live2d))

        # 1순위: 주석을 살린 채 값만 갈아끼운다. 코어 conf.yaml 은 설명
        # 주석이 빽빽하고, 운영자가 거기서 LLM 키·TTS 경로를 직접 채운다.
        kept_comments = True
        try:
            from .conf_patch import ConfPatchError, set_value
            text = original
            for path_keys, value in wanted:
                text = set_value(text, path_keys, value)
        except Exception as e:  # noqa: BLE001 - 형식이 예상과 다르면 물러선다
            log = logging.getLogger("aist.cli")
            log.info("주석 유지 방식 실패(%s) → 값만 다시 씁니다(주석은 사라집니다)", e)
            kept_comments = False
            data = yaml.safe_load(original) or {}
            cc = data.get("character_config")
            if not isinstance(cc, dict):     # 'character_config:' 만 있고 비어 있는 경우
                cc = {}
                data["character_config"] = cc
            for path_keys, value in wanted:
                node = data
                for k in path_keys[:-1]:
                    nxt = node.get(k)
                    if not isinstance(nxt, dict):
                        nxt = {}
                        node[k] = nxt
                    node = nxt
                node[path_keys[-1]] = value
            text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

        # 백업은 덮어쓰지 않는다. 두 번 돌리면 원본 백업이 개조본으로
        # 바뀌어 되돌릴 수 없게 된다.
        backup = unique_path(target.with_suffix(target.suffix + ".bak"))
        backup.write_text(original, encoding="utf-8")
        target.write_text(text, encoding="utf-8")
        print(f"개조 완료: {target}\n  - character_config.persona_prompt 주입")
        print(f"  - tts_config.tts_model = gpt_sovits_tts")
        if args.live2d:
            print(f"  - live2d_model_name = {args.live2d}")
        print(f"  (원본 백업: {backup})")
        if not kept_comments:
            print("  ※ 이 파일의 설명 주석은 사라졌습니다. 원래 설명은 백업 파일에 있습니다.")
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
    path = generate_report(memory, cfg.logging.reports_dir, transcript_path=latest,
                           tz_name=cfg.scheduler.timezone)
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


async def _run_with_signals(orch, coro_name: str) -> None:
    """Ctrl+C / 종료 신호를 받으면 '중단 요청'으로 바꿔 정상 종료를 태운다.

    그냥 KeyboardInterrupt 가 올라가게 두면 방송 루프가 취소되면서 뒷정리
    (OBS 스트림 내리기·기록 저장)가 통째로 건너뛰어진다. 실제로 확인한
    문제다 — 스트림이 켜진 채 남는다. 그래서 신호를 잡아 request_stop()
    으로 바꾸고, 방송이 스스로 마무리하게 한다.

    윈도우는 add_signal_handler 가 없어서 signal.signal 로 대체한다.
    """
    import signal

    loop = asyncio.get_running_loop()
    task = asyncio.ensure_future(getattr(orch, coro_name)())
    asked = {"n": 0}

    def _ask_stop():
        asked["n"] += 1
        if asked["n"] == 1:
            print("\n중단 요청 — 방송을 정상적으로 내리는 중입니다 "
                  "(OBS 스트림 종료·기록 저장). 한 번 더 누르면 즉시 끕니다.")
            orch.request_stop()
        else:
            print("\n즉시 중단합니다. OBS 스트림이 켜진 채 남을 수 있습니다.")
            task.cancel()

    installed = []
    for signame in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _ask_stop)
            installed.append(("loop", sig))
        except (NotImplementedError, RuntimeError, AttributeError, ValueError):
            # 윈도우 / 메인 스레드가 아닐 때
            try:
                prev = signal.signal(sig, lambda *_a: _ask_stop())
                installed.append(("signal", sig, prev))
            except (ValueError, OSError):
                pass
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        for entry in installed:
            try:
                if entry[0] == "loop":
                    loop.remove_signal_handler(entry[1])
                else:
                    signal.signal(entry[1], entry[2])
            except Exception:  # noqa: BLE001 - 정리 실패는 무시
                pass


def _acquire_single(cfg):
    """중복 실행 잠금. 이미 돌고 있으면 None 을 돌려준다(그리고 안내 출력).

    같은 방송을 두 번 켜면 AI 가 채팅마다 두 번 말하고, 먼저 끝난 쪽이
    OBS 송출을 내려 아직 방송 중인 쪽 화면이 꺼진다.
    """
    from .single_instance import InstanceLock, lock_path_for
    lock = InstanceLock(lock_path_for(cfg.safety.stop_flag_path))
    if lock.acquire():
        return lock
    print("이미 방송 프로그램이 돌고 있습니다 — 이 창은 그냥 닫으세요.")
    print("  같은 방송을 두 번 켜면 AI 가 채팅마다 두 번 말하고,")
    print("  먼저 끝나는 쪽이 OBS 송출을 내려 화면이 꺼집니다.")
    print("  돌고 있는 방송을 끝내려면: windows\\중단.bat (또는 aist stop)")
    return None


def cmd_broadcast_now(args) -> int:
    from .orchestrator import Orchestrator
    cfg, persona = _load(args)
    if not _gate(cfg, getattr(args, "force", False)):
        return 1
    lock = _acquire_single(cfg)
    if lock is None:
        return 1
    orch = Orchestrator(cfg, persona)
    try:
        asyncio.run(_run_with_signals(orch, "run_one_now"))
    except KeyboardInterrupt:
        print("\n중단됨")
    finally:
        lock.release()
    return 0


def cmd_stop(args) -> int:
    """지금 도는 방송에 중단을 요청한다(사고 시 킬스위치).

    프로세스 간 통신 대신 파일 하나를 쓴다. 윈도우/리눅스 어디서나 같게
    동작하고, 원격에서 파일만 만들 수 있어도 끌 수 있다.
    """
    from .config import load_config
    from .safety import StopFlag
    cfg = load_config(args.config)
    flag = StopFlag(cfg.safety.stop_flag_path)
    if getattr(args, "clear", False):
        flag.clear()
        print(f"중단 스위치를 해제했습니다: {flag.path}")
        return 0
    p = flag.raise_(args.reason or "운영자 중단 요청")
    print(f"중단 스위치를 올렸습니다: {p}")
    print("  도는 방송이 있으면 몇 초 안에 마무리 절차로 들어갑니다")
    print("  (OBS 스트림 종료 · 기록 저장까지 하고 끝냅니다).")
    print(f"  해제: aist stop --clear   (안 지우면 다음 방송 시작 시 자동으로 지워집니다)")
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
    # 게시처만 끄면 공지 문구는 그대로 만들어져 로그에 "[공지/start] ..." 로
    # 찍힌다. 화면에 "공지 없음" 이라고 해놓고 공지가 찍히면 운영자는
    # 공지가 나간 줄 안다. 리허설에서는 공지 단계 자체를 건너뛴다.
    # (문구를 보고 싶으면 `aist announce-preview`)
    cfg.announce.on_start = False
    cfg.announce.on_end = False
    cfg.end_judge.min_minutes = 0
    cfg.end_judge.max_minutes = max(1, args.minutes)
    # 마무리 단계도 리허설 길이에 맞춰 줄인다. 실제 방송의 기본값(유예 5분,
    # 여운 45초)을 그대로 쓰면 1분 리허설이 7분 걸린다.
    cfg.end_judge.end_jitter_min = 0
    cfg.end_judge.wind_down.end_grace_minutes = 1
    cfg.end_judge.wind_down.closing_wait_sec = 10

    # 리허설은 진짜 기억·리포트를 건드리면 안 된다. 가짜 시청자/후원이
    # 장기기억에 들어가면 다음 실제 방송 공지에 "저번 방송 땐 N명 왔었고"
    # 처럼 인용된다. 산출물은 전부 data/rehearsal/ 아래로 보낸다.
    reh = Path(args.rehearsal_dir)
    cfg.memory.path = str(reh / "memory")
    cfg.logging.dir = str(reh / "logs")
    cfg.logging.reports_dir = str(reh / "reports")
    cfg.logging.content_dir = str(reh / "content")
    print(f"  산출물(기억/리포트/트랜스크립트)은 {reh}/ 에만 씁니다 — "
          "실제 기억은 건드리지 않습니다.")

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
        asyncio.run(_run_with_signals(orch, "run_one_now"))
    except KeyboardInterrupt:
        print("\n중단됨")
    print("\n리허설 끝. 위 흐름이 어색하면 persona.yaml / config.yaml 을 다듬으세요.")
    return 0


def cmd_run(args) -> int:
    from .orchestrator import Orchestrator
    cfg, persona = _load(args)
    if not _gate(cfg, getattr(args, "force", False)):
        return 1
    lock = _acquire_single(cfg)
    if lock is None:
        return 1
    orch = Orchestrator(cfg, persona)
    try:
        asyncio.run(_run_with_signals(orch, "run"))
    except KeyboardInterrupt:
        print("\n중단됨")
    finally:
        lock.release()
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
    p_reh.add_argument("--rehearsal-dir", default="data/rehearsal",
                       help="리허설 산출물 경로(실제 기억과 분리)")
    p_reh.set_defaults(func=cmd_rehearse)
    p_run = sub.add_parser("run", help="완전 자동 루프(스케줄러)")
    p_run.add_argument("--force", action="store_true",
                       help="패키지가 빠져 있어도 강행(중간에 멈출 수 있음)")
    p_run.set_defaults(func=cmd_run)

    p_stop = sub.add_parser(
        "stop", help="지금 도는 방송을 정상 종료시킨다(사고 시 킬스위치)")
    p_stop.add_argument("--reason", default="", help="중단 사유(기록용)")
    p_stop.add_argument("--clear", action="store_true", help="중단 스위치 해제")
    p_stop.set_defaults(func=cmd_stop)
    return p


def _fix_output_encoding() -> None:
    """출력이 콘솔이 아닐 때 한글/기호에서 죽지 않게 한다.

    윈도우에서 stdout 이 콘솔이면 파이썬이 유니코드 API 로 쓰지만,
    파일이나 파이프로 리다이렉트되면 로케일 인코딩(한국어 윈도우는
    cp949)을 쓴다. 그런데 우리가 안내문에 쓰는 em dash 는 cp949 에 없다:

        UnicodeEncodeError: 'cp949' codec can't encode character '\u2014'

    무인 운영은 콘솔 없이 도는 자리라 정확히 이 조건이다. 배치들이 이미
    chcp 65001 로 UTF-8 을 쓰므로 여기서도 UTF-8 로 맞추고, 그래도 못 쓰는
    문자가 있으면 죽는 대신 대체한다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            # 테스트의 캡처 스트림 등 reconfigure 를 지원하지 않는 경우.
            pass


def main(argv=None) -> int:
    _fix_output_encoding()
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    _load_dotenv()
    _setup_logging(args.log)
    from .config import ConfigError
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except (ConfigError, FileNotFoundError) as e:
        # 설정/페르소나 파일 문제는 운영자가 고칠 수 있는 것들이다.
        # 파이썬 트레이스백을 보여주면 고칠 수 있는 사람도 못 고친다.
        print(f"\n[오류] {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
