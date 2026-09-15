"""실행 준비 상태 점검 — "설정은 맞는데 정작 못 도는" 상태를 잡아낸다.

`check` 가 설정 값만 읽고 "점검 완료"를 찍는 바람에, 실제로는 websockets /
obsws-python 이 없어서 방송이 시작 즉시 중단되는 상태를 '준비됨'으로
오해할 수 있었다. 그래서 **켜져 있는 기능이 실제로 돌 수 있는지**(패키지가
설치돼 있는지, 코어 웹UI 가 받아져 있는지)를 여기서 따로 본다.

네트워크 없이 동작한다. import 가능 여부만 보고, 실제 연결은 `doctor` 몫.
"""

import os
import re
import sys
from dataclasses import dataclass
from importlib import util as _importlib_util
from pathlib import Path


# 이 프로젝트의 주 사용 환경은 윈도우다(README 도 윈도우가 먼저). 그래서
# 안내 문구는 윈도우 기준으로 내보내고, 리눅스/맥이면 셸 명령으로 바꾼다.
# 윈도우 사용자에게 `bash ...` 나 `./x.sh` 를 보여주면 그대로 막힌다.
IS_WINDOWS = os.name == "nt"


def hint(win: str, posix: str) -> str:
    """지금 OS 에서 실제로 칠 수 있는 명령을 돌려준다."""
    return win if IS_WINDOWS else posix


# 각 준비 항목을 해결하는 명령 (윈도우 / 리눅스·맥)
CMD_SETUP_ALL = (r"windows\설치.bat 더블클릭", "./run.sh setup")
CMD_FRONTEND = (r"windows\프론트엔드받기.bat 더블클릭", "./scripts/fetch_frontend.sh")
CMD_CORE_SETUP = (r"windows\코어준비.bat 더블클릭", "bash scripts/setup_openllm_vtuber.sh")


@dataclass
class Need:
    """켜져 있는 기능 하나가 요구하는 패키지."""
    feature: str      # 표시용 기능 이름
    module: str       # import 이름
    package: str      # pip 이름
    extra: str        # pip install -e ".[extra]" 의 extra 이름
    blocking: bool    # True 면 이게 없으면 방송이 성립하지 않음

    @property
    def installed(self) -> bool:
        try:
            return _importlib_util.find_spec(self.module) is not None
        except (ImportError, ValueError):
            return False


def needs(cfg) -> list[Need]:
    """현재 설정에서 **켜져 있는** 기능들이 요구하는 패키지 목록."""
    out: list[Need] = [
        # 코어 연결은 항상 필수 — 실패하면 orchestrator 가 사이클을 중단한다.
        Need("코어(Open-LLM-VTuber) 연결", "websockets", "websockets", "vtuber", True),
    ]

    # OBS: start_stream 이 꺼져 있으면 운영자가 수동으로 켜는 단계라 필수 아님.
    if cfg.obs.start_stream or cfg.obs.launch_if_not_running:
        out.append(Need("OBS 제어(송출)", "obsws_python", "obsws-python", "obs", True))

    # 채팅 — 채팅이 안 들어오면 방송이 성립하지 않으므로 blocking.
    per_platform = {
        "twitch": [("websockets", "websockets", "twitch")],
        "youtube": [("pytchat", "pytchat", "youtube")],
        "chzzk": [("websockets", "websockets", "chzzk"), ("requests", "requests", "chzzk")],
        "kick": [("websockets", "websockets", "kick"), ("requests", "requests", "kick")],
        "soop": [("websockets", "websockets", "soop"), ("requests", "requests", "soop")],
        "twitcasting": [("requests", "requests", "twitcasting")],
        "rehearsal": [],   # 가짜 채팅 — 추가 패키지 없음
    }
    for p in cfg.active_platforms():
        for mod, pkg, extra in per_platform.get(p, []):
            out.append(Need(f"채팅 수신({p})", mod, pkg, extra, True))

    # 아래는 없어도 방송 자체는 돌아간다 — 해당 기능만 꺼진다.
    if cfg.announce.discord.enabled:
        out.append(Need("디스코드 공지", "requests", "requests", "discord", False))
    if cfg.announce.naver_cafe.enabled:
        out.append(Need("네이버 카페 공지", "requests", "requests", "naver", False))
        if cfg.announce.naver_cafe.use_selenium_fallback:
            out.append(Need("네이버 카페 공지(셀레늄 보조)", "selenium", "selenium", "selenium", False))
    llm_mod = {
        "openai": ("openai", "openai"),
        "anthropic": ("anthropic", "anthropic"),
        "gemini": ("google.generativeai", "google-generativeai"),
    }.get(cfg.llm.provider)
    if llm_mod:
        out.append(Need(f"공지 문구 생성(LLM: {cfg.llm.provider})", llm_mod[0], llm_mod[1], "llm", False))
    if cfg.memory.backend == "chroma":
        out.append(Need("장기기억(chroma)", "chromadb", "chromadb", "memory", False))

    # 같은 패키지가 여러 기능에서 걸리면 한 줄로 합친다(blocking 우선).
    merged: dict[str, Need] = {}
    for n in out:
        cur = merged.get(n.module)
        if cur is None:
            merged[n.module] = n
        else:
            if n.blocking and not cur.blocking:
                cur.blocking = True
            if n.feature not in cur.feature:
                cur.feature = f"{cur.feature}, {n.feature}"
    return list(merged.values())


def missing(cfg) -> list[Need]:
    """설치돼 있지 않은 것만."""
    return [n for n in needs(cfg) if not n.installed]


def install_hint(items: list[Need]) -> str:
    """빠진 것들을 한 번에 까는 pip 명령."""
    extras = sorted({n.extra for n in items})
    return 'pip install -e ".[' + ",".join(extras) + ']"'


def repo_root() -> Path:
    """저장소 루트.

    보통은 이 패키지의 부모(`pip install -e .`). 다만 site-packages 설치나
    PyInstaller exe 로는 그게 저장소가 아니므로, 실행 위치에 코어가 있으면
    그쪽을 우선한다.
    """
    cwd = Path.cwd()
    if (cwd / "Open-LLM-VTuber").is_dir():
        return cwd
    return Path(__file__).resolve().parent.parent


def core_frontend_ready(root: Path | None = None) -> tuple[bool, str]:
    """코어 웹UI(프론트엔드)가 받아져 있는지.

    frontend/ 는 컴파일 산출물이라 커밋하지 않는다(README 만 있음).
    안 받으면 코어는 떠도 화면이 안 나온다.
    """
    root = root or repo_root()
    core = root / "Open-LLM-VTuber"
    if not core.is_dir():
        return False, "Open-LLM-VTuber/ 디렉터리가 없습니다"
    if (core / "frontend" / "index.html").is_file():
        return True, "받아짐"
    return False, ("프론트엔드(웹UI) 미설치 — " + hint(*CMD_FRONTEND) +
                   ". 다운로드가 막히면 손으로 받는 방법을 알려줍니다")


def core_conf_ready(root: Path | None = None) -> tuple[bool, str]:
    """코어의 conf.yaml 이 있는지.

    run_server.py 가 conf.yaml 을 바로 읽는다 — 없으면 코어가 뜨지 않는다.
    conf.korean.yaml(한국어 개조본)을 복사해서 만든다.
    """
    root = root or repo_root()
    core = root / "Open-LLM-VTuber"
    if not core.is_dir():
        return False, "Open-LLM-VTuber/ 디렉터리가 없습니다"
    if (core / "conf.yaml").is_file():
        return True, "있음"
    if (core / "conf.korean.yaml").is_file():
        return False, ("conf.yaml 없음 — " + hint(*CMD_CORE_SETUP) +
                       " (또는 conf.korean.yaml 을 conf.yaml 로 복사)")
    return False, "conf.yaml 없음 (conf.korean.yaml 도 없음 — 저장소가 온전한지 확인)"


# 코어가 실제로 뜨려면 코어 자신의 의존성(fastapi/loguru/tomli ...)도 필요하다.
# 코어는 보통 uv 로 자기 가상환경에서 돈다 — 그래서 aist 인터프리터에서
# import 되는지만 봐서는 단정할 수 없다. 둘 다 본다.
_CORE_MARKERS = ("tomli", "fastapi", "loguru")


def core_deps_ready(root: Path | None = None) -> tuple[bool, str]:
    """코어 의존성이 준비돼 보이는지(확정 아님 — 최종 판단은 doctor 의 WS 연결).

    코어 전용 가상환경(.venv)이 있으면 준비된 것으로 본다. 없으면 현재
    인터프리터에서 코어의 대표 모듈이 import 되는지 확인한다.
    """
    root = root or repo_root()
    core = root / "Open-LLM-VTuber"
    if not core.is_dir():
        return False, "Open-LLM-VTuber/ 디렉터리가 없습니다"
    if (core / ".venv").is_dir():
        return True, "코어 전용 .venv 있음"
    missing_markers = [m for m in _CORE_MARKERS
                       if Need("", m, m, "", False).installed is False]
    if not missing_markers:
        return True, "현재 환경에 설치됨"
    return False, (f"코어 의존성 미설치({', '.join(missing_markers)} 없음) — " +
                   hint(*CMD_CORE_SETUP))


def core_python_ok(root: Path | None = None) -> tuple[bool, str]:
    """지금 파이썬이 코어가 지원하는 범위인지.

    코어 pyproject 는 requires-python = ">=3.10,<3.13" 이다. python.org 에서
    '최신'을 받으면 그 범위 밖이라, aist 는 깔리는데(우리는 >=3.10) 코어
    설치만 실패한다 — 왜 실패하는지 알기 어려운 자리다.
    """
    root = root or repo_root()
    pyproject = root / "Open-LLM-VTuber" / "pyproject.toml"
    cur = tuple(sys.version_info)[:2]
    now = f"{cur[0]}.{cur[1]}"
    if not pyproject.is_file():
        return True, f"확인 못 함(코어 pyproject 없음) — 지금 {now}"

    text = pyproject.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'requires-python\s*=\s*["\']([^"\']+)["\']', text)
    if not m:
        return True, f"코어가 파이썬 범위를 명시하지 않음 — 지금 {now}"
    spec = m.group(1)

    lo = re.search(r'>=\s*(\d+)\.(\d+)', spec)
    hi = re.search(r'<\s*(\d+)\.(\d+)', spec)
    if lo and cur < (int(lo.group(1)), int(lo.group(2))):
        return False, f"파이썬 {now} 은 너무 낮습니다 — 코어 요구: {spec}"
    if hi and cur >= (int(hi.group(1)), int(hi.group(2))):
        newest = f"{hi.group(1)}.{int(hi.group(2)) - 1}"
        return False, (f"파이썬 {now} 은 코어가 지원하지 않습니다(코어 요구: {spec}). "
                       f"파이썬 {newest} 로 설치하세요 — aist 는 되는데 코어만 "
                       f"설치에 실패합니다")
    return True, f"{now} (코어 요구: {spec})"


# --------------------------------------------------------------------------- #
# 설정값 자체의 오류 — "설정은 맞아 보이는데 정작 방송이 이상한" 부류.
# 패키지가 다 깔려 있어도 여기서 걸리면 방송이 엉뚱하게 돈다.
# --------------------------------------------------------------------------- #
_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class Problem(str):
    """설정 문제 한 줄. 방송 자체를 막는지(blocking) 여부를 함께 담는다.

    문자열 그대로 쓸 수 있어서(출력·검색) 기존 호출부는 그대로 동작한다.
    구분이 필요한 이유: 디스코드 채널 ID 가 비었다고 "방송이 안 됩니다" 라고
    하면 거짓말이다. 공지만 안 올라갈 뿐 방송은 된다.
    """

    blocking: bool = True

    def __new__(cls, text: str, blocking: bool = True):
        obj = super().__new__(cls, text)
        obj.blocking = blocking
        return obj


def config_problems(cfg) -> list[str]:
    """config.yaml 값 자체의 문제를 사람이 읽는 문장으로 돌려준다.

    여기 걸리는 것들은 전부 조용히 잘못 도는 것들이라, 점검에서 잡아야 한다:
      - 타임존 오타 → 조용히 UTC 로 떨어져 방송이 9시간 어긋난다
      - 요일 키 오타(예: 한글 '월') → 그 요일이 조용히 휴방이 된다
      - 시각 형식 오류 → 방송 시작 계산에서 터진다
      - 전부 휴방 → 자동 운영을 켜도 영영 안 켜진다
    """
    out: list[str] = []
    sch = cfg.scheduler

    # 1) 타임존
    #
    # 윈도우에는 시스템 타임존 DB 가 없다. tzdata 패키지가 없으면 정상적인
    # 'Asia/Seoul' 도 실패한다 — 그때 "오타"라고 안내하면 운영자가 멀쩡한
    # 설정을 고치려 들게 된다. 원인을 구분해서 알려준다.
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(sch.timezone)
    except Exception:
        try:
            import tzdata  # noqa: F401
            has_tzdata = True
        except ImportError:
            has_tzdata = False
        import zoneinfo as _zi
        if not has_tzdata and not _zi.TZPATH:
            out.append(
                "타임존 데이터가 없습니다(윈도우는 시스템에 없음) → config 의 "
                f"timezone '{sch.timezone}' 이 무시되고 PC 로컬 시간으로 방송 "
                "시각이 계산됩니다. 고치기: pip install tzdata"
            )
        else:
            out.append(
                f"타임존 '{sch.timezone}' 을 찾을 수 없습니다 → 시간이 어긋납니다. "
                f"예: Asia/Seoul"
            )

    # 2) 요일 키
    unknown = [k for k in sch.weekly if k not in _WEEKDAY_KEYS]
    if unknown:
        out.append(
            f"스케줄 요일 키를 모르겠습니다: {', '.join(repr(k) for k in unknown)} → "
            f"그 요일은 휴방으로 처리됩니다. 써야 할 키: {', '.join(_WEEKDAY_KEYS)}"
        )

    # 3) 시각 형식
    from .scheduler import _parse_hhmm
    for day, times in sch.weekly.items():
        for t in (times or []):
            try:
                _parse_hhmm(t)
            except ValueError as e:
                out.append(f"스케줄 {day} 의 시각이 잘못됨: {e}")

    # 4) 전부 휴방인데 자동 운영이 켜져 있음
    if sch.enabled:
        has_any = any(
            (times or []) for k, times in sch.weekly.items() if k in _WEEKDAY_KEYS
        )
        if not has_any:
            out.append(
                "scheduler.enabled=true 인데 요일별 시작 시각이 하나도 없습니다 → "
                "`aist run` 이 영영 방송을 켜지 않습니다."
            )

    # 5) 종료 판단 값이 앞뒤가 안 맞음
    ej = cfg.end_judge
    if ej.min_minutes > ej.max_minutes:
        out.append(Problem(
            f"end_judge.min_minutes({ej.min_minutes}) 가 max_minutes({ej.max_minutes}) "
            f"보다 큽니다 → 최소 시간 보장이 이겨서 항상 {ej.min_minutes}분 방송이 됩니다.",
            blocking=False))
    if ej.scheduled_end_hhmm:
        try:
            _parse_hhmm(ej.scheduled_end_hhmm)
        except ValueError as e:
            out.append(f"end_judge.scheduled_end_hhmm 이 잘못됨: {e}")

    # 6) 공지를 켰는데 올릴 곳이 없음
    an = cfg.announce
    if (an.on_start or an.on_end) and not (an.discord.enabled or an.naver_cafe.enabled):
        out.append(Problem(
            "공지를 켰는데(on_start/on_end) 디스코드·네이버 카페가 둘 다 꺼져 있습니다 "
            "→ 공지가 아무 데도 안 올라갑니다.", blocking=False))
    if an.discord.enabled and not an.discord.channel_id:
        out.append(Problem(
            "디스코드 공지가 켜져 있는데 channel_id 가 0 입니다 → 게시 안 됩니다. "
            "(공지만 안 나갈 뿐 방송은 됩니다. 안 쓸 거면 announce.discord.enabled=false)",
            blocking=False))

    return out
