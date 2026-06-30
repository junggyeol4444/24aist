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


def _load(args):
    from .config import load_config
    from .persona import Persona
    cfg = load_config(args.config)
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
    print(f"aist {__version__} — 설정 점검\n")
    print(f"  플랫폼          : {cfg.platform}")
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
    if cfg.platform == "twitch":
        print(f"    TWITCH         : channel={mark(s.twitch_channel)} token={mark(s.twitch_oauth_token)}(없으면 익명읽기)")
    if cfg.announce.naver_cafe.enabled:
        print(f"    NAVER          : token={mark(s.naver_access_token)} refresh={mark(s.naver_refresh_token)}")
    print("\n점검 완료. (실제 연결 테스트는 broadcast-now / run 으로)")
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


def cmd_broadcast_now(args) -> int:
    from .orchestrator import Orchestrator
    cfg, persona = _load(args)
    orch = Orchestrator(cfg, persona)
    try:
        asyncio.run(orch.run_one_now())
    except KeyboardInterrupt:
        print("\n중단됨")
    return 0


def cmd_run(args) -> int:
    from .orchestrator import Orchestrator
    cfg, persona = _load(args)
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

    sp = sub.add_parser("announce-preview", help="공지 문구 미리보기")
    sp.add_argument("--kind", choices=["start", "end", "both"], default="both")
    sp.add_argument("--count", type=int, default=3)
    sp.set_defaults(func=cmd_announce_preview)

    sp = sub.add_parser("build-persona", help="conf.yaml 에 페르소나/TTS/Live2D 주입(개조)")
    sp.add_argument("--conf", default="", help="Open-LLM-VTuber conf.yaml 경로(주면 그 파일을 패치)")
    sp.add_argument("--out", default="data/persona_prompt.txt", help="conf 없을 때 프롬프트 저장 경로")
    sp.add_argument("--live2d", default="", help="live2d_model_name 으로 설정할 값")
    sp.set_defaults(func=cmd_build_persona)

    sub.add_parser("broadcast-now", help="지금 한 방송만(시작 수동, 종료 자동)").set_defaults(func=cmd_broadcast_now)
    sub.add_parser("run", help="완전 자동 루프(스케줄러)").set_defaults(func=cmd_run)
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
