"""주 사용 환경은 윈도우다 — 안내가 윈도우에서 칠 수 없는 명령이면 안 된다.

윈도우 사용자에게 `bash ...` / `./x.sh` / `cd A && B` 를 보여주면 그대로
막힌다. 점검이 내놓는 모든 안내는 그 OS 에서 실제로 실행 가능해야 한다.
"""

import argparse
import io
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from aist import cli, preflight

# 윈도우 cmd 에서 안 먹는 것들
POSIX_ONLY = ("bash ", "./", " && ", ".sh")

WINDOWS_DIR = Path(__file__).resolve().parent.parent / "windows"


def _check_output(monkeypatch, *, windows: bool) -> str:
    monkeypatch.setattr(preflight, "IS_WINDOWS", windows)
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.cmd_check(argparse.Namespace(
            config="config/config.example.yaml",
            persona="config/persona.example.yaml",
        ))
    return buf.getvalue()


def test_windows_guidance_has_no_shell_commands(monkeypatch):
    out = _check_output(monkeypatch, windows=True)
    # 안내 줄만 본다(설정 요약에는 ws:// 같은 게 섞여 있다)
    lines = [ln for ln in out.splitlines()
             if "받기" in ln or "준비" in ln or "한 번에" in ln or "미설치" in ln]
    assert lines, "안내가 하나도 안 나왔다"
    for ln in lines:
        for bad in POSIX_ONLY:
            assert bad not in ln, f"윈도우 안내에 셸 명령이 샜다: {ln!r} ({bad!r})"


def test_windows_guidance_points_at_bat_files(monkeypatch):
    out = _check_output(monkeypatch, windows=True)
    assert ".bat" in out, "윈도우인데 .bat 안내가 없다"


def test_posix_guidance_uses_shell(monkeypatch):
    out = _check_output(monkeypatch, windows=False)
    assert "run.sh" in out or ".sh" in out


@pytest.mark.parametrize("name", [
    "설치.bat", "코어준비.bat", "프론트엔드받기.bat", "코어실행.bat",
    "점검.bat", "리허설.bat", "테스트방송.bat", "방송시작.bat",
    "전체실행.bat", "리포트.bat", "EXE만들기.bat",
])
def test_referenced_bat_exists(name):
    """안내가 가리키는 .bat 이 실제로 있어야 한다."""
    assert (WINDOWS_DIR / name).is_file(), f"windows/{name} 이 없다"


@pytest.mark.parametrize("name", [p.name for p in WINDOWS_DIR.glob("*.bat")])
def test_bat_files_are_crlf(name):
    """cmd 는 LF 만 있는 배치 파일에서 오작동할 수 있다."""
    raw = (WINDOWS_DIR / name).read_bytes()
    assert b"\r\n" in raw, f"windows/{name} 이 CRLF 가 아니다"


@pytest.mark.parametrize("name", [p.name for p in WINDOWS_DIR.glob("*.bat")])
def test_bat_files_do_not_tell_windows_users_to_run_sh(name):
    """배치 파일이 화면에 .sh 를 띄우면 안 된다.

    REM 주석(개발자용)과 도메인(astral.sh)은 사용자에게 안 보이므로 뺀다.
    보는 건 echo 로 실제 출력되는 줄뿐이다.
    """
    text = (WINDOWS_DIR / name).read_bytes().decode("utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.lower().startswith("echo"):
            continue
        cleaned = stripped.replace("astral.sh", "")   # uv 공식 문서 주소
        assert ".sh" not in cleaned, f"windows/{name} 이 화면에 .sh 를 안내한다: {stripped!r}"


def test_windows_has_unattended_option():
    """24시간 무인 운영은 이 프로젝트의 목적이다.

    리눅스는 deploy/systemd + install.sh 가 있었는데 윈도우는 아무 수단도
    없었다. 작업 스케줄러 등록/해제가 그 자리를 채운다.
    """
    reg = WINDOWS_DIR / "자동시작등록.bat"
    off = WINDOWS_DIR / "자동시작해제.bat"
    assert reg.is_file() and off.is_file()
    text = reg.read_bytes().decode("utf-8")
    assert "schtasks" in text, "작업 스케줄러에 등록하지 않는다"


def test_windows_installer_prepares_core():
    """설치.bat 이 코어 준비까지 해야 한다(리눅스 run.sh setup 과 동등)."""
    text = (WINDOWS_DIR / "설치.bat").read_bytes().decode("utf-8")
    assert "코어준비.bat" in text, "설치.bat 이 코어를 준비하지 않는다"
