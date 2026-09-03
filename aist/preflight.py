"""실행 준비 상태 점검 — "설정은 맞는데 정작 못 도는" 상태를 잡아낸다.

`check` 가 설정 값만 읽고 "점검 완료"를 찍는 바람에, 실제로는 websockets /
obsws-python 이 없어서 방송이 시작 즉시 중단되는 상태를 '준비됨'으로
오해할 수 있었다. 그래서 **켜져 있는 기능이 실제로 돌 수 있는지**(패키지가
설치돼 있는지, 코어 웹UI 가 받아져 있는지)를 여기서 따로 본다.

네트워크 없이 동작한다. import 가능 여부만 보고, 실제 연결은 `doctor` 몫.
"""

import os
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
